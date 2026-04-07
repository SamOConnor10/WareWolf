from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
import numpy as np
import pandas as pd

from django.db.models import Q, Sum
from django.utils import timezone

from inventory.models import Order, OrderLine, DemandAnomaly


@dataclass
class AnomalyResult:
    item_id: int
    date: str          # EU formatted string "DD/MM/YYYY"
    quantity: int
    score: float       # robust z-score (higher = more anomalous)
    severity: str      # LOW | MEDIUM | HIGH


def build_daily_sales_df(days_back: int = 120) -> pd.DataFrame:
    """
    Returns daily SALE quantities per item for the last `days_back` days
    ending at the latest SALE order date in the database (not today's date).
    """
    # Find latest date that actually exists in the data
    latest = (
        Order.objects.filter(order_type=Order.TYPE_SALE)
        .order_by("-order_date")
        .values_list("order_date", flat=True)
        .first()
    )
    if not latest:
        return pd.DataFrame()

    end = latest
    start = end - timedelta(days=days_back)

    qs = (
        OrderLine.objects.filter(
            order__order_type=Order.TYPE_SALE,
            order__order_date__range=(start, end),
        )
        .values("item_id", "order__order_date")
        .annotate(y=Sum("quantity"))
        .order_by("item_id", "order__order_date")
    )

    rows = []
    for r in qs.iterator(chunk_size=8000):
        rows.append(
            {"item_id": r["item_id"], "ds": r["order__order_date"], "y": int(r["y"] or 0)}
        )
    df = pd.DataFrame(rows)
    if df.empty:
        return df

    df["ds"] = pd.to_datetime(df["ds"])
    return df


def _mad(x: np.ndarray) -> float:
    """Median Absolute Deviation."""
    med = np.median(x)
    return float(np.median(np.abs(x - med)))


def detect_sales_anomalies(
    days_back: int = 120,
    min_points: int = 28,
    last_n_days_only: int = 14,
    z_thresh_low: float = 3.5,
    z_thresh_med: float = 5.0,
    z_thresh_high: float = 6.5,
    *,
    min_nonzero_days_in_hist: int = 5,
    sparse_abs_min_qty: int = 45,
    mad_zero_med_multiplier: float = 8.0,
    max_recent_days_per_item: int = 1,
    min_qty_for_flag: int = 4,
) -> list[AnomalyResult]:
    """
    Robust anomaly detection using rolling median + MAD robust z-score.
    Pure numpy/pandas (no scipy/sklearn).

    - Builds a per-item continuous daily demand series (missing days -> 0).
    - Computes robust z-score against a rolling history window.
    - Flags positive spikes above thresholds in the last N days.

    Sparse-demand guardrails: when MAD is 0 (many zero-demand days), we do not
    treat small restocks as z≈6 spikes unless there is enough non-zero history
    or the absolute quantity is very large. Per-SKU we keep at most
    ``max_recent_days_per_item`` day(s) in the window (strongest by score) so
    routine catalogues do not produce hundreds of rows per scan.
    """
    df = build_daily_sales_df(days_back=days_back)
    if df.empty:
        return []

    results: list[AnomalyResult] = []
    end_date = df["ds"].max().date()
    start_recent = end_date - timedelta(days=last_n_days_only)

    series_start_ts = pd.Timestamp(end_date - timedelta(days=days_back))

    for item_id, g in df.groupby("item_id"):
        g = g.sort_values("ds")
        g = g[g["ds"] >= series_start_ts].copy()
        g_dates = g["ds"].dt.date
        if not ((g_dates >= start_recent) & (g["y"] > 0)).any():
            continue
        g = g.set_index("ds").asfreq("D", fill_value=0).reset_index()

        if len(g) < min_points:
            continue

        # Rolling window for context (past-only). Only score days in the "recent"
        # window — scoring earlier days is unnecessary and was the main CPU cost.
        window = 14
        y = g["y"].astype(float).values
        g["ds_date"] = g["ds"].dt.date
        recent_mask = g["ds_date"] >= start_recent
        recent_indices = np.flatnonzero(recent_mask.to_numpy())

        scores = np.zeros(len(g), dtype=float)
        for i in recent_indices:
            left = max(0, i - window)
            hist = y[left:i]

            if len(hist) < 7:
                scores[i] = 0.0
                continue

            med = np.median(hist)
            mad = _mad(hist)

            if mad == 0:
                nonzero_hist = int(np.count_nonzero(hist))
                if med == 0:
                    if nonzero_hist < min_nonzero_days_in_hist:
                        scores[i] = (
                            7.0 if y[i] >= sparse_abs_min_qty else 0.0
                        )
                    elif y[i] >= 20:
                        scores[i] = 6.0
                    else:
                        scores[i] = 0.0
                elif med > 0 and y[i] >= (med * mad_zero_med_multiplier):
                    if nonzero_hist < min_nonzero_days_in_hist:
                        scores[i] = 0.0
                    else:
                        scores[i] = 5.0
                else:
                    scores[i] = 0.0
                continue

            scores[i] = 0.6745 * (y[i] - med) / mad

        g["robust_z"] = scores

        recent = g[
            (g["ds_date"] >= start_recent)
            & (g["y"] >= min_qty_for_flag)
            & (g["robust_z"] >= z_thresh_low)
        ]

        item_candidates: list[AnomalyResult] = []
        for row in recent.itertuples(index=False):
            ds = row.ds
            qty = int(row.y)
            z = float(row.robust_z)

            if z >= z_thresh_high or qty >= 30:
                sev = DemandAnomaly.SEV_HIGH
            elif z >= z_thresh_med or qty >= 15:
                sev = DemandAnomaly.SEV_MED
            else:
                sev = DemandAnomaly.SEV_LOW

            item_candidates.append(
                AnomalyResult(
                    item_id=int(item_id),
                    date=ds.strftime("%d/%m/%Y"),
                    quantity=qty,
                    score=z,
                    severity=sev,
                )
            )

        if item_candidates:
            item_candidates.sort(key=lambda r: (-r.score, r.date))
            if max_recent_days_per_item > 0:
                item_candidates = item_candidates[:max_recent_days_per_item]
            results.extend(item_candidates)

    # Sort: High severity first, then highest score
    sev_rank = {"HIGH": 0, "MEDIUM": 1, "LOW": 2}
    results.sort(key=lambda r: (sev_rank.get(r.severity, 9), -r.score))
    return results


def anomaly_keep_set(results: list[AnomalyResult]) -> set[tuple[int, date]]:
    keep: set[tuple[int, date]] = set()
    for r in results:
        d = pd.to_datetime(r.date, dayfirst=True).date()
        keep.add((r.item_id, d))
    return keep


def prune_stale_anomalies_not_in_results(keep: set[tuple[int, date]]) -> int:
    """
    Remove DemandAnomaly rows whose (item, date) is not in the latest detection
    output. After rule changes, re-running the scan replaces the table with the
    current findings only. Uses a single SQL DELETE (exclude OR pairs), not N
    row-by-row deletes.
    """
    if not keep:
        deleted, _ = DemandAnomaly.objects.all().delete()
        return deleted
    pair_q = Q()
    for item_id, d in keep:
        pair_q |= Q(item_id=item_id, date=d)
    deleted, _ = DemandAnomaly.objects.exclude(pair_q).delete()
    return deleted


def save_anomalies(results: list[AnomalyResult]):
    """
    Persist anomalies in DemandAnomaly.
    Avoid duplicates using (item, date). Updates existing rows if re-run.
    Returns number of *new* records created.
    """
    if not results:
        return 0, []

    parsed = []
    for r in results:
        d = pd.to_datetime(r.date, dayfirst=True).date()
        parsed.append((r.item_id, d, r))
    # Last write wins if detection ever emits duplicate (item, date).
    dedup = {}
    for item_id, d, r in parsed:
        dedup[(item_id, d)] = r
    parsed = [(k[0], k[1], dedup[k]) for k in dedup]

    keys = list({(i, d) for i, d, _ in parsed})
    existing = {}
    chunk_size = 400
    for off in range(0, len(keys), chunk_size):
        chunk = keys[off : off + chunk_size]
        q = Q()
        for item_id, d in chunk:
            q |= Q(item_id=item_id, date=d)
        for o in DemandAnomaly.objects.filter(q).only(
            "id", "item_id", "date", "quantity", "score", "severity"
        ):
            existing[(o.item_id, o.date)] = o

    to_create = []
    to_update = []
    for item_id, d, r in parsed:
        key = (item_id, d)
        if key in existing:
            o = existing[key]
            o.quantity = r.quantity
            o.score = float(r.score)
            o.severity = r.severity
            to_update.append(o)
        else:
            to_create.append(
                DemandAnomaly(
                    item_id=item_id,
                    date=d,
                    quantity=r.quantity,
                    score=float(r.score),
                    severity=r.severity,
                )
            )

    if to_update:
        DemandAnomaly.objects.bulk_update(
            to_update, ["quantity", "score", "severity"], batch_size=500
        )

    created = 0
    created_objs = []
    if to_create:
        DemandAnomaly.objects.bulk_create(to_create, batch_size=500)
        created = len(to_create)
        q = Q()
        for x in to_create:
            q |= Q(item_id=x.item_id, date=x.date)
        fetched = {
            (o.item_id, o.date): o
            for o in DemandAnomaly.objects.filter(q).select_related("item")
        }
        for item_id, d, r in parsed:
            if (item_id, d) not in existing and (item_id, d) in fetched:
                created_objs.append(fetched[(item_id, d)])

    return created, created_objs
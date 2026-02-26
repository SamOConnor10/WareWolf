from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
import numpy as np
import pandas as pd

from django.db.models import Sum
from django.utils import timezone

from inventory.models import Order, DemandAnomaly


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
        Order.objects.filter(order_type=Order.TYPE_SALE, order_date__range=(start, end))
        .values("item_id", "order_date")
        .annotate(y=Sum("quantity"))
        .order_by("item_id", "order_date")
    )

    rows = [{"item_id": r["item_id"], "ds": r["order_date"], "y": int(r["y"] or 0)} for r in qs]
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
    min_points: int = 21,
    last_n_days_only: int = 14,
    z_thresh_low: float = 3.0,
    z_thresh_med: float = 4.0,
    z_thresh_high: float = 5.0,
) -> list[AnomalyResult]:
    """
    Robust anomaly detection using rolling median + MAD robust z-score.
    Pure numpy/pandas (no scipy/sklearn).

    - Builds a per-item continuous daily demand series (missing days -> 0).
    - Computes robust z-score against a rolling history window.
    - Flags positive spikes (y>0) above thresholds in the last N days.
    """
    df = build_daily_sales_df(days_back=days_back)
    if df.empty:
        return []

    results: list[AnomalyResult] = []
    end_date = df["ds"].max().date()
    start_recent = end_date - timedelta(days=last_n_days_only)

    for item_id, g in df.groupby("item_id"):
        g = g.sort_values("ds").copy()
        g = g.set_index("ds").asfreq("D", fill_value=0).reset_index()

        if len(g) < min_points:
            continue

        # Rolling window for context (past-only)
        window = 14
        y = g["y"].astype(float).values
        scores = np.zeros(len(g), dtype=float)

        for i in range(len(g)):
            left = max(0, i - window)
            right = i  # past only
            hist = y[left:right]

            # Need enough past points to compute a stable median/MAD
            if len(hist) < 7:
                scores[i] = 0.0
                continue

            med = np.median(hist)
            mad = _mad(hist)

            if mad == 0:
                # Fallback for sparse demand:
                # if typical is ~0 and today is a spike, flag it with a synthetic score
                if med == 0 and y[i] >= 10:
                    scores[i] = 6.0  # treat as strong anomaly
                elif med > 0 and y[i] >= (med * 5):
                    scores[i] = 5.0
                else:
                    scores[i] = 0.0
                continue

            # Normal robust z-score
            scores[i] = 0.6745 * (y[i] - med) / mad

        g["robust_z"] = scores
        g["ds_date"] = g["ds"].dt.date

        # Only recent positive spikes
        recent = g[
            (g["ds_date"] >= start_recent)
            & (g["y"] > 0)
            & (g["robust_z"] >= z_thresh_low)
        ]

        for _, row in recent.iterrows():
            qty = int(row["y"])
            z = float(row["robust_z"])

            if z >= z_thresh_high or qty >= 30:
                sev = DemandAnomaly.SEV_HIGH
            elif z >= z_thresh_med or qty >= 15:
                sev = DemandAnomaly.SEV_MED
            else:
                sev = DemandAnomaly.SEV_LOW

            results.append(
                AnomalyResult(
                    item_id=int(item_id),
                    date=row["ds"].strftime("%d/%m/%Y"),
                    quantity=qty,
                    score=z,
                    severity=sev,
                )
            )

    # Sort: High severity first, then highest score
    sev_rank = {"HIGH": 0, "MEDIUM": 1, "LOW": 2}
    results.sort(key=lambda r: (sev_rank.get(r.severity, 9), -r.score))
    return results


def save_anomalies(results: list[AnomalyResult]):
    """
    Persist anomalies in DemandAnomaly.
    Avoid duplicates using (item, date). Updates existing rows if re-run.
    Returns number of *new* records created.
    """
    created = 0
    created_objs = []

    for r in results:
        d = pd.to_datetime(r.date, dayfirst=True).date()

        obj, was_created = DemandAnomaly.objects.get_or_create(
            item_id=r.item_id,
            date=d,
            defaults={
                "quantity": r.quantity,
                "score": float(r.score),
                "severity": r.severity,
            },
        )

        if was_created:
            created += 1
            created_objs.append(obj)
        else:
            # Update existing anomaly in case thresholds change / rerun
            obj.quantity = r.quantity
            obj.score = float(r.score)
            obj.severity = r.severity
            obj.save(update_fields=["quantity", "score", "severity"])

    return created, created_objs
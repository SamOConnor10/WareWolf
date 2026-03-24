from __future__ import annotations

import datetime
import math
import re
from dataclasses import dataclass
from typing import Any

import numpy as np
import pandas as pd
from django.db.models import Sum
from django.utils import timezone

from inventory.models import Activity, Item, Order, OrderLine, StockHistory


@dataclass
class ForecastModelBundle:
    model_name: str
    model: Any
    baseline_name: str
    baseline_series: pd.Series
    used_fallback: bool
    fallback_reason: str


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        if value is None:
            return float(default)
        return float(value)
    except (TypeError, ValueError):
        return float(default)


def _mape(y_true: np.ndarray, y_pred: np.ndarray) -> float:
    denom = np.maximum(np.abs(y_true), 1.0)
    return float(np.mean(np.abs((y_true - y_pred) / denom)) * 100.0)


def _build_from_stock_snapshots(start_date: datetime.date, end_date: datetime.date) -> pd.DataFrame:
    current_items = list(Item.objects.filter(is_active=True).values("id", "quantity"))
    qty_by_item = {row["id"]: int(row["quantity"] or 0) for row in current_items}
    current_total_units = int(sum(qty_by_item.values()))

    if not qty_by_item:
        return pd.DataFrame([{"date": end_date, "total_units": 0}])

    pre_range_rows = (
        StockHistory.objects.filter(item_id__in=qty_by_item.keys(), date__lt=start_date)
        .values("item_id", "date", "quantity")
        .order_by("item_id", "-date")
    )
    seen_pre = set()
    for row in pre_range_rows:
        item_id = row["item_id"]
        if item_id in seen_pre:
            continue
        qty_by_item[item_id] = int(row["quantity"] or 0)
        seen_pre.add(item_id)

    range_rows = (
        StockHistory.objects.filter(item_id__in=qty_by_item.keys(), date__range=(start_date, end_date))
        .values("item_id", "date", "quantity")
        .order_by("date", "item_id")
    )
    first_in_range_by_item: dict[int, int] = {}
    updates_by_day: dict[datetime.date, list[tuple[int, int]]] = {}
    for row in range_rows:
        day = row["date"]
        item_id = row["item_id"]
        qty = int(row["quantity"] or 0)
        if item_id not in first_in_range_by_item:
            first_in_range_by_item[item_id] = qty
        updates_by_day.setdefault(day, []).append((item_id, qty))

    for item_id in list(qty_by_item.keys()):
        if item_id in seen_pre:
            continue
        if item_id in first_in_range_by_item:
            qty_by_item[item_id] = first_in_range_by_item[item_id]

    rows: list[dict[str, Any]] = []
    running_total = int(sum(qty_by_item.values()))
    cursor = start_date
    while cursor <= end_date:
        for item_id, new_qty in updates_by_day.get(cursor, []):
            old_qty = qty_by_item.get(item_id, 0)
            qty_by_item[item_id] = new_qty
            running_total += int(new_qty - old_qty)
        running_total = max(0, int(running_total))
        rows.append({"date": cursor, "total_units": running_total})
        cursor += datetime.timedelta(days=1)

    if rows:
        rows[-1]["total_units"] = max(0, current_total_units)
    return pd.DataFrame(rows)


def _reconstruct_from_movements(start_date: datetime.date, end_date: datetime.date) -> pd.DataFrame:
    current_total_units = int(Item.objects.filter(is_active=True).aggregate(total=Sum("quantity"))["total"] or 0)

    order_rows = (
        OrderLine.objects.filter(
            order__status=Order.STATUS_DELIVERED,
            order__stock_applied=True,
            order__order_date__range=(start_date, end_date),
        )
        .values("order__order_date", "order__order_type")
        .annotate(total_qty=Sum("quantity"))
        .order_by("order__order_date")
    )

    daily_deltas: dict[datetime.date, int] = {}
    for row in order_rows:
        day = row["order__order_date"]
        qty = int(row["total_qty"] or 0)
        if row["order__order_type"] == Order.TYPE_PURCHASE:
            delta = qty
        else:
            delta = -qty
        daily_deltas[day] = int(daily_deltas.get(day, 0) + delta)

    adjustment_re = re.compile(r"Adjusted quantity for .*: change of ([+-]?\d+)")
    adjustment_rows = (
        Activity.objects.filter(timestamp__date__range=(start_date, end_date))
        .values("timestamp", "message")
        .order_by("timestamp")
    )
    for row in adjustment_rows:
        match = adjustment_re.search(row["message"] or "")
        if not match:
            continue
        delta = int(match.group(1))
        day = row["timestamp"].date()
        daily_deltas[day] = int(daily_deltas.get(day, 0) + delta)

    if not daily_deltas:
        return pd.DataFrame([{"date": end_date, "total_units": current_total_units}])

    cumulative_delta = int(sum(daily_deltas.values()))
    start_total = max(0, current_total_units - cumulative_delta)

    rows: list[dict[str, Any]] = []
    running = start_total
    cursor = start_date
    while cursor <= end_date:
        running = max(0, int(running + daily_deltas.get(cursor, 0)))
        rows.append({"date": cursor, "total_units": running})
        cursor += datetime.timedelta(days=1)

    if rows:
        rows[-1]["total_units"] = current_total_units
    return pd.DataFrame(rows)


def get_daily_inventory_series(days_back: int = 180) -> pd.DataFrame:
    """
    Build a clean daily total inventory unit series: columns date | total_units.
    Latest value is forced to match current system total exactly.
    """
    today = timezone.localdate()
    start_date = today - datetime.timedelta(days=max(int(days_back) - 1, 0))

    has_snapshots = StockHistory.objects.exists()
    if has_snapshots:
        df = _build_from_stock_snapshots(start_date=start_date, end_date=today)
    else:
        df = _reconstruct_from_movements(start_date=start_date, end_date=today)

    if df.empty:
        current_total_units = int(Item.objects.filter(is_active=True).aggregate(total=Sum("quantity"))["total"] or 0)
        df = pd.DataFrame([{"date": today, "total_units": current_total_units}])

    df = df.drop_duplicates(subset=["date"]).sort_values("date").reset_index(drop=True)
    df["date"] = pd.to_datetime(df["date"]).dt.date
    df["total_units"] = pd.to_numeric(df["total_units"], errors="coerce").fillna(0).astype(int).clip(lower=0)

    current_total_units = int(Item.objects.filter(is_active=True).aggregate(total=Sum("quantity"))["total"] or 0)
    df.loc[df.index[-1], "total_units"] = current_total_units
    return df[["date", "total_units"]]


def train_forecast_model(series_df: pd.DataFrame, horizon_days: int = 7) -> ForecastModelBundle:
    """
    Train advanced model (Prophet) with baseline fallback.
    """
    if series_df.empty:
        empty_series = pd.Series(dtype=float)
        return ForecastModelBundle(
            model_name="baseline",
            model=None,
            baseline_name="last_value",
            baseline_series=empty_series,
            used_fallback=True,
            fallback_reason="No historical data",
        )

    y = series_df["total_units"].astype(float).reset_index(drop=True)
    baseline_last = float(y.iloc[-1]) if len(y) else 0.0
    baseline_series = pd.Series([baseline_last] * max(int(horizon_days), 1))

    if len(series_df) < 21:
        return ForecastModelBundle(
            model_name="baseline",
            model=None,
            baseline_name="last_value",
            baseline_series=baseline_series,
            used_fallback=True,
            fallback_reason="Insufficient history for advanced model",
        )

    try:
        from prophet import Prophet

        df = pd.DataFrame(
            {
                "ds": pd.to_datetime(series_df["date"]),
                "y": series_df["total_units"].astype(float),
            }
        )
        model = Prophet(
            weekly_seasonality=True,
            daily_seasonality=False,
            yearly_seasonality=False,
            changepoint_prior_scale=0.08,
            seasonality_prior_scale=8.0,
            interval_width=0.8,
        )
        model.fit(df)
        return ForecastModelBundle(
            model_name="prophet",
            model=model,
            baseline_name="last_value",
            baseline_series=baseline_series,
            used_fallback=False,
            fallback_reason="",
        )
    except Exception as exc:
        return ForecastModelBundle(
            model_name="baseline",
            model=None,
            baseline_name="last_value",
            baseline_series=baseline_series,
            used_fallback=True,
            fallback_reason=f"Advanced model unavailable ({exc.__class__.__name__})",
        )


def _cap_unrealistic_jumps(history_values: list[float], forecast_values: list[float]) -> list[float]:
    if not forecast_values:
        return forecast_values

    hist = np.array(history_values[-60:], dtype=float) if history_values else np.array([0.0], dtype=float)
    hist_deltas = np.abs(np.diff(hist)) if len(hist) >= 2 else np.array([0.0], dtype=float)
    p95_delta = float(np.percentile(hist_deltas, 95)) if len(hist_deltas) else 0.0

    current = float(history_values[-1]) if history_values else 0.0
    max_daily_jump = max(50.0, p95_delta * 2.0, abs(current) * 0.15)

    capped: list[float] = []
    prev = current
    for value in forecast_values:
        raw = max(0.0, float(value))
        upper = prev + max_daily_jump
        lower = max(0.0, prev - max_daily_jump)
        clipped = min(max(raw, lower), upper)
        capped.append(clipped)
        prev = clipped
    return capped


def generate_forecast(
    series_df: pd.DataFrame,
    horizon_days: int = 7,
    chart_history_days: int = 45,
) -> dict[str, Any]:
    """
    Generate next-N-day forecast with confidence bounds and chart-ready arrays.
    """
    horizon_days = max(int(horizon_days), 1)
    model_bundle = train_forecast_model(series_df=series_df, horizon_days=horizon_days)
    chart_history_days = max(int(chart_history_days), 7)
    chart_df = series_df.tail(chart_history_days).copy()
    hist_dates = [d.strftime("%d %b") for d in pd.to_datetime(chart_df["date"]).dt.date.tolist()]
    hist_values = chart_df["total_units"].astype(float).tolist()

    last_date = pd.to_datetime(series_df["date"].iloc[-1]).date() if not series_df.empty else timezone.localdate()
    future_dates = [last_date + datetime.timedelta(days=i) for i in range(1, horizon_days + 1)]

    yhat: list[float]
    yhat_lower: list[float]
    yhat_upper: list[float]

    if model_bundle.model_name == "prophet" and model_bundle.model is not None:
        future_df = pd.DataFrame({"ds": pd.to_datetime(future_dates)})
        pred = model_bundle.model.predict(future_df)
        yhat = [max(0.0, _safe_float(v)) for v in pred["yhat"].tolist()]
        yhat_lower = [max(0.0, _safe_float(v)) for v in pred["yhat_lower"].tolist()]
        yhat_upper = [max(0.0, _safe_float(v)) for v in pred["yhat_upper"].tolist()]
    else:
        yhat = model_bundle.baseline_series.tolist()
        yhat_lower = [max(0.0, val * 0.95) for val in yhat]
        yhat_upper = [max(0.0, val * 1.05) for val in yhat]

    yhat = _cap_unrealistic_jumps(hist_values, yhat)
    yhat_lower = _cap_unrealistic_jumps(hist_values, yhat_lower)
    yhat_upper = _cap_unrealistic_jumps(hist_values, yhat_upper)

    trend_start = float(yhat[0]) if yhat else (hist_values[-1] if hist_values else 0.0)
    trend_end = float(yhat[-1]) if yhat else trend_start
    if trend_start <= 0:
        trend_delta_ratio = 0.0 if trend_end == trend_start else 1.0
    else:
        trend_delta_ratio = (trend_end - trend_start) / trend_start

    if trend_delta_ratio > 0.01:
        trend_badge = "rising"
    elif trend_delta_ratio < -0.01:
        trend_badge = "falling"
    else:
        trend_badge = "stable"

    forecast_change_pct = trend_delta_ratio * 100.0
    has_significant_change = abs(forecast_change_pct) >= 1.0

    horizon_low = float(min(yhat_lower)) if yhat_lower else 0.0
    horizon_high = float(max(yhat_upper)) if yhat_upper else 0.0
    avg_forecast = float(np.mean(yhat)) if yhat else 0.0
    avg_band_width = float(np.mean([max(0.0, hi - lo) for lo, hi in zip(yhat_lower, yhat_upper)])) if yhat else 0.0
    rel_uncertainty_pct = (avg_band_width / max(avg_forecast, 1.0)) * 100.0
    if rel_uncertainty_pct <= 4.0:
        confidence_label = "High"
    elif rel_uncertainty_pct <= 9.0:
        confidence_label = "Medium"
    else:
        confidence_label = "Low"

    future_labels = [d.strftime("%d %b") for d in future_dates]
    chart_labels = hist_dates + future_labels
    chart_hist_values = hist_values + [None] * horizon_days
    chart_forecast_values = [None] * len(hist_values) + [round(v, 2) for v in yhat]
    chart_lower_values = [None] * len(hist_values) + [round(v, 2) for v in yhat_lower]
    chart_upper_values = [None] * len(hist_values) + [round(v, 2) for v in yhat_upper]

    return {
        "model_used": model_bundle.model_name,
        "used_fallback": model_bundle.used_fallback,
        "fallback_reason": model_bundle.fallback_reason,
        "trend_badge": trend_badge,
        "forecast_points": [
            {
                "date": d.isoformat(),
                "yhat": round(float(y), 2),
                "yhat_lower": round(float(lo), 2),
                "yhat_upper": round(float(hi), 2),
            }
            for d, y, lo, hi in zip(future_dates, yhat, yhat_lower, yhat_upper)
        ],
        "next_day_forecast": int(round(yhat[0])) if yhat else 0,
        "latest_forecast": int(round(yhat[-1])) if yhat else 0,
        "forecast_change_pct": round(float(forecast_change_pct), 2),
        "has_significant_change": has_significant_change,
        "expected_range_lower": int(round(horizon_low)),
        "expected_range_upper": int(round(horizon_high)),
        "confidence_label": confidence_label,
        "history_days_used": int(len(series_df)),
        "chart_today_index": max(len(hist_values) - 1, 0),
        "chart_labels": chart_labels,
        "chart_hist_values": chart_hist_values,
        "chart_forecast_values": chart_forecast_values,
        "chart_lower_values": chart_lower_values,
        "chart_upper_values": chart_upper_values,
    }


def evaluate_model(series_df: pd.DataFrame, horizon_days: int = 7) -> dict[str, Any]:
    """
    Backtest advanced model against baseline using MAE/RMSE/MAPE.
    """
    if series_df.empty or len(series_df) < max(14, horizon_days + 7):
        return {
            "can_evaluate": False,
            "reason": "Insufficient data for backtesting",
            "baseline": {},
            "advanced": {},
        }

    values = series_df["total_units"].astype(float).to_numpy()
    split_idx = max(int(math.floor(len(values) * 0.8)), len(values) - max(14, horizon_days))
    split_idx = min(max(split_idx, 7), len(values) - 7)

    train_df = series_df.iloc[:split_idx].copy()
    valid_df = series_df.iloc[split_idx:].copy()
    y_true = valid_df["total_units"].astype(float).to_numpy()

    baseline_value = float(train_df["total_units"].iloc[-1])
    baseline_pred = np.array([baseline_value] * len(valid_df), dtype=float)

    baseline_mae = float(np.mean(np.abs(y_true - baseline_pred)))
    baseline_rmse = float(np.sqrt(np.mean((y_true - baseline_pred) ** 2)))
    baseline_mape = _mape(y_true, baseline_pred)

    advanced_metrics: dict[str, Any] = {"available": False}
    model_bundle = train_forecast_model(train_df, horizon_days=len(valid_df))

    if model_bundle.model_name == "prophet" and model_bundle.model is not None:
        try:
            future_dates = pd.to_datetime(valid_df["date"])
            pred_df = model_bundle.model.predict(pd.DataFrame({"ds": future_dates}))
            adv_pred = np.maximum(pred_df["yhat"].to_numpy(dtype=float), 0.0)
            advanced_metrics = {
                "available": True,
                "model_name": "advanced",
                "mae": float(np.mean(np.abs(y_true - adv_pred))),
                "rmse": float(np.sqrt(np.mean((y_true - adv_pred) ** 2))),
                "mape": _mape(y_true, adv_pred),
            }
        except Exception as exc:
            advanced_metrics = {
                "available": False,
                "reason": f"Advanced model backtest failed ({exc.__class__.__name__})",
            }
    else:
        advanced_metrics = {
            "available": False,
            "reason": model_bundle.fallback_reason or "Fallback model selected",
        }

    return {
        "can_evaluate": True,
        "train_points": int(len(train_df)),
        "validation_points": int(len(valid_df)),
        "baseline": {
            "model_name": "baseline",
            "mae": round(baseline_mae, 4),
            "rmse": round(baseline_rmse, 4),
            "mape": round(baseline_mape, 4),
        },
        "advanced": {
            **advanced_metrics,
            "mae": round(float(advanced_metrics.get("mae", 0.0)), 4) if advanced_metrics.get("available") else None,
            "rmse": round(float(advanced_metrics.get("rmse", 0.0)), 4) if advanced_metrics.get("available") else None,
            "mape": round(float(advanced_metrics.get("mape", 0.0)), 4) if advanced_metrics.get("available") else None,
        },
    }

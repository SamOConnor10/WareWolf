# inventory/ml/forecasting.py
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
import pandas as pd
from django.db.models import Sum
from django.utils import timezone

from inventory.models import Order, Item

@dataclass
class ForecastOutput:
    history: list[dict]          # [{"ds": "2026-02-01", "y": 5}, ...]
    forecast: list[dict]         # [{"ds": "...", "yhat": 4.2, "yhat_lower": 2.0, "yhat_upper": 6.4}, ...]
    metrics: dict                # {"mape": 0.18, "mae": 2.1, "model": "Prophet"}
    recommendation: dict         # {"reorder_qty": 40, "reorder_by": "2026-03-01", "expected_stockout": "2026-02-28"}

def _daily_demand_series(item: Item, days_back: int = 120) -> pd.DataFrame:
    """
    Demand = SALE quantities per day for an item.
    Returns df with columns ds (date), y (demand).
    """
    end = timezone.now().date()
    start = end - timedelta(days=days_back)

    qs = (
        Order.objects.filter(
            item=item,
            order_type=Order.TYPE_SALE,
            order_date__range=(start, end),
        )
        .values("order_date")
        .annotate(y=Sum("quantity"))
        .order_by("order_date")
    )

    # Build continuous daily series (fill missing days with 0 demand)
    if not qs:
        df = pd.DataFrame({"ds": [], "y": []})
        return df

    df = pd.DataFrame([{"ds": r["order_date"], "y": int(r["y"] or 0)} for r in qs])
    df["ds"] = pd.to_datetime(df["ds"])
    df = df.set_index("ds").asfreq("D", fill_value=0).reset_index()
    df["y"] = df["y"].astype(float)
    return df

def prophet_forecast_item(item: Item, horizon_days: int = 30) -> ForecastOutput:
    """
    Prophet forecast + simple backtest metrics + reorder recommendation.
    """
    from prophet import Prophet
    import numpy as np

    df = _daily_demand_series(item, days_back=180)

    # Not enough data -> return empty forecast but still provide recommendation baseline
    if len(df) < 7:
        return ForecastOutput(
            history=df.to_dict("records"),
            forecast=[],
            metrics={"model": "Prophet", "note": "Not enough history (<14 days)"},
            recommendation=_recommend(item, avg_daily_demand=float(df["y"].mean()) if len(df) else 0.0),
        )

    # --- backtest split (last 14 days as test) ---
    split = max(len(df) - 14, 1)
    train, test = df.iloc[:split], df.iloc[split:]

    m = Prophet(
        daily_seasonality=False,
        weekly_seasonality=True,
        yearly_seasonality=False,
    )
    m.fit(train.rename(columns={"ds": "ds", "y": "y"}))

    # predict on test for metrics
    test_future = test[["ds"]]
    test_pred = m.predict(test_future)
    test_pred["yhat"] = test_pred["yhat"].clip(lower=0)
    y_true = test["y"].values
    y_hat = test_pred["yhat"].values

    mae = float(np.mean(np.abs(y_true - y_hat)))
    mape = float(np.mean(np.abs((y_true - y_hat) / np.maximum(y_true, 1))))  # avoid div by 0

    # --- future forecast ---
    future = m.make_future_dataframe(periods=horizon_days, freq="D")
    pred = m.predict(future)

    # Keep only forecast horizon (including today forward)
    pred_tail = pred.tail(horizon_days)

    pred_tail["yhat"] = pred_tail["yhat"].clip(lower=0)
    pred_tail["yhat_lower"] = pred_tail["yhat_lower"].clip(lower=0)
    pred_tail["yhat_upper"] = pred_tail["yhat_upper"].clip(lower=0)

    avg_daily = float(pred_tail["yhat"].mean())
    avg_upper = float(pred_tail["yhat_upper"].mean())
    rec = _recommend(item, avg_daily_demand=avg_daily, avg_daily_upper=avg_upper)

    forecast = [
        {
            "ds": d.strftime("%d/%m/%Y"),
            "yhat": float(y),
            "yhat_lower": float(lo),
            "yhat_upper": float(hi),
        }
        for d, y, lo, hi in zip(
            pred_tail["ds"],
            pred_tail["yhat"],
            pred_tail["yhat_lower"],
            pred_tail["yhat_upper"],
        )
    ]

    avg_daily = float(pred_tail["yhat"].clip(lower=0).mean())
    rec = _recommend(item, avg_daily_demand=avg_daily)

    return ForecastOutput(
        history=[{"ds": r["ds"].strftime("%d/%m/%Y"), "y": float(r["y"])} for r in df.to_dict("records")],
        forecast=forecast,
        metrics={"model": "Prophet", "mae": mae, "mape": mape},
        recommendation=rec,
    )

def _recommend(item: Item, avg_daily_demand: float, avg_daily_upper: float | None = None) -> dict:
    """
    Reorder logic using forecasted daily demand.
    """
    lead_time_days = getattr(item, "lead_time_days", 7)  # we’ll add this field
    safety_stock = item.safety_stock

    # Expected demand during lead time + safety buffer
    review_period_days = 30
    needed = (avg_daily_demand * (lead_time_days + review_period_days)) + float(safety_stock)
    reorder_qty = max(int(round(needed - item.quantity)), 0)

    # Force a sensible reorder if stock is zero / below reorder level
    if item.quantity <= 0:
        # If we’re out, at least order enough to reach reorder level + safety stock
        min_target = max(item.reorder_level, 1) + int(safety_stock)
        reorder_qty = max(reorder_qty, min_target)

    elif item.quantity <= item.reorder_level:
        # If low stock, top up to reorder level + safety stock
        min_target = (item.reorder_level + int(safety_stock)) - item.quantity
        reorder_qty = max(reorder_qty, min_target)

    if avg_daily_demand < 0.03 and item.quantity > 0:
        risk = "Low"

    # Risk scoring using uncertainty (upper bound)
    risk = "Low"
    if avg_daily_upper is None:
        avg_daily_upper = avg_daily_demand

    lead_time_need_upper = (avg_daily_upper * lead_time_days) + float(safety_stock)
    if item.quantity <= 0:
        risk = "High"
    elif item.quantity < lead_time_need_upper:
        risk = "High"
    elif item.quantity < (avg_daily_demand * lead_time_days) + float(safety_stock):
        risk = "Medium"
    

    # Rough stockout estimate (if demand > 0)
    expected_stockout = None
    if avg_daily_demand > 0:
        days_left = int(item.quantity / avg_daily_demand)
        expected_stockout = (timezone.now().date() + timedelta(days=days_left)).strftime("%d/%m/%Y")
    reorder_by = (timezone.now().date() + timedelta(days=max(lead_time_days - 2, 0))).strftime("%d/%m/%Y")

    show_stockout = (avg_daily_demand * lead_time_days) >= 1

    reason = "Forecast-based recommendation"

    if item.quantity <= 0:
        reason = "Out of stock (min reorder to reorder level)"
    elif item.quantity <= item.reorder_level:
        reason = "Below reorder level (min top-up)"
    elif avg_daily_demand == 0:
        reason = "No recent demand (rule-based)"

    return {
        "avg_daily_demand": round(avg_daily_demand, 2),
        "lead_time_days": int(lead_time_days),
        "reorder_qty": int(reorder_qty),
        "reorder_by": reorder_by,
        "expected_stockout": expected_stockout,
        "show_stockout": show_stockout,
        "reason": reason,

        # NEW:
        "risk": risk,
        "lead_time_need_upper": round(float(lead_time_need_upper), 2),
    }

"""Market regime detection helpers."""

from __future__ import annotations

import pandas as pd


def detect_regime(
    ema_fast: float,
    ema_slow: float,
    volatility: float,
    volatility_threshold: float,
    *,
    price: float | None = None,
) -> str:
    """Return a bull, ranging, or bear classification."""
    if price is not None and price > ema_fast > ema_slow and volatility <= volatility_threshold:
        return "bull"
    if price is not None and price < ema_fast < ema_slow:
        return "bear"
    if volatility > volatility_threshold:
        return "bear"
    if ema_fast > ema_slow:
        return "bull"
    return "ranging"


def classify_regime_history(
    prices: pd.Series,
    *,
    ema_fast_period: int = 20,
    ema_slow_period: int = 50,
    volatility_lookback: int = 14,
    volatility_baseline_period: int = 60,
    volatility_threshold_multiplier: float = 1.5,
    confirmation_periods: int = 2,
) -> pd.DataFrame:
    """Classify a price history into baseline and active regimes."""
    if prices.empty:
        return pd.DataFrame(
            columns=[
                "price",
                "ema_fast",
                "ema_slow",
                "volatility",
                "volatility_baseline",
                "volatility_threshold",
                "base_regime",
                "active_regime",
            ]
        )

    price_series = prices.dropna().astype(float)
    ema_fast = price_series.ewm(span=ema_fast_period, adjust=False).mean()
    ema_slow = price_series.ewm(span=ema_slow_period, adjust=False).mean()
    returns = price_series.pct_change()
    volatility = returns.rolling(window=volatility_lookback).std(ddof=0)
    volatility_baseline = returns.rolling(window=volatility_baseline_period).std(ddof=0)
    volatility_threshold = volatility_baseline * volatility_threshold_multiplier

    base_regimes: list[str] = []
    for timestamp in price_series.index:
        if any(
            pd.isna(value)
            for value in (
                ema_fast.loc[timestamp],
                ema_slow.loc[timestamp],
                volatility.loc[timestamp],
                volatility_threshold.loc[timestamp],
            )
        ):
            base_regimes.append("unknown")
            continue
        base_regimes.append(
            detect_regime(
                float(ema_fast.loc[timestamp]),
                float(ema_slow.loc[timestamp]),
                float(volatility.loc[timestamp]),
                float(volatility_threshold.loc[timestamp]),
                price=float(price_series.loc[timestamp]),
            )
        )

    active_regimes: list[str] = []
    last_active = "unknown"
    streak_regime = "unknown"
    streak_count = 0

    for regime in base_regimes:
        if regime == "unknown":
            active_regimes.append(last_active)
            continue

        if regime == streak_regime:
            streak_count += 1
        else:
            streak_regime = regime
            streak_count = 1

        if last_active == "unknown":
            last_active = regime
        elif regime != last_active and streak_count >= max(1, confirmation_periods):
            last_active = regime

        active_regimes.append(last_active)

    return pd.DataFrame(
        {
            "price": price_series,
            "ema_fast": ema_fast,
            "ema_slow": ema_slow,
            "volatility": volatility,
            "volatility_baseline": volatility_baseline,
            "volatility_threshold": volatility_threshold,
            "base_regime": pd.Series(base_regimes, index=price_series.index),
            "active_regime": pd.Series(active_regimes, index=price_series.index),
        }
    )

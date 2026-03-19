"""Mean-reversion signal helpers."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping

import pandas as pd

from .momentum import calculate_rsi


def find_oversold_assets(
    rsi_values: Mapping[str, float],
    threshold: float = 30.0,
) -> list[str]:
    """Return symbols whose RSI is at or below the oversold threshold."""
    return sorted(symbol for symbol, rsi in rsi_values.items() if rsi <= threshold)


@dataclass(frozen=True, slots=True)
class MeanReversionSignal:
    """Current oversold signal state for one asset."""

    strength: float
    price: float
    moving_average: float
    lower_band: float
    rsi: float
    volume_24h: float


def build_mean_reversion_frame(
    prices: pd.Series,
    quote_volumes: pd.Series,
    *,
    rsi_period: int = 14,
    rsi_oversold: float = 30.0,
    bollinger_period: int = 20,
    bollinger_std: float = 2.0,
    volume_window: int = 24,
) -> pd.DataFrame:
    """Return a vectorized indicator frame for the mean-reversion module."""
    price_series = prices.astype(float)
    volume_series = quote_volumes.astype(float)
    moving_average = price_series.rolling(window=bollinger_period).mean()
    rolling_std = price_series.rolling(window=bollinger_period).std(ddof=0)
    lower_band = moving_average - (bollinger_std * rolling_std)
    rsi = calculate_rsi(price_series, period=rsi_period)
    volume_24h = volume_series.rolling(window=volume_window, min_periods=1).sum()
    rsi_signal = ((rsi_oversold - rsi) / rsi_oversold).clip(lower=0.0, upper=1.0)
    bb_signal = (((lower_band - price_series) / price_series) * 20.0).clip(lower=0.0, upper=1.0)
    signal_strength = pd.concat([rsi_signal, bb_signal], axis=1).max(axis=1)

    return pd.DataFrame(
        {
            "price": price_series,
            "moving_average": moving_average,
            "lower_band": lower_band,
            "rsi": rsi,
            "volume_24h": volume_24h,
            "signal_strength": signal_strength,
        }
    )


def evaluate_mean_reversion_signal(
    prices: pd.Series,
    quote_volumes: pd.Series,
    *,
    rsi_period: int = 14,
    rsi_oversold: float = 30.0,
    bollinger_period: int = 20,
    bollinger_std: float = 2.0,
    min_volume_usd: float = 10_000_000.0,
    volume_window: int = 24,
) -> MeanReversionSignal | None:
    """Return the latest mean-reversion signal when RSI or Bollinger triggers."""
    indicator_frame = build_mean_reversion_frame(
        prices,
        quote_volumes,
        rsi_period=rsi_period,
        rsi_oversold=rsi_oversold,
        bollinger_period=bollinger_period,
        bollinger_std=bollinger_std,
        volume_window=volume_window,
    ).dropna(subset=["moving_average", "lower_band", "rsi"])
    if indicator_frame.empty:
        return None

    current = indicator_frame.iloc[-1]
    moving_average = float(current["moving_average"])
    lower_band = float(current["lower_band"])
    current_price = float(current["price"])
    current_rsi = float(current["rsi"])
    current_volume = float(current["volume_24h"])

    if (
        pd.isna(moving_average)
        or pd.isna(lower_band)
        or pd.isna(current_rsi)
        or current_volume < min_volume_usd
    ):
        return None

    strength = float(current["signal_strength"])
    if strength <= 0.0:
        return None

    return MeanReversionSignal(
        strength=strength,
        price=current_price,
        moving_average=moving_average,
        lower_band=lower_band,
        rsi=current_rsi,
        volume_24h=current_volume,
    )

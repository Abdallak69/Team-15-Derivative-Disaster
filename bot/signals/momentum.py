"""Momentum signal helpers."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping, Sequence

import pandas as pd


def calculate_momentum_scores(
    price_history: Mapping[str, Sequence[float]],
) -> dict[str, float]:
    """Return simple first-to-last return scores ranked highest first."""
    scores: dict[str, float] = {}
    for symbol, prices in price_history.items():
        if len(prices) < 2 or prices[0] == 0:
            continue
        scores[symbol] = (prices[-1] / prices[0]) - 1.0
    return dict(sorted(scores.items(), key=lambda item: item[1], reverse=True))


def calculate_rsi(prices: pd.Series, period: int = 14) -> pd.Series:
    """Return an exponentially smoothed RSI series."""
    delta = prices.astype(float).diff()
    gains = delta.clip(lower=0.0)
    losses = (-delta).clip(lower=0.0)
    average_gain = gains.ewm(alpha=1 / period, adjust=False, min_periods=period).mean()
    average_loss = losses.ewm(alpha=1 / period, adjust=False, min_periods=period).mean()
    average_loss_safe = average_loss.mask(average_loss == 0.0)
    rs = average_gain / average_loss_safe
    rsi = 100.0 - (100.0 / (1.0 + rs))
    rsi = rsi.mask((average_loss == 0.0) & (average_gain > 0.0), 100.0)
    rsi = rsi.mask((average_gain == 0.0) & (average_loss > 0.0), 0.0)
    rsi = rsi.mask((average_gain == 0.0) & (average_loss == 0.0), 50.0)
    return rsi.astype(float)


@dataclass(frozen=True, slots=True)
class MomentumSignal:
    """Single-asset momentum ranking output."""

    symbol: str
    composite_score: float
    normalized_score: float
    price: float
    ema: float
    rsi: float
    quote_volume: float


def rank_assets_by_momentum(
    closes: pd.DataFrame,
    quote_volumes: pd.DataFrame,
    *,
    lookback_periods: Sequence[int] = (3, 5, 7),
    rsi_period: int = 14,
    rsi_threshold: float = 45.0,
    ema_period: int = 20,
    min_volume_usd: float = 10_000_000.0,
    top_n_assets: int = 8,
) -> list[MomentumSignal]:
    """Rank the latest cross-section using the documented momentum filters."""
    if closes.empty:
        return []

    macd_slow = 26
    macd_signal_period = 9
    required_history = max(
        max(lookback_periods, default=1), rsi_period, ema_period,
        macd_slow + macd_signal_period,
    ) + 1
    raw_candidates: list[dict[str, float | str]] = []

    for symbol in closes.columns:
        price_series = closes[symbol].dropna()
        if len(price_series) < required_history:
            continue

        current_price = float(price_series.iloc[-1])
        current_ema = float(price_series.ewm(span=ema_period, adjust=False).mean().iloc[-1])
        current_rsi = float(calculate_rsi(price_series, period=rsi_period).iloc[-1])

        macd_line = (
            price_series.ewm(span=12, adjust=False).mean()
            - price_series.ewm(span=macd_slow, adjust=False).mean()
        )
        macd_signal = macd_line.ewm(span=macd_signal_period, adjust=False).mean()
        macd_histogram = float((macd_line - macd_signal).iloc[-1])

        volume_series = (
            quote_volumes[symbol].dropna()
            if symbol in quote_volumes.columns
            else pd.Series(dtype=float)
        )
        current_volume = float(volume_series.iloc[-1]) if not volume_series.empty else 0.0

        if (
            pd.isna(current_rsi)
            or current_rsi < rsi_threshold
            or current_price <= current_ema
            or current_volume < min_volume_usd
            or macd_histogram <= 0
        ):
            continue

        composite_score = sum(
            (current_price / float(price_series.iloc[-(lookback + 1)])) - 1.0
            for lookback in lookback_periods
        ) / len(lookback_periods)
        raw_candidates.append(
            {
                "symbol": symbol,
                "composite_score": composite_score,
                "price": current_price,
                "ema": current_ema,
                "rsi": current_rsi,
                "quote_volume": current_volume,
            }
        )

    if not raw_candidates:
        return []

    min_score = min(float(candidate["composite_score"]) for candidate in raw_candidates)
    max_score = max(float(candidate["composite_score"]) for candidate in raw_candidates)
    score_span = max_score - min_score
    normalized_candidates = [
        MomentumSignal(
            symbol=str(candidate["symbol"]),
            composite_score=float(candidate["composite_score"]),
            normalized_score=(
                1.0
                if score_span == 0.0
                else (float(candidate["composite_score"]) - min_score) / score_span
            ),
            price=float(candidate["price"]),
            ema=float(candidate["ema"]),
            rsi=float(candidate["rsi"]),
            quote_volume=float(candidate["quote_volume"]),
        )
        for candidate in sorted(
            raw_candidates,
            key=lambda item: float(item["composite_score"]),
            reverse=True,
        )[:top_n_assets]
    ]
    return normalized_candidates

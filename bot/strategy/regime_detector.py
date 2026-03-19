"""Market regime detection helpers."""

from __future__ import annotations


def detect_regime(
    ema_fast: float,
    ema_slow: float,
    volatility: float,
    volatility_threshold: float,
) -> str:
    """Return a baseline bull, ranging, or bear classification."""
    if volatility >= volatility_threshold and ema_fast < ema_slow:
        return "bear"
    if ema_fast > ema_slow:
        return "bull"
    return "ranging"


"""Mean-reversion signal helpers."""

from __future__ import annotations

from typing import Mapping


def find_oversold_assets(
    rsi_values: Mapping[str, float],
    threshold: float = 30.0,
) -> list[str]:
    """Return symbols whose RSI is at or below the oversold threshold."""
    return sorted(symbol for symbol, rsi in rsi_values.items() if rsi <= threshold)


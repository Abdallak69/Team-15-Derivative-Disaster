"""Risk management helpers."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping


def enforce_position_limit(
    weights: Mapping[str, float],
    max_position_pct: float,
) -> dict[str, float]:
    """Clip individual weights to the configured position limit."""
    return {
        symbol: min(max(weight, 0.0), max_position_pct)
        for symbol, weight in weights.items()
        if weight > 0
    }


@dataclass(slots=True)
class RiskManager:
    """Baseline position limit manager."""

    max_position_pct: float = 0.10

    def apply_position_limits(self, weights: Mapping[str, float]) -> dict[str, float]:
        """Enforce the configured maximum allocation per symbol."""
        return enforce_position_limit(weights, self.max_position_pct)


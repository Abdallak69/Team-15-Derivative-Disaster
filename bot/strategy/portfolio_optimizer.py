"""Portfolio sizing helpers."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping


def normalize_weights(
    weights: Mapping[str, float],
    cash_floor: float = 0.0,
) -> dict[str, float]:
    """Scale positive weights to respect the configured cash floor."""
    positive_weights = {symbol: max(weight, 0.0) for symbol, weight in weights.items() if weight > 0}
    total_weight = sum(positive_weights.values())
    if total_weight <= 0 or cash_floor >= 1.0:
        return {}

    investable_fraction = 1.0 - max(cash_floor, 0.0)
    return {
        symbol: (weight / total_weight) * investable_fraction
        for symbol, weight in positive_weights.items()
    }


@dataclass(slots=True)
class PortfolioOptimizer:
    """Baseline optimizer that only normalizes target weights."""

    cash_floor: float = 0.0

    def optimize(self, weights: Mapping[str, float]) -> dict[str, float]:
        """Return normalized weights with the configured cash floor."""
        return normalize_weights(weights, cash_floor=self.cash_floor)


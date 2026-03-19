"""Order execution helpers."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping


@dataclass(frozen=True, slots=True)
class OrderProposal:
    """Baseline order representation for rebalance planning."""

    side: str
    symbol: str
    target_weight: float


def generate_rebalance_orders(
    current_weights: Mapping[str, float],
    target_weights: Mapping[str, float],
    min_drift: float = 0.0,
) -> list[OrderProposal]:
    """Generate buy and sell proposals for materially different weights."""
    orders: list[OrderProposal] = []
    for symbol, target_weight in target_weights.items():
        current_weight = current_weights.get(symbol, 0.0)
        drift = target_weight - current_weight
        if abs(drift) <= min_drift:
            continue
        orders.append(
            OrderProposal(
                side="BUY" if drift > 0 else "SELL",
                symbol=symbol,
                target_weight=target_weight,
            )
        )
    return orders


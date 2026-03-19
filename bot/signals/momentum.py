"""Momentum signal helpers."""

from __future__ import annotations

from typing import Mapping, Sequence


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


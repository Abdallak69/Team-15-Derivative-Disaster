"""Signal combination helpers."""

from __future__ import annotations

from typing import Mapping, Sequence


def combine_weight_maps(weight_maps: Sequence[Mapping[str, float]]) -> dict[str, float]:
    """Aggregate multiple weight maps by summing symbol weights."""
    combined: dict[str, float] = {}
    for weight_map in weight_maps:
        for symbol, weight in weight_map.items():
            combined[symbol] = combined.get(symbol, 0.0) + weight
    return combined


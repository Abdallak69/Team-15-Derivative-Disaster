"""Pairs rotation helpers."""

from __future__ import annotations

from typing import Mapping


def rank_pairs_by_spread(spreads: Mapping[str, float]) -> list[str]:
    """Return pairs ordered from the most negative spread upward."""
    return [pair for pair, _ in sorted(spreads.items(), key=lambda item: item[1])]


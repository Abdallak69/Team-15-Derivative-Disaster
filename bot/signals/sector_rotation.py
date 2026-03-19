"""Sector rotation helpers."""

from __future__ import annotations


def classify_btc_dominance(
    current_value: float,
    previous_value: float,
    min_change: float = 0.5,
) -> str:
    """Classify the current market rotation from BTC dominance changes."""
    delta = current_value - previous_value
    if delta >= min_change:
        return "bitcoin_led"
    if delta <= -min_change:
        return "altcoin_rotation"
    return "neutral"


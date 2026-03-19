"""Sector rotation helpers — BTC dominance-driven sector allocation."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping, Sequence


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


@dataclass(frozen=True, slots=True)
class SectorAllocation:
    """Target allocation weights for each sector based on BTC dominance regime."""

    btc_weight: float
    eth_weight: float
    large_alt_weight: float
    small_alt_weight: float
    rotation_regime: str


# Sector definitions: symbol prefixes that map to each bucket
_BTC_SYMBOLS = frozenset({"BTCUSDT", "BTCUSD"})
_ETH_SYMBOLS = frozenset({"ETHUSDT", "ETHUSD"})
_LARGE_ALT_PREFIXES = ("SOL", "BNB", "XRP", "ADA", "AVAX", "DOT", "MATIC", "LINK", "DOGE")


def _classify_symbol(symbol: str) -> str:
    """Classify a symbol into btc, eth, large_alt, or small_alt."""
    upper = symbol.upper()
    if upper in _BTC_SYMBOLS:
        return "btc"
    if upper in _ETH_SYMBOLS:
        return "eth"
    for prefix in _LARGE_ALT_PREFIXES:
        if upper.startswith(prefix):
            return "large_alt"
    return "small_alt"


def compute_sector_allocation(
    btc_dominance: float,
    previous_dominance: float,
    *,
    min_change: float = 0.5,
) -> SectorAllocation:
    """Compute target sector weights based on BTC dominance regime.

    - bitcoin_led (dominance rising): heavy BTC + ETH, light alts
    - altcoin_rotation (dominance falling): light BTC, heavy alts
    - neutral: balanced allocation
    """
    regime = classify_btc_dominance(btc_dominance, previous_dominance, min_change)

    if regime == "bitcoin_led":
        return SectorAllocation(
            btc_weight=0.40,
            eth_weight=0.25,
            large_alt_weight=0.25,
            small_alt_weight=0.10,
            rotation_regime=regime,
        )
    elif regime == "altcoin_rotation":
        return SectorAllocation(
            btc_weight=0.15,
            eth_weight=0.20,
            large_alt_weight=0.40,
            small_alt_weight=0.25,
            rotation_regime=regime,
        )
    else:  # neutral
        return SectorAllocation(
            btc_weight=0.30,
            eth_weight=0.25,
            large_alt_weight=0.30,
            small_alt_weight=0.15,
            rotation_regime=regime,
        )


def sector_rotation_weights(
    universe: Sequence[str],
    btc_dominance: float,
    previous_dominance: float,
    *,
    min_change: float = 0.5,
) -> dict[str, float]:
    """Produce per-asset weight suggestions based on sector rotation.

    Distributes the sector-level weight equally among assets in each bucket.
    """
    allocation = compute_sector_allocation(
        btc_dominance, previous_dominance, min_change=min_change
    )

    buckets: dict[str, list[str]] = {"btc": [], "eth": [], "large_alt": [], "small_alt": []}
    for symbol in universe:
        bucket = _classify_symbol(symbol)
        buckets[bucket].append(symbol)

    weight_map: dict[str, float] = {
        "btc": allocation.btc_weight,
        "eth": allocation.eth_weight,
        "large_alt": allocation.large_alt_weight,
        "small_alt": allocation.small_alt_weight,
    }

    weights: dict[str, float] = {}
    for bucket, symbols in buckets.items():
        if not symbols:
            continue
        per_asset = weight_map[bucket] / len(symbols)
        for symbol in symbols:
            weights[symbol] = per_asset

    return weights


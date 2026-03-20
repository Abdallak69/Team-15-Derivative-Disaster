"""Signal combination helpers — regime-dependent ensemble weighting."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping, Sequence


def combine_weight_maps(weight_maps: Sequence[Mapping[str, float]]) -> dict[str, float]:
    """Aggregate multiple weight maps by summing symbol weights."""
    combined: dict[str, float] = {}
    for weight_map in weight_maps:
        for symbol, weight in weight_map.items():
            combined[symbol] = combined.get(symbol, 0.0) + weight
    return combined


# Architecture-documented regime weights (Doc 02 Section 3.3):
#   Sentiment is applied as a post-hoc scalar multiplier (0.5x-1.5x) on all
#   combined weights — it does not produce its own {symbol: weight} map.
#   The "sentiment" budget from the original doc is redistributed to the
#   active signal modules so the matrix sums correctly.
#
# BULL:   Momentum 60%, Sector 25%, MeanRev 15%            (sentiment as multiplier)
# RANGE:  MeanRev 40%, Momentum 30%, Pairs 15%, Sector 15% (sentiment as multiplier)
# BEAR:   MeanRev 30%, Pairs 10%, Sector 10%  + 50% cash   (sentiment as multiplier)

_REGIME_WEIGHTS: dict[str, dict[str, float]] = {
    "bull": {
        "momentum": 0.60,
        "sector_rotation": 0.25,
        "mean_reversion": 0.15,
    },
    "ranging": {
        "mean_reversion": 0.40,
        "momentum": 0.30,
        "pairs_rotation": 0.15,
        "sector_rotation": 0.15,
    },
    "bear": {
        "mean_reversion": 0.30,
        "pairs_rotation": 0.10,
        "sector_rotation": 0.10,
        # remaining 50% is held as cash (not allocated to any signal)
    },
}


@dataclass(frozen=True, slots=True)
class EnsembleResult:
    """Output of the ensemble combination step."""

    regime: str
    target_weights: dict[str, float]
    signal_contributions: dict[str, dict[str, float]]
    cash_allocation: float


def ensemble_combine(
    regime: str,
    *,
    momentum_weights: Mapping[str, float] | None = None,
    mean_reversion_weights: Mapping[str, float] | None = None,
    sector_rotation_weights: Mapping[str, float] | None = None,
    pairs_rotation_weights: Mapping[str, float] | None = None,
    sentiment_multiplier: float = 1.0,
) -> EnsembleResult:
    """Combine signal weight maps with regime-dependent blending.

    Each signal module produces a {symbol: raw_weight} map. This function
    scales each map by the regime-specific sub-strategy weight and sums them.

    The sentiment_multiplier is applied as a post-hoc scaling factor
    (e.g., F&G < 25 → 1.30, F&G > 75 → 0.70).
    """
    regime_key = regime.lower() if regime.lower() in _REGIME_WEIGHTS else "ranging"
    strategy_weights = _REGIME_WEIGHTS[regime_key]

    signal_maps: dict[str, Mapping[str, float]] = {}
    if momentum_weights:
        signal_maps["momentum"] = momentum_weights
    if mean_reversion_weights:
        signal_maps["mean_reversion"] = mean_reversion_weights
    if sector_rotation_weights:
        signal_maps["sector_rotation"] = sector_rotation_weights
    if pairs_rotation_weights:
        signal_maps["pairs_rotation"] = pairs_rotation_weights

    combined: dict[str, float] = {}
    contributions: dict[str, dict[str, float]] = {}

    for signal_name, weight_map in signal_maps.items():
        blend_factor = strategy_weights.get(signal_name, 0.0)
        if blend_factor <= 0.0:
            continue
        signal_contribution: dict[str, float] = {}
        for symbol, raw_weight in weight_map.items():
            contribution = raw_weight * blend_factor
            signal_contribution[symbol] = contribution
            combined[symbol] = combined.get(symbol, 0.0) + contribution
        contributions[signal_name] = signal_contribution

    # Apply sentiment overlay as a multiplier on all positions
    sentiment_clamped = max(0.5, min(1.5, sentiment_multiplier))
    if sentiment_clamped != 1.0:
        combined = {s: w * sentiment_clamped for s, w in combined.items()}

    # Compute how much is allocated to cash by the regime
    allocated_signal_weight = sum(strategy_weights.values())
    cash_allocation = max(0.0, 1.0 - allocated_signal_weight)

    return EnsembleResult(
        regime=regime_key,
        target_weights=combined,
        signal_contributions=contributions,
        cash_allocation=cash_allocation,
    )


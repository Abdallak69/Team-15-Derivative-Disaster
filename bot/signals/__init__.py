"""Signal generation modules."""

from .mean_reversion import find_oversold_assets
from .momentum import calculate_momentum_scores
from .pairs_rotation import rank_pairs_by_spread
from .sector_rotation import classify_btc_dominance

__all__ = [
    "calculate_momentum_scores",
    "classify_btc_dominance",
    "find_oversold_assets",
    "rank_pairs_by_spread",
]


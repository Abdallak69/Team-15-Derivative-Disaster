"""Signal generation modules."""

from .mean_reversion import MeanReversionSignal
from .mean_reversion import build_mean_reversion_frame
from .mean_reversion import evaluate_mean_reversion_signal
from .mean_reversion import find_oversold_assets
from .momentum import MomentumSignal
from .momentum import calculate_rsi
from .momentum import calculate_momentum_scores
from .momentum import rank_assets_by_momentum
from .pairs_rotation import PairSignal
from .pairs_rotation import find_cointegrated_pairs
from .pairs_rotation import pairs_rotation_weights
from .pairs_rotation import rank_pairs_by_spread
from .sector_rotation import SectorAllocation
from .sector_rotation import classify_btc_dominance
from .sector_rotation import compute_sector_allocation
from .sector_rotation import sector_rotation_weights

__all__ = [
    "MeanReversionSignal",
    "MomentumSignal",
    "PairSignal",
    "SectorAllocation",
    "build_mean_reversion_frame",
    "calculate_momentum_scores",
    "calculate_rsi",
    "classify_btc_dominance",
    "compute_sector_allocation",
    "evaluate_mean_reversion_signal",
    "find_cointegrated_pairs",
    "find_oversold_assets",
    "pairs_rotation_weights",
    "rank_pairs_by_spread",
    "rank_assets_by_momentum",
    "sector_rotation_weights",
]

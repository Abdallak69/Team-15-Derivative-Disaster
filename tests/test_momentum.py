"""Tests for the baseline momentum helper."""

from __future__ import annotations

import unittest

import pandas as pd

from bot.signals.momentum import calculate_momentum_scores
from bot.signals.momentum import rank_assets_by_momentum


class MomentumTests(unittest.TestCase):
    def test_calculate_momentum_scores_orders_highest_return_first(self) -> None:
        scores = calculate_momentum_scores(
            {
                "ETHUSD": [100.0, 105.0],
                "BTCUSD": [100.0, 110.0],
            }
        )

        self.assertEqual(list(scores.keys()), ["BTCUSD", "ETHUSD"])
        self.assertAlmostEqual(scores["BTCUSD"], 0.10)

    def test_rank_assets_by_momentum_applies_filters_and_orders_scores(self) -> None:
        closes = pd.DataFrame(
            {
                "BTCUSDT": [100, 102, 104, 106, 108, 110, 112, 114, 116, 118, 120, 122, 124, 126, 128],
                "ETHUSDT": [100, 101, 102, 103, 104, 105, 106, 107, 108, 109, 110, 111, 112, 113, 114],
                "SOLUSDT": [120, 118, 116, 114, 112, 110, 108, 106, 104, 102, 100, 98, 96, 94, 92],
            }
        )
        volumes = pd.DataFrame(
            {
                "BTCUSDT": [20_000_000.0] * len(closes),
                "ETHUSDT": [9_000_000.0] * len(closes),
                "SOLUSDT": [20_000_000.0] * len(closes),
            }
        )

        signals = rank_assets_by_momentum(
            closes,
            volumes,
            lookback_periods=(3, 5, 7),
            rsi_threshold=45.0,
            ema_period=5,
            min_volume_usd=10_000_000.0,
            top_n_assets=3,
        )

        self.assertEqual([signal.symbol for signal in signals], ["BTCUSDT"])
        self.assertGreater(signals[0].normalized_score, 0.0)

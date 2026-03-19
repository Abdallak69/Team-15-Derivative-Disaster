"""Tests for the baseline momentum helper."""

from __future__ import annotations

import unittest

from bot.signals.momentum import calculate_momentum_scores


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


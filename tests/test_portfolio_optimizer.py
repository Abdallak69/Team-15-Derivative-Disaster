"""Tests for the baseline portfolio optimizer."""

from __future__ import annotations

import unittest

from bot.strategy.portfolio_optimizer import normalize_weights


class PortfolioOptimizerTests(unittest.TestCase):
    def test_normalize_weights_respects_cash_floor(self) -> None:
        normalized = normalize_weights({"BTCUSD": 2.0, "ETHUSD": 1.0}, cash_floor=0.20)
        self.assertAlmostEqual(sum(normalized.values()), 0.80)
        self.assertGreater(normalized["BTCUSD"], normalized["ETHUSD"])


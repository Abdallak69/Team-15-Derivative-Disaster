"""Tests for the baseline mean-reversion helper."""

from __future__ import annotations

import unittest

from bot.signals.mean_reversion import find_oversold_assets


class MeanReversionTests(unittest.TestCase):
    def test_find_oversold_assets_returns_threshold_matches(self) -> None:
        oversold = find_oversold_assets({"BTCUSD": 45.0, "ETHUSD": 25.0, "SOLUSD": 30.0})
        self.assertEqual(oversold, ["ETHUSD", "SOLUSD"])


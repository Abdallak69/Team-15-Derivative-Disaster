"""Tests for the baseline mean-reversion helper."""

from __future__ import annotations

import unittest

import pandas as pd

from bot.signals.mean_reversion import evaluate_mean_reversion_signal
from bot.signals.mean_reversion import find_oversold_assets


class MeanReversionTests(unittest.TestCase):
    def test_find_oversold_assets_returns_threshold_matches(self) -> None:
        oversold = find_oversold_assets({"BTCUSD": 45.0, "ETHUSD": 25.0, "SOLUSD": 30.0})
        self.assertEqual(oversold, ["ETHUSD", "SOLUSD"])

    def test_evaluate_mean_reversion_signal_returns_signal_for_oversold_series(self) -> None:
        prices = pd.Series(
            [100.0] * 20 + [95.0, 93.0, 92.0, 91.0, 90.0]
        )
        volumes = pd.Series([1_000_000.0] * len(prices))

        signal = evaluate_mean_reversion_signal(
            prices,
            volumes,
            min_volume_usd=10_000_000.0,
        )

        self.assertIsNotNone(signal)
        assert signal is not None
        self.assertGreater(signal.strength, 0.0)
        self.assertLess(signal.rsi, 30.0)

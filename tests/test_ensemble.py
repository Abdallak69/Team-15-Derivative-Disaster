"""Tests for ensemble signal combination."""

from __future__ import annotations

import unittest

from bot.strategy.ensemble import (
    EnsembleResult,
    combine_weight_maps,
    ensemble_combine,
)


class CombineWeightMapsTests(unittest.TestCase):
    def test_sums_overlapping_symbols(self) -> None:
        result = combine_weight_maps([{"A": 0.5, "B": 0.3}, {"A": 0.2, "C": 0.1}])
        self.assertAlmostEqual(result["A"], 0.7)
        self.assertAlmostEqual(result["B"], 0.3)
        self.assertAlmostEqual(result["C"], 0.1)


class EnsembleCombineTests(unittest.TestCase):
    def test_bull_regime_weights_momentum_highest(self) -> None:
        result = ensemble_combine(
            "bull",
            momentum_weights={"BTCUSD": 1.0},
            mean_reversion_weights={"ETHUSD": 1.0},
        )
        self.assertIsInstance(result, EnsembleResult)
        self.assertEqual(result.regime, "bull")
        self.assertGreater(result.target_weights.get("BTCUSD", 0), result.target_weights.get("ETHUSD", 0))

    def test_bear_regime_excludes_momentum(self) -> None:
        result = ensemble_combine(
            "bear",
            momentum_weights={"BTCUSD": 1.0},
            mean_reversion_weights={"ETHUSD": 1.0},
        )
        self.assertAlmostEqual(result.target_weights.get("BTCUSD", 0), 0.0)
        self.assertGreater(result.target_weights.get("ETHUSD", 0), 0.0)

    def test_bear_regime_allocates_50pct_cash(self) -> None:
        result = ensemble_combine("bear")
        self.assertAlmostEqual(result.cash_allocation, 0.50)

    def test_sentiment_multiplier_scales_weights(self) -> None:
        base = ensemble_combine("bull", momentum_weights={"BTCUSD": 1.0}, sentiment_multiplier=1.0)
        scaled = ensemble_combine("bull", momentum_weights={"BTCUSD": 1.0}, sentiment_multiplier=1.3)
        self.assertGreater(
            scaled.target_weights.get("BTCUSD", 0),
            base.target_weights.get("BTCUSD", 0),
        )

    def test_unknown_regime_falls_back_to_ranging(self) -> None:
        result = ensemble_combine("unknown_regime", momentum_weights={"A": 1.0})
        self.assertEqual(result.regime, "ranging")

    def test_empty_signals_returns_empty_weights(self) -> None:
        result = ensemble_combine("bull")
        self.assertEqual(result.target_weights, {})

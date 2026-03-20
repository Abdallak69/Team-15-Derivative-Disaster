"""Tests for cointegration-based pairs rotation."""

from __future__ import annotations

import unittest

import numpy as np
import pandas as pd

from bot.signals.pairs_rotation import (
    PairSignal,
    _adf_test_pvalue,
    _compute_hedge_ratio,
    _estimate_half_life,
    find_cointegrated_pairs,
    pairs_rotation_weights,
)


class HedgeRatioTests(unittest.TestCase):
    def test_hedge_ratio_for_correlated_series(self) -> None:
        np.random.seed(42)
        b = pd.Series(np.cumsum(np.random.randn(100)))
        a = 2.0 * b + np.random.randn(100) * 0.1
        ratio = _compute_hedge_ratio(pd.Series(a), pd.Series(b))
        self.assertAlmostEqual(ratio, 2.0, places=0)

    def test_hedge_ratio_returns_zero_for_flat_series(self) -> None:
        flat = pd.Series([1.0] * 50)
        other = pd.Series(np.random.randn(50))
        ratio = _compute_hedge_ratio(other, flat)
        self.assertAlmostEqual(ratio, 0.0)


class AdfTests(unittest.TestCase):
    def test_stationary_series_has_low_pvalue(self) -> None:
        np.random.seed(0)
        stationary = pd.Series(np.random.randn(200))
        p = _adf_test_pvalue(stationary)
        self.assertLess(p, 0.10)

    def test_random_walk_has_high_pvalue(self) -> None:
        np.random.seed(1)
        walk = pd.Series(np.cumsum(np.random.randn(200)))
        p = _adf_test_pvalue(walk)
        self.assertGreater(p, 0.10)

    def test_short_series_returns_one(self) -> None:
        short = pd.Series([1.0, 2.0])
        self.assertAlmostEqual(_adf_test_pvalue(short), 1.0)


class HalfLifeTests(unittest.TestCase):
    def test_mean_reverting_spread_has_finite_half_life(self) -> None:
        np.random.seed(10)
        spread = pd.Series(np.random.randn(200))
        hl = _estimate_half_life(spread)
        self.assertGreater(hl, 0)
        self.assertLess(hl, 100)


class FindCointegratedPairsTests(unittest.TestCase):
    def test_returns_empty_for_insufficient_data(self) -> None:
        df = pd.DataFrame({"A": [1.0, 2.0], "B": [3.0, 4.0]})
        result = find_cointegrated_pairs(df, lookback=60)
        self.assertEqual(result, [])


class PairsWeightsTests(unittest.TestCase):
    def test_assigns_positive_and_negative_weights(self) -> None:
        signal = PairSignal(
            asset_a="X", asset_b="Y",
            z_score=-2.5, spread=-1.0,
            half_life=5.0, hedge_ratio=1.0, adf_pvalue=0.01,
        )
        weights = pairs_rotation_weights([signal], z_entry=2.0)
        self.assertGreater(weights.get("X", 0), 0)
        self.assertLess(weights.get("Y", 0), 0)

    def test_max_pairs_limit(self) -> None:
        signals = [
            PairSignal(f"A{i}", f"B{i}", z_score=-3.0, spread=-1.0,
                       half_life=5.0, hedge_ratio=1.0, adf_pvalue=0.01)
            for i in range(10)
        ]
        weights = pairs_rotation_weights(signals, max_pairs=2)
        unique_symbols = {s for s in weights if weights[s] != 0}
        self.assertLessEqual(len(unique_symbols), 4)

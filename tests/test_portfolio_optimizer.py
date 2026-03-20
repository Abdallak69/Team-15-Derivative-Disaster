"""Tests for the portfolio optimizer."""

from __future__ import annotations

import unittest

from bot.strategy.portfolio_optimizer import (
    PortfolioOptimizer,
    normalize_weights,
    optimize_weights,
)


class PortfolioOptimizerTests(unittest.TestCase):
    def test_normalize_weights_respects_cash_floor(self) -> None:
        normalized = normalize_weights({"BTCUSD": 2.0, "ETHUSD": 1.0}, cash_floor=0.20)
        self.assertAlmostEqual(sum(normalized.values()), 0.80)
        self.assertGreater(normalized["BTCUSD"], normalized["ETHUSD"])

    def test_optimize_caps_at_max_position(self) -> None:
        weights = {"BTCUSD": 1.0}
        result = optimize_weights(weights, regime="bull", max_position_pct=0.10)
        self.assertLessEqual(result.get("BTCUSD", 0.0), 0.10)

    def test_inverse_vol_favors_lower_volatility(self) -> None:
        weights = {"BTCUSD": 0.3, "ETHUSD": 0.3, "SOLUSD": 0.3, "XRPUSD": 0.3}
        vols = {"BTCUSD": 0.01, "ETHUSD": 0.10, "SOLUSD": 0.10, "XRPUSD": 0.10}
        result = optimize_weights(weights, volatilities=vols, regime="bull", max_position_pct=0.40)
        self.assertGreater(result.get("BTCUSD", 0), result.get("ETHUSD", 0))

    def test_sector_cap_limits_concentration(self) -> None:
        weights = {
            "SOLUSD": 0.5,
            "BNBUSD": 0.5,
            "XRPUSD": 0.5,
            "ADAUSD": 0.5,
            "AVAXUSD": 0.5,
        }
        result = optimize_weights(weights, regime="bull", max_sector_pct=0.30)
        large_alt_total = sum(result.get(s, 0) for s in weights)
        self.assertLessEqual(large_alt_total, 0.80 + 0.01)

    def test_cash_floor_varies_by_regime(self) -> None:
        weights = {f"SYM{i}": 0.1 for i in range(12)}
        bull = optimize_weights(weights, regime="bull", max_position_pct=0.20, max_sector_pct=1.0)
        bear = optimize_weights(weights, regime="bear", max_position_pct=0.20, max_sector_pct=1.0)
        self.assertGreater(sum(bull.values()), sum(bear.values()))

    def test_optimizer_class_delegates_correctly(self) -> None:
        opt = PortfolioOptimizer()
        result = opt.optimize({"BTCUSD": 1.0, "ETHUSD": 0.5}, regime="bull")
        self.assertIn("BTCUSD", result)
        self.assertIn("ETHUSD", result)
        total = sum(result.values())
        self.assertLessEqual(total, 0.80 + 0.01)

"""Tests for the baseline risk manager."""

from __future__ import annotations

import unittest

from bot.risk.risk_manager import enforce_position_limit


class RiskManagerTests(unittest.TestCase):
    def test_enforce_position_limit_caps_allocations(self) -> None:
        capped = enforce_position_limit({"BTCUSD": 0.25, "ETHUSD": 0.05}, max_position_pct=0.10)
        self.assertEqual(capped["BTCUSD"], 0.10)
        self.assertEqual(capped["ETHUSD"], 0.05)


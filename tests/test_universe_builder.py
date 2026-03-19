"""Tests for exchange-info universe parsing."""

from __future__ import annotations

import unittest

from bot.data.universe_builder import UniverseBuilder


class UniverseBuilderTests(unittest.TestCase):
    def test_build_from_exchange_info_returns_only_trading_pairs(self) -> None:
        builder = UniverseBuilder()
        universe = builder.build_from_exchange_info(
            {
                "Data": [
                    {"Pair": "BTCUSD", "Status": "TRADING", "PricePrecision": 2},
                    {"Pair": "ETHUSD", "Status": "HALTED", "PricePrecision": 2},
                    {"Pair": "SOLUSD", "Status": "TRADING", "PricePrecision": 3},
                ]
            }
        )

        self.assertEqual(universe, ["BTCUSD", "SOLUSD"])

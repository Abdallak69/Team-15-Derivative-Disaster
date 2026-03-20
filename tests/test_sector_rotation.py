"""Tests for BTC dominance-driven sector rotation."""

from __future__ import annotations

import unittest

from bot.signals.sector_rotation import (
    classify_btc_dominance,
    compute_sector_allocation,
    sector_rotation_weights,
)


class ClassifyDominanceTests(unittest.TestCase):
    def test_rising_dominance_is_bitcoin_led(self) -> None:
        self.assertEqual(classify_btc_dominance(60.0, 59.0), "bitcoin_led")

    def test_falling_dominance_is_altcoin_rotation(self) -> None:
        self.assertEqual(classify_btc_dominance(56.0, 57.0), "altcoin_rotation")

    def test_stable_dominance_is_neutral(self) -> None:
        self.assertEqual(classify_btc_dominance(58.0, 58.2), "neutral")


class SectorAllocationTests(unittest.TestCase):
    def test_bitcoin_led_weights_sum_to_one(self) -> None:
        alloc = compute_sector_allocation(60.0, 59.0)
        total = alloc.btc_weight + alloc.eth_weight + alloc.large_alt_weight + alloc.small_alt_weight
        self.assertAlmostEqual(total, 1.0)
        self.assertEqual(alloc.rotation_regime, "bitcoin_led")

    def test_altcoin_rotation_favors_alts(self) -> None:
        alloc = compute_sector_allocation(55.0, 57.0)
        self.assertGreater(alloc.large_alt_weight, alloc.btc_weight)


class SectorWeightsTests(unittest.TestCase):
    def test_distributes_weights_across_universe(self) -> None:
        universe = ["BTCUSD", "ETHUSD", "SOLUSD", "SHIBUSD"]
        weights = sector_rotation_weights(universe, 60.0, 59.0)
        self.assertEqual(len(weights), len(universe))
        for w in weights.values():
            self.assertGreater(w, 0)

    def test_all_weights_are_positive(self) -> None:
        universe = ["BTCUSD", "ETHUSD", "SOLUSD"]
        weights = sector_rotation_weights(universe, 58.0, 58.0)
        for w in weights.values():
            self.assertGreater(w, 0)

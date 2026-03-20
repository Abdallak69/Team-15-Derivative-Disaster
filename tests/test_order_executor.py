"""Tests for rebalance order generation."""

from __future__ import annotations

import unittest

from bot.execution.order_executor import generate_rebalance_orders


class OrderExecutorTests(unittest.TestCase):
    def test_generate_rebalance_orders_flattens_removed_positions(self) -> None:
        orders = generate_rebalance_orders(
            current_weights={"BTCUSD": 0.25, "ETHUSD": 0.10},
            target_weights={"BTCUSD": 0.20},
            portfolio_value=1_000_000.0,
            prices={"BTCUSD": 80_000.0, "ETHUSD": 2_500.0},
        )

        sides = {(o.side, o.symbol) for o in orders}
        self.assertIn(("SELL", "BTCUSD"), sides)
        self.assertIn(("SELL", "ETHUSD"), sides)

    def test_generate_rebalance_orders_produces_buy_orders(self) -> None:
        orders = generate_rebalance_orders(
            current_weights={},
            target_weights={"BTCUSD": 0.10, "ETHUSD": 0.05},
            portfolio_value=1_000_000.0,
            prices={"BTCUSD": 80_000.0, "ETHUSD": 2_500.0},
        )

        sides = {(o.side, o.symbol) for o in orders}
        self.assertIn(("BUY", "BTCUSD"), sides)
        self.assertIn(("BUY", "ETHUSD"), sides)

    def test_sells_come_before_buys(self) -> None:
        orders = generate_rebalance_orders(
            current_weights={"BTCUSD": 0.30},
            target_weights={"BTCUSD": 0.10, "ETHUSD": 0.20},
            portfolio_value=1_000_000.0,
            prices={"BTCUSD": 80_000.0, "ETHUSD": 2_500.0},
        )

        sell_indices = [i for i, o in enumerate(orders) if o.side == "SELL"]
        buy_indices = [i for i, o in enumerate(orders) if o.side == "BUY"]
        if sell_indices and buy_indices:
            self.assertLess(max(sell_indices), min(buy_indices))

    def test_min_drift_filters_small_changes(self) -> None:
        orders = generate_rebalance_orders(
            current_weights={"BTCUSD": 0.10},
            target_weights={"BTCUSD": 0.11},
            portfolio_value=1_000_000.0,
            prices={"BTCUSD": 80_000.0},
            min_rebalance_drift=0.05,
        )
        self.assertEqual(len(orders), 0)

    def test_limit_order_pricing_applies_offset(self) -> None:
        orders = generate_rebalance_orders(
            current_weights={},
            target_weights={"BTCUSD": 0.10},
            portfolio_value=1_000_000.0,
            prices={"BTCUSD": 80_000.0},
            limit_offset_pct=0.0001,
        )
        self.assertEqual(len(orders), 1)
        buy = orders[0]
        self.assertEqual(buy.order_type, "LIMIT")
        self.assertAlmostEqual(buy.price, 80_000.0 * (1 - 0.0001), places=2)

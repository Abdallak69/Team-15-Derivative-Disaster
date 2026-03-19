"""Tests for rebalance order generation."""

from __future__ import annotations

import unittest

from bot.execution.order_executor import generate_rebalance_orders


class OrderExecutorTests(unittest.TestCase):
    def test_generate_rebalance_orders_flattens_removed_positions(self) -> None:
        orders = generate_rebalance_orders(
            current_weights={"BTCUSD": 0.25, "ETHUSD": 0.10},
            target_weights={"BTCUSD": 0.20},
        )

        summary = {(order.side, order.symbol, order.target_weight) for order in orders}
        self.assertIn(("SELL", "BTCUSD", 0.20), summary)
        self.assertIn(("SELL", "ETHUSD", 0.0), summary)

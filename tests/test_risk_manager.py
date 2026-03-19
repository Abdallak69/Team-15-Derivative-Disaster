"""Tests for the integrated risk manager."""

from __future__ import annotations

import unittest

from bot.risk.circuit_breaker import CircuitBreaker
from bot.risk.risk_manager import RiskManager, enforce_position_limit


def _snapshot(
    *,
    timestamp: int = 1710800000,
    portfolio_value: float = 1000.0,
    positions: list[dict[str, float | str]] | None = None,
    pending_orders: list[dict[str, str]] | None = None,
) -> dict[str, object]:
    return {
        "cash_usd": 0.0,
        "pending_orders": pending_orders or [],
        "positions": positions or [],
        "timestamp": timestamp,
        "total_portfolio_value_usd": portfolio_value,
    }


class RiskManagerTests(unittest.TestCase):
    def test_enforce_position_limit_caps_allocations(self) -> None:
        capped = enforce_position_limit({"BTCUSD": 0.25, "ETHUSD": 0.05}, max_position_pct=0.10)
        self.assertEqual(capped["BTCUSD"], 0.10)
        self.assertEqual(capped["ETHUSD"], 0.05)

    def test_evaluate_risk_triggers_stop_loss_once_per_open_position(self) -> None:
        manager = RiskManager(stop_loss_pct=0.03)
        snapshot = _snapshot(
            positions=[
                {
                    "pair": "BTCUSD",
                    "quantity": 1.0,
                    "entry_price": 100.0,
                    "last_price": 96.0,
                    "market_value_usd": 96.0,
                }
            ]
        )
        state = manager.make_initial_state(snapshot)

        first_result = manager.evaluate_risk(snapshot, state)
        second_result = manager.evaluate_risk(snapshot, state)

        self.assertEqual(first_result["forced_sells"][0]["pair"], "BTCUSD")
        self.assertEqual(first_result["forced_sells"][0]["action"], "SELL_FULL")
        self.assertEqual(second_result["forced_sells"], [])
        self.assertEqual(state["pending_exit_pairs"], ["BTCUSD"])

    def test_evaluate_risk_respects_existing_pending_sell_orders(self) -> None:
        manager = RiskManager(stop_loss_pct=0.03)
        snapshot = _snapshot(
            positions=[
                {
                    "pair": "BTCUSD",
                    "quantity": 1.0,
                    "entry_price": 100.0,
                    "last_price": 95.0,
                    "market_value_usd": 95.0,
                }
            ],
            pending_orders=[{"pair": "BTCUSD", "side": "SELL", "status": "NEW"}],
        )
        state = manager.make_initial_state(snapshot)

        result = manager.evaluate_risk(snapshot, state)

        self.assertEqual(result["forced_sells"], [])
        self.assertEqual(state["pending_exit_pairs"], ["BTCUSD"])

    def test_evaluate_risk_rolls_day_start_forward_before_daily_loss_check(self) -> None:
        manager = RiskManager(daily_loss_limit=0.02)
        day_one = _snapshot(timestamp=1710800000, portfolio_value=1000.0)
        day_two = _snapshot(timestamp=1710887000, portfolio_value=970.0)
        state = manager.make_initial_state(day_one)

        result = manager.evaluate_risk(day_two, state)

        self.assertFalse(result["block_new_buys"])
        self.assertEqual(state["day_key"], day_two["timestamp"] // 86400)
        self.assertEqual(state["day_start_value"], 970.0)
        self.assertFalse(state["daily_loss_hit_today"])


class CircuitBreakerTests(unittest.TestCase):
    def test_circuit_breaker_latches_levels_and_applies_pause(self) -> None:
        breaker = CircuitBreaker(level_one=0.03, level_two=0.05)
        manager = RiskManager()
        initial = _snapshot(portfolio_value=1000.0)
        state = manager.make_initial_state(initial)

        state, action_one, drawdown_one = breaker.check_circuit_breaker(
            _snapshot(timestamp=1710800060, portfolio_value=960.0),
            state,
        )
        state, action_two, drawdown_two = breaker.check_circuit_breaker(
            _snapshot(timestamp=1710800120, portfolio_value=955.0),
            state,
        )
        state, action_three, drawdown_three = breaker.check_circuit_breaker(
            _snapshot(timestamp=1710800180, portfolio_value=940.0),
            state,
        )
        state, action_four, drawdown_four = breaker.check_circuit_breaker(
            _snapshot(timestamp=1710800240, portfolio_value=930.0),
            state,
        )
        state, _, drawdown_reset = breaker.check_circuit_breaker(
            _snapshot(timestamp=1710800300, portfolio_value=1100.0),
            state,
        )

        self.assertEqual(action_one, "REDUCE_ALL_50")
        self.assertAlmostEqual(drawdown_one, 0.04)
        self.assertIsNone(action_two)
        self.assertAlmostEqual(drawdown_two, 0.045)
        self.assertEqual(action_three, "LIQUIDATE_ALL")
        self.assertAlmostEqual(drawdown_three, 0.06)
        self.assertEqual(state["paused_until"], 1710800180 + 86400)
        self.assertIsNone(action_four)
        self.assertAlmostEqual(drawdown_four, 0.07)
        self.assertEqual(state["highest_cb_triggered"], 0)
        self.assertEqual(state["peak_value"], 1100.0)
        self.assertAlmostEqual(drawdown_reset, 0.0)
        self.assertAlmostEqual(state["max_drawdown"], 0.07)

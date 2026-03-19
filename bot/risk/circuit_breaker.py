"""Circuit breaker helpers."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any


def update_drawdown(
    snapshot: Mapping[str, Any],
    state: dict[str, Any],
) -> tuple[dict[str, Any], float]:
    value = float(snapshot["total_portfolio_value_usd"])

    if value > state["peak_value"]:
        state["peak_value"] = value
        state["highest_cb_triggered"] = 0

    current_drawdown = 0.0
    if state["peak_value"] > 0:
        current_drawdown = (state["peak_value"] - value) / state["peak_value"]

    state["max_drawdown"] = max(float(state["max_drawdown"]), current_drawdown)

    return state, current_drawdown


def check_circuit_breaker(
    snapshot: Mapping[str, Any],
    state: dict[str, Any],
    *,
    level_one: float = 0.03,
    level_two: float = 0.05,
    pause_seconds: int = 86400,
) -> tuple[dict[str, Any], str | None, float]:
    state, current_drawdown = update_drawdown(snapshot, state)

    now = int(snapshot["timestamp"])
    action = None

    if current_drawdown >= level_two and state["highest_cb_triggered"] < 2:
        action = "LIQUIDATE_ALL"
        state["highest_cb_triggered"] = 2
        state["paused_until"] = now + pause_seconds
    elif current_drawdown >= level_one and state["highest_cb_triggered"] < 1:
        action = "REDUCE_ALL_50"
        state["highest_cb_triggered"] = 1

    return state, action, current_drawdown


@dataclass(slots=True)
class CircuitBreaker:
    """Portfolio-level drawdown evaluator with the local latch semantics preserved."""

    level_one: float = 0.03
    level_two: float = 0.05
    pause_seconds: int = 86400

    def evaluate(self, drawdown_pct: float) -> str:
        """Return the coarse circuit-breaker level for the supplied drawdown."""
        if drawdown_pct >= self.level_two:
            return "halt"
        if drawdown_pct >= self.level_one:
            return "reduce"
        return "ok"

    def update_drawdown(
        self,
        snapshot: Mapping[str, Any],
        state: dict[str, Any],
    ) -> tuple[dict[str, Any], float]:
        return update_drawdown(snapshot, state)

    def check_circuit_breaker(
        self,
        snapshot: Mapping[str, Any],
        state: dict[str, Any],
    ) -> tuple[dict[str, Any], str | None, float]:
        return check_circuit_breaker(
            snapshot,
            state,
            level_one=self.level_one,
            level_two=self.level_two,
            pause_seconds=self.pause_seconds,
        )

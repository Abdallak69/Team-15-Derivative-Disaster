"""Risk management helpers."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any


def enforce_position_limit(
    weights: Mapping[str, float],
    max_position_pct: float,
) -> dict[str, float]:
    """Clip individual weights to the configured position limit."""
    return {
        symbol: min(max(weight, 0.0), max_position_pct)
        for symbol, weight in weights.items()
        if weight > 0
    }


def get_day_key(snapshot: Mapping[str, Any]) -> int:
    """Bucket a snapshot into a UTC day key."""
    return int(snapshot["timestamp"]) // 86400


def make_initial_state(snapshot: Mapping[str, Any]) -> dict[str, Any]:
    """Return the mutable state expected by the transplanted local risk logic."""
    value = float(snapshot["total_portfolio_value_usd"])
    day_key = get_day_key(snapshot)

    return {
        "peak_value": value,
        "max_drawdown": 0.0,
        "day_key": day_key,
        "day_start_value": value,
        "daily_loss_hit_today": False,
        "paused_until": None,
        "highest_cb_triggered": 0,
        "pending_exit_pairs": [],
    }


def _coerce_float(value: Any) -> float | None:
    if value in (None, ""):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _extract_order_pair(order: Mapping[str, Any]) -> str | None:
    for key in ("pair", "Pair", "symbol", "Symbol", "asset", "Asset"):
        value = order.get(key)
        if value not in (None, ""):
            return str(value)
    return None


def _extract_order_side(order: Mapping[str, Any]) -> str:
    for key in ("side", "Side", "action", "Action"):
        value = order.get(key)
        if value not in (None, ""):
            return str(value).upper()
    return ""


def _extract_order_status(order: Mapping[str, Any]) -> str:
    for key in ("status", "Status", "state", "State"):
        value = order.get(key)
        if value not in (None, ""):
            return str(value).upper()
    return ""


def check_position_stop_losses(
    snapshot: Mapping[str, Any],
    state: dict[str, Any],
    *,
    stop_loss_pct: float = 0.03,
) -> list[dict[str, Any]]:
    forced_sells = []
    pending_exit_pairs = state["pending_exit_pairs"]

    for position in snapshot["positions"]:
        pair = str(position["pair"])

        if pair in pending_exit_pairs:
            continue

        entry_price = _coerce_float(position.get("entry_price"))
        last_price = _coerce_float(position.get("last_price"))

        if entry_price is None or entry_price <= 0 or last_price is None:
            continue

        pnl_pct = (last_price - entry_price) / entry_price

        if pnl_pct <= -stop_loss_pct:
            quantity = _coerce_float(position.get("quantity")) or 0.0
            forced_sells.append(
                {
                    "pair": pair,
                    "action": "SELL_FULL",
                    "quantity": quantity,
                    "reason": "stop_loss",
                }
            )
            pending_exit_pairs.append(pair)

    return forced_sells


def check_daily_loss(
    snapshot: Mapping[str, Any],
    state: dict[str, Any],
    *,
    daily_loss_limit: float = 0.02,
) -> bool:
    current_value = float(snapshot["total_portfolio_value_usd"])
    day_start_value = float(state["day_start_value"])

    if day_start_value <= 0:
        return False

    daily_return = (current_value - day_start_value) / day_start_value
    if daily_return <= -daily_loss_limit:
        state["daily_loss_hit_today"] = True

    return bool(state["daily_loss_hit_today"])


def rollover_day_if_needed(snapshot: Mapping[str, Any], state: dict[str, Any]) -> None:
    day_key = get_day_key(snapshot)

    if day_key != state["day_key"]:
        state["day_key"] = day_key
        state["day_start_value"] = float(snapshot["total_portfolio_value_usd"])
        state["daily_loss_hit_today"] = False


def cleanup_pending_exit_pairs(snapshot: Mapping[str, Any], state: dict[str, Any]) -> None:
    open_pairs = {str(position["pair"]) for position in snapshot["positions"]}

    state["pending_exit_pairs"] = [
        pair for pair in state["pending_exit_pairs"] if pair in open_pairs
    ]


def sync_pending_exit_pairs(snapshot: Mapping[str, Any], state: dict[str, Any]) -> None:
    """Protect against duplicate exits when sell orders are already pending in the runtime."""
    open_pairs = {str(position["pair"]) for position in snapshot["positions"]}
    pending_exit_pairs = list(state["pending_exit_pairs"])

    for order in snapshot.get("pending_orders", []):
        if not isinstance(order, Mapping):
            continue
        pair = _extract_order_pair(order)
        if pair is None or pair not in open_pairs:
            continue
        if _extract_order_side(order) != "SELL":
            continue
        status = _extract_order_status(order)
        if status and status in {"CANCELLED", "CANCELED", "FILLED", "REJECTED", "EXPIRED"}:
            continue
        if pair not in pending_exit_pairs:
            pending_exit_pairs.append(pair)

    state["pending_exit_pairs"] = pending_exit_pairs


def refresh_pending_exit_pairs(snapshot: Mapping[str, Any], state: dict[str, Any]) -> None:
    """Keep tracked pending exits aligned with open positions and live sell orders."""
    cleanup_pending_exit_pairs(snapshot, state)
    sync_pending_exit_pairs(snapshot, state)


def evaluate_risk(
    snapshot: Mapping[str, Any],
    state: dict[str, Any],
    *,
    stop_loss_pct: float = 0.03,
    daily_loss_limit: float = 0.02,
) -> dict[str, Any]:
    rollover_day_if_needed(snapshot, state)
    refresh_pending_exit_pairs(snapshot, state)
    forced_sells = check_position_stop_losses(
        snapshot,
        state,
        stop_loss_pct=stop_loss_pct,
    )
    block_new_buys = check_daily_loss(
        snapshot,
        state,
        daily_loss_limit=daily_loss_limit,
    )

    return {
        "state": state,
        "forced_sells": forced_sells,
        "block_new_buys": block_new_buys,
    }


@dataclass(frozen=True, slots=True)
class RiskDecision:
    """Serializable runtime decision consumed by the orchestrator layer."""

    portfolio_action: str | None = None
    forced_sells: tuple[dict[str, Any], ...] = ()
    block_new_buys: bool = False
    current_drawdown: float = 0.0
    max_drawdown: float = 0.0
    daily_loss_hit_today: bool = False
    paused_until: int | None = None
    paused: bool = False
    priority: str = "NONE"
    reason: str = "ok"

    def to_dict(self) -> dict[str, Any]:
        return {
            "block_new_buys": self.block_new_buys,
            "current_drawdown": self.current_drawdown,
            "daily_loss_hit_today": self.daily_loss_hit_today,
            "forced_sells": [dict(order) for order in self.forced_sells],
            "max_drawdown": self.max_drawdown,
            "paused": self.paused,
            "paused_until": self.paused_until,
            "portfolio_action": self.portfolio_action,
            "priority": self.priority,
            "reason": self.reason,
        }


@dataclass(slots=True)
class RiskManager:
    """Position limit and per-position risk gate manager."""

    max_position_pct: float = 0.10
    stop_loss_pct: float = 0.03
    daily_loss_limit: float = 0.02

    def apply_position_limits(self, weights: Mapping[str, float]) -> dict[str, float]:
        """Enforce the configured maximum allocation per symbol."""
        return enforce_position_limit(weights, self.max_position_pct)

    def make_initial_state(self, snapshot: Mapping[str, Any]) -> dict[str, Any]:
        return make_initial_state(snapshot)

    def check_position_stop_losses(
        self,
        snapshot: Mapping[str, Any],
        state: dict[str, Any],
    ) -> list[dict[str, Any]]:
        return check_position_stop_losses(
            snapshot,
            state,
            stop_loss_pct=self.stop_loss_pct,
        )

    def check_daily_loss(self, snapshot: Mapping[str, Any], state: dict[str, Any]) -> bool:
        return check_daily_loss(
            snapshot,
            state,
            daily_loss_limit=self.daily_loss_limit,
        )

    def rollover_day_if_needed(self, snapshot: Mapping[str, Any], state: dict[str, Any]) -> None:
        rollover_day_if_needed(snapshot, state)

    def cleanup_pending_exit_pairs(
        self,
        snapshot: Mapping[str, Any],
        state: dict[str, Any],
    ) -> None:
        cleanup_pending_exit_pairs(snapshot, state)

    def sync_pending_exit_pairs(self, snapshot: Mapping[str, Any], state: dict[str, Any]) -> None:
        sync_pending_exit_pairs(snapshot, state)

    def refresh_pending_exit_pairs(
        self,
        snapshot: Mapping[str, Any],
        state: dict[str, Any],
    ) -> None:
        refresh_pending_exit_pairs(snapshot, state)

    def evaluate_risk(self, snapshot: Mapping[str, Any], state: dict[str, Any]) -> dict[str, Any]:
        return evaluate_risk(
            snapshot,
            state,
            stop_loss_pct=self.stop_loss_pct,
            daily_loss_limit=self.daily_loss_limit,
        )

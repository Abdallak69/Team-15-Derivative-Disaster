"""Order execution — weight-to-order conversion, precision, and API placement."""

from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass
from typing import Any, Mapping, Sequence

logger = logging.getLogger("tradingbot.system")
trade_logger = logging.getLogger("tradingbot.trades")


@dataclass(frozen=True, slots=True)
class OrderProposal:
    """Concrete order ready for submission."""

    side: str
    symbol: str
    quantity: float
    price: float
    order_type: str
    target_weight: float


def _round_step(value: float, precision: int | None) -> float:
    """Round value to the given decimal precision, defaulting to 8."""
    p = precision if precision is not None else 8
    return round(value, p)


def generate_rebalance_orders(
    current_weights: Mapping[str, float],
    target_weights: Mapping[str, float],
    *,
    portfolio_value: float,
    prices: Mapping[str, float],
    exchange_info: Mapping[str, Any] | None = None,
    limit_offset_pct: float = 0.0001,
    min_rebalance_drift: float = 0.0,
    prefer_limit: bool = True,
) -> list[OrderProposal]:
    """Convert weight diffs into concrete order proposals sorted sells-first.

    Parameters
    ----------
    current_weights : current portfolio allocation fractions
    target_weights  : desired portfolio allocation fractions
    portfolio_value : total portfolio value in quote currency
    prices          : {symbol: last_price} for order sizing
    exchange_info   : optional {symbol: MarketDefinition-like} for precision
    limit_offset_pct: offset from LastPrice for limit orders
    min_rebalance_drift: minimum abs weight drift to generate an order
    prefer_limit    : use LIMIT orders (5 bps) vs MARKET (10 bps)
    """
    orders: list[OrderProposal] = []
    all_symbols = set(current_weights) | set(target_weights)

    for symbol in sorted(all_symbols):
        target_w = target_weights.get(symbol, 0.0)
        current_w = current_weights.get(symbol, 0.0)
        drift = target_w - current_w

        if abs(drift) <= min_rebalance_drift:
            continue

        last_price = prices.get(symbol)
        if not last_price or last_price <= 0:
            logger.warning("No price for %s — skipping order", symbol)
            continue

        notional = abs(drift) * portfolio_value
        quantity = notional / last_price

        price_prec: int | None = None
        qty_prec: int | None = None
        min_order: float | None = None
        if exchange_info and symbol in exchange_info:
            info = exchange_info[symbol]
            price_prec = getattr(info, "price_precision", None) or info.get("price_precision") if isinstance(info, dict) else getattr(info, "price_precision", None)
            qty_prec = getattr(info, "amount_precision", None) or info.get("amount_precision") if isinstance(info, dict) else getattr(info, "amount_precision", None)
            min_order = getattr(info, "min_order_size", None) or info.get("min_order_size") if isinstance(info, dict) else getattr(info, "min_order_size", None)

        quantity = _round_step(quantity, qty_prec)
        if quantity <= 0:
            continue
        if min_order is not None and quantity < min_order:
            logger.info("Order for %s below min size (%.8f < %.8f) — skipping", symbol, quantity, min_order)
            continue

        side = "BUY" if drift > 0 else "SELL"
        if prefer_limit:
            if side == "BUY":
                order_price = last_price * (1.0 - limit_offset_pct)
            else:
                order_price = last_price * (1.0 + limit_offset_pct)
            order_price = _round_step(order_price, price_prec)
            order_type = "LIMIT"
        else:
            order_price = last_price
            order_type = "MARKET"

        orders.append(OrderProposal(
            side=side,
            symbol=symbol,
            quantity=quantity,
            price=order_price,
            order_type=order_type,
            target_weight=target_w,
        ))

    sells = [o for o in orders if o.side == "SELL"]
    buys = [o for o in orders if o.side == "BUY"]
    return sells + buys


def execute_orders(
    orders: Sequence[OrderProposal],
    client: Any,
    *,
    spacing_seconds: float = 65.0,
    dry_run: bool = False,
) -> list[dict[str, Any]]:
    """Place orders via the API client with inter-order spacing.

    Returns a list of result dicts (one per order) containing order_id
    or error information.  In dry_run mode, orders are logged but not
    placed.
    """
    results: list[dict[str, Any]] = []
    for idx, order in enumerate(orders):
        record: dict[str, Any] = {
            "ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "action": order.side,
            "pair": order.symbol,
            "type": order.order_type,
            "qty": order.quantity,
            "price": order.price,
            "target_weight": order.target_weight,
            "status": "PENDING",
            "order_id": None,
            "commission": None,
        }

        if dry_run:
            record["status"] = "DRY_RUN"
            logger.info(
                "DRY_RUN %s %s qty=%.8f price=%.8f",
                order.side, order.symbol, order.quantity, order.price,
            )
            trade_logger.info(json.dumps(record, default=str))
            results.append(record)
            continue

        try:
            params: dict[str, Any] = {
                "pair": order.symbol,
                "side": order.side,
                "type": order.order_type,
                "quantity": order.quantity,
            }
            if order.order_type == "LIMIT":
                params["price"] = order.price

            response = client.place_order(**params)
            order_id = (
                response.get("OrderId")
                or response.get("orderId")
                or response.get("order_id")
            )
            record["order_id"] = order_id
            record["status"] = "PLACED"
            logger.info(
                "PLACED %s %s qty=%.8f price=%.8f order_id=%s",
                order.side, order.symbol, order.quantity, order.price, order_id,
            )
        except Exception:
            record["status"] = "FAILED"
            logger.exception("Failed to place %s %s", order.side, order.symbol)

        trade_logger.info(json.dumps(record, default=str))
        results.append(record)

        if idx < len(orders) - 1 and spacing_seconds > 0:
            time.sleep(spacing_seconds)

    return results

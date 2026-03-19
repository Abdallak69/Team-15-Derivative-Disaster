"""Utilities for deriving the tradable universe from exchange metadata."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any
from typing import Iterable


def _first_present(payload: Mapping[str, Any], *keys: str) -> Any:
    for key in keys:
        if key in payload and payload[key] not in (None, ""):
            return payload[key]
    return None


def _coerce_int(value: Any) -> int | None:
    if value in (None, ""):
        return None
    return int(value)


def _coerce_float(value: Any) -> float | None:
    if value in (None, ""):
        return None
    return float(value)


@dataclass(frozen=True, slots=True)
class MarketDefinition:
    """Normalized market metadata from `/v3/exchangeInfo`."""

    symbol: str
    status: str
    price_precision: int | None
    amount_precision: int | None
    min_order_size: float | None


@dataclass(slots=True)
class UniverseBuilder:
    """Build a sorted asset universe from exchange info payloads."""

    def parse_exchange_info(
        self,
        exchange_info: Iterable[Mapping[str, Any]] | Mapping[str, Any],
    ) -> dict[str, MarketDefinition]:
        """Return normalized market definitions keyed by symbol."""
        records = self._normalize_records(exchange_info)
        markets: dict[str, MarketDefinition] = {}
        for item in records:
            symbol = _first_present(item, "Pair", "pair", "symbol", "Symbol")
            if not symbol:
                continue
            status = str(_first_present(item, "Status", "status") or "TRADING")
            markets[str(symbol)] = MarketDefinition(
                symbol=str(symbol),
                status=status,
                price_precision=_coerce_int(
                    _first_present(item, "PricePrecision", "pricePrecision")
                ),
                amount_precision=_coerce_int(
                    _first_present(item, "AmountPrecision", "amountPrecision")
                ),
                min_order_size=_coerce_float(
                    _first_present(item, "MiniOrder", "MinOrder", "minOrder", "miniOrder")
                ),
            )
        return markets

    def build_from_exchange_info(
        self,
        exchange_info: Iterable[Mapping[str, Any]] | Mapping[str, Any],
    ) -> list[str]:
        """Select symbols marked as trading and return them in sorted order."""
        markets = self.parse_exchange_info(exchange_info)
        universe = {
            symbol
            for symbol, market in markets.items()
            if market.status.upper() == "TRADING"
        }
        return sorted(universe)

    @staticmethod
    def _normalize_records(
        exchange_info: Iterable[Mapping[str, Any]] | Mapping[str, Any],
    ) -> list[dict[str, Any]]:
        if isinstance(exchange_info, Mapping):
            for key in ("Data", "data", "Result", "result"):
                if key in exchange_info:
                    return UniverseBuilder._normalize_records(exchange_info[key])

            records: list[dict[str, Any]] = []
            for symbol, value in exchange_info.items():
                if not isinstance(value, Mapping):
                    continue
                record = dict(value)
                if not any(field in record for field in ("Pair", "pair", "symbol", "Symbol")):
                    record["symbol"] = symbol
                records.append(record)
            return records or [dict(exchange_info)]

        return [dict(item) for item in exchange_info if isinstance(item, Mapping)]

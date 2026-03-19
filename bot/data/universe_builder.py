"""Utilities for deriving the tradable universe from exchange metadata."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable, Mapping


@dataclass(slots=True)
class UniverseBuilder:
    """Build a sorted asset universe from exchange info payloads."""

    def build_from_exchange_info(
        self,
        exchange_info: Iterable[Mapping[str, Any]],
    ) -> list[str]:
        """Select symbols marked as trading and return them in sorted order."""
        universe = {
            item["symbol"]
            for item in exchange_info
            if item.get("status", "TRADING") == "TRADING" and item.get("symbol")
        }
        return sorted(universe)


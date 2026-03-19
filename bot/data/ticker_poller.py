"""Ticker polling scaffold."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any


@dataclass(slots=True)
class TickerPoller:
    """Minimal polling shell that records which pairs are being tracked."""

    pairs: tuple[str, ...] = ()

    def poll(self) -> dict[str, Any]:
        """Return a lightweight polling snapshot."""
        return {
            "pairs": list(self.pairs),
            "tickers": [],
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }


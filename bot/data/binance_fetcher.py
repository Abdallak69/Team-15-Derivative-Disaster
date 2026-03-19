"""Helpers for constructing Binance historical data requests."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(slots=True)
class BinanceFetcher:
    """Small URL builder for future Binance integration."""

    base_url: str = "https://api.binance.com"

    def klines_url(self, symbol: str, interval: str = "1h") -> str:
        """Return the public kline endpoint for a symbol and interval."""
        return (
            f"{self.base_url.rstrip('/')}/api/v3/klines"
            f"?symbol={symbol.upper()}&interval={interval}"
        )


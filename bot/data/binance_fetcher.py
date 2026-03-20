"""Binance public-market historical data helpers."""

from __future__ import annotations

from dataclasses import dataclass
from dataclasses import field
from datetime import datetime
from datetime import timezone
import logging
from typing import Any

import requests
from tenacity import before_sleep_log
from tenacity import retry
from tenacity import retry_if_exception_type
from tenacity import stop_after_attempt
from tenacity import wait_exponential


_INTERVAL_MS = {
    "1m": 60_000,
    "5m": 5 * 60_000,
    "15m": 15 * 60_000,
    "30m": 30 * 60_000,
    "1h": 60 * 60_000,
    "4h": 4 * 60 * 60_000,
    "1d": 24 * 60 * 60_000,
}
LOGGER = logging.getLogger("tradingbot.system")


class BinanceApiError(RuntimeError):
    """Raised when Binance returns an invalid non-retryable response."""


class TransientBinanceRequestError(RuntimeError):
    """Raised for retryable Binance transport or server failures."""


def normalize_binance_symbol(symbol: str) -> str:
    """Map Roostoo-style `BTCUSD` symbols to Binance spot symbols."""
    normalized = (
        symbol.upper()
        .replace("/", "")
        .replace("-", "")
        .replace("_", "")
        .replace(" ", "")
    )
    if normalized.endswith("USD") and not normalized.endswith("USDT"):
        return f"{normalized}T"
    return normalized


def _coerce_timestamp_ms(value: int | datetime | None) -> int | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        timestamp = value.astimezone(timezone.utc)
        return int(timestamp.timestamp() * 1000)
    return int(value)


@dataclass(frozen=True, slots=True)
class BinanceKline:
    """Normalized Binance OHLCV record."""

    symbol: str
    interval: str
    open_time_ms: int
    close_time_ms: int
    open: float
    high: float
    low: float
    close: float
    volume: float
    quote_volume: float
    trade_count: int
    taker_buy_base_volume: float
    taker_buy_quote_volume: float

    @classmethod
    def from_api_row(
        cls,
        *,
        symbol: str,
        interval: str,
        row: list[Any],
    ) -> BinanceKline:
        """Build a normalized kline from Binance's array payload."""
        return cls(
            symbol=normalize_binance_symbol(symbol),
            interval=interval,
            open_time_ms=int(row[0]),
            open=float(row[1]),
            high=float(row[2]),
            low=float(row[3]),
            close=float(row[4]),
            volume=float(row[5]),
            close_time_ms=int(row[6]),
            quote_volume=float(row[7]),
            trade_count=int(row[8]),
            taker_buy_base_volume=float(row[9]),
            taker_buy_quote_volume=float(row[10]),
        )


@dataclass(slots=True)
class BinanceFetcher:
    """Small Binance public-market data client with kline pagination."""

    base_url: str = "https://api.binance.com"
    timeout_seconds: float = 10.0
    session: requests.Session | Any = field(default_factory=requests.Session)

    @staticmethod
    def interval_to_milliseconds(interval: str) -> int:
        """Return the candle width for a supported Binance interval."""
        if interval not in _INTERVAL_MS:
            raise ValueError(f"Unsupported Binance interval: {interval}")
        return _INTERVAL_MS[interval]

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=1, max=8),
        retry=retry_if_exception_type(
            (requests.ConnectionError, requests.Timeout, TransientBinanceRequestError)
        ),
        before_sleep=before_sleep_log(LOGGER, logging.WARNING),
        reraise=True,
    )
    def get_klines(
        self,
        *,
        symbol: str,
        interval: str = "1h",
        start_time_ms: int | datetime | None = None,
        end_time_ms: int | datetime | None = None,
        limit: int = 1000,
    ) -> list[BinanceKline]:
        """Fetch one page of klines from Binance."""
        normalized_symbol = normalize_binance_symbol(symbol)
        params: dict[str, Any] = {
            "symbol": normalized_symbol,
            "interval": interval,
            "limit": min(int(limit), 1000),
        }
        start_ms = _coerce_timestamp_ms(start_time_ms)
        end_ms = _coerce_timestamp_ms(end_time_ms)
        if start_ms is not None:
            params["startTime"] = start_ms
        if end_ms is not None:
            params["endTime"] = end_ms

        response = self.session.get(
            f"{self.base_url.rstrip('/')}/api/v3/klines",
            params=params,
            timeout=self.timeout_seconds,
        )
        status_code = int(getattr(response, "status_code", 200))
        if status_code == 429 or status_code >= 500:
            raise TransientBinanceRequestError(
                f"Retryable Binance status {status_code} while fetching klines."
            )
        response.raise_for_status()
        try:
            payload = response.json()
        except ValueError as exc:
            raise BinanceApiError("Invalid JSON response from Binance klines endpoint.") from exc
        if not isinstance(payload, list):
            raise BinanceApiError("Unexpected Binance klines response payload.")
        return [
            BinanceKline.from_api_row(symbol=normalized_symbol, interval=interval, row=row)
            for row in payload
            if isinstance(row, list) and len(row) >= 11
        ]

    def iter_historical_klines(
        self,
        *,
        symbol: str,
        interval: str,
        start_time_ms: int | datetime,
        end_time_ms: int | datetime | None = None,
        limit: int = 1000,
    ) -> list[BinanceKline]:
        """Fetch all klines in a time range by paging Binance's public endpoint."""
        klines: list[BinanceKline] = []
        cursor_ms = _coerce_timestamp_ms(start_time_ms)
        stop_ms = _coerce_timestamp_ms(end_time_ms)
        if cursor_ms is None:
            raise ValueError("A start time is required for historical kline pagination.")

        step_ms = self.interval_to_milliseconds(interval)
        while True:
            page = self.get_klines(
                symbol=symbol,
                interval=interval,
                start_time_ms=cursor_ms,
                end_time_ms=stop_ms,
                limit=limit,
            )
            if not page:
                break

            klines.extend(page)
            last_open_time_ms = page[-1].open_time_ms
            next_cursor_ms = last_open_time_ms + step_ms
            if next_cursor_ms <= cursor_ms:
                break

            cursor_ms = next_cursor_ms
            if stop_ms is not None and cursor_ms >= stop_ms:
                break

        return klines

    def fetch_historical_klines(
        self,
        *,
        symbol: str,
        interval: str,
        start_time_ms: int | datetime,
        end_time_ms: int | datetime | None = None,
    ) -> list[BinanceKline]:
        """Compatibility wrapper around the paginated historical fetch path."""
        return self.iter_historical_klines(
            symbol=symbol,
            interval=interval,
            start_time_ms=start_time_ms,
            end_time_ms=end_time_ms,
        )

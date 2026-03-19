"""Local sqlite cache for Binance historical klines."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import sqlite3
from typing import Any
from typing import Iterable

from .binance_fetcher import BinanceKline


@dataclass(slots=True)
class BinanceHistoryStore:
    """Persist Binance public klines for repeated local backtests."""

    db_path: Path

    def initialize(self) -> Path:
        """Create the Binance kline cache table when needed."""
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(self.db_path) as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS binance_klines (
                    symbol TEXT NOT NULL,
                    interval TEXT NOT NULL,
                    open_time_ms INTEGER NOT NULL,
                    close_time_ms INTEGER NOT NULL,
                    open REAL NOT NULL,
                    high REAL NOT NULL,
                    low REAL NOT NULL,
                    close REAL NOT NULL,
                    volume REAL NOT NULL,
                    quote_volume REAL NOT NULL,
                    trade_count INTEGER NOT NULL,
                    taker_buy_base_volume REAL NOT NULL,
                    taker_buy_quote_volume REAL NOT NULL,
                    PRIMARY KEY (symbol, interval, open_time_ms)
                )
                """
            )
            connection.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_binance_klines_lookup
                ON binance_klines (interval, symbol, open_time_ms)
                """
            )
        return self.db_path

    def upsert_klines(self, klines: Iterable[BinanceKline]) -> int:
        """Insert or update a batch of Binance klines."""
        batch = list(klines)
        if not batch:
            return 0

        self.initialize()
        with sqlite3.connect(self.db_path) as connection:
            connection.executemany(
                """
                INSERT INTO binance_klines (
                    symbol,
                    interval,
                    open_time_ms,
                    close_time_ms,
                    open,
                    high,
                    low,
                    close,
                    volume,
                    quote_volume,
                    trade_count,
                    taker_buy_base_volume,
                    taker_buy_quote_volume
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(symbol, interval, open_time_ms) DO UPDATE SET
                    close_time_ms = excluded.close_time_ms,
                    open = excluded.open,
                    high = excluded.high,
                    low = excluded.low,
                    close = excluded.close,
                    volume = excluded.volume,
                    quote_volume = excluded.quote_volume,
                    trade_count = excluded.trade_count,
                    taker_buy_base_volume = excluded.taker_buy_base_volume,
                    taker_buy_quote_volume = excluded.taker_buy_quote_volume
                """,
                [
                    (
                        kline.symbol,
                        kline.interval,
                        kline.open_time_ms,
                        kline.close_time_ms,
                        kline.open,
                        kline.high,
                        kline.low,
                        kline.close,
                        kline.volume,
                        kline.quote_volume,
                        kline.trade_count,
                        kline.taker_buy_base_volume,
                        kline.taker_buy_quote_volume,
                    )
                    for kline in batch
                ],
            )
        return len(batch)

    def fetch_klines(
        self,
        *,
        symbol: str,
        interval: str,
        start_time_ms: int | None = None,
        end_time_ms: int | None = None,
    ) -> list[dict[str, Any]]:
        """Load cached klines for one symbol and interval."""
        self.initialize()
        query = """
            SELECT
                symbol,
                interval,
                open_time_ms,
                close_time_ms,
                open,
                high,
                low,
                close,
                volume,
                quote_volume,
                trade_count,
                taker_buy_base_volume,
                taker_buy_quote_volume
            FROM binance_klines
            WHERE symbol = ?
              AND interval = ?
        """
        params: list[Any] = [symbol, interval]
        if start_time_ms is not None:
            query += " AND open_time_ms >= ?"
            params.append(start_time_ms)
        if end_time_ms is not None:
            query += " AND open_time_ms <= ?"
            params.append(end_time_ms)
        query += " ORDER BY open_time_ms ASC"

        with sqlite3.connect(self.db_path) as connection:
            connection.row_factory = sqlite3.Row
            rows = connection.execute(query, params).fetchall()
        return [dict(row) for row in rows]

    def get_time_range(self, *, symbol: str, interval: str) -> tuple[int | None, int | None]:
        """Return the cached min/max open times for one symbol and interval."""
        self.initialize()
        with sqlite3.connect(self.db_path) as connection:
            row = connection.execute(
                """
                SELECT MIN(open_time_ms) AS first_open_time_ms,
                       MAX(open_time_ms) AS last_open_time_ms
                FROM binance_klines
                WHERE symbol = ? AND interval = ?
                """,
                (symbol, interval),
            ).fetchone()
        if row is None:
            return None, None
        return row[0], row[1]

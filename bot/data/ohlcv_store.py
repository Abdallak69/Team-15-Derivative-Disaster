"""Local sqlite storage for ticker-derived 1-minute OHLCV candles."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from datetime import timezone
from pathlib import Path
import sqlite3
from typing import Any
from typing import Iterable


def _coerce_float(value: Any) -> float | None:
    if value in (None, ""):
        return None
    return float(value)


def _first_present(payload: dict[str, Any], *keys: str) -> Any:
    for key in keys:
        if key in payload and payload[key] not in (None, ""):
            return payload[key]
    return None


@dataclass(frozen=True, slots=True)
class TickerSnapshot:
    """Normalized ticker record used by the storage layer."""

    pair: str
    polled_at: datetime
    last_price: float
    max_bid: float | None = None
    min_ask: float | None = None
    change_pct: float | None = None
    coin_trade_value_24h: float | None = None
    unit_trade_value_24h: float | None = None

    @classmethod
    def from_api_payload(
        cls,
        payload: dict[str, Any],
        *,
        polled_at: datetime | None = None,
    ) -> TickerSnapshot:
        """Create a normalized ticker snapshot from an API response row."""
        pair = _first_present(payload, "Pair", "pair", "symbol", "Symbol")
        if not pair:
            raise ValueError("Ticker payload is missing a pair/symbol field.")

        last_price = _coerce_float(
            _first_present(payload, "LastPrice", "lastPrice", "last_price", "price")
        )
        if last_price is None:
            raise ValueError(f"Ticker payload for {pair} is missing LastPrice.")

        snapshot_time = polled_at or datetime.now(timezone.utc)
        if snapshot_time.tzinfo is None:
            snapshot_time = snapshot_time.replace(tzinfo=timezone.utc)

        return cls(
            pair=str(pair),
            polled_at=snapshot_time.astimezone(timezone.utc),
            last_price=last_price,
            max_bid=_coerce_float(_first_present(payload, "MaxBid", "maxBid", "max_bid")),
            min_ask=_coerce_float(_first_present(payload, "MinAsk", "minAsk", "min_ask")),
            change_pct=_coerce_float(_first_present(payload, "Change", "change")),
            coin_trade_value_24h=_coerce_float(
                _first_present(payload, "CoinTradeValue", "coinTradeValue")
            ),
            unit_trade_value_24h=_coerce_float(
                _first_present(payload, "UnitTradeValue", "unitTradeValue")
            ),
        )


@dataclass(slots=True)
class OhlcvStore:
    """Sqlite-backed store for 1-minute candles built from ticker polls."""

    db_path: Path

    def initialize(self) -> Path:
        """Create the candle table if it does not already exist."""
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(self.db_path) as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS ohlcv_1m (
                    pair TEXT NOT NULL,
                    candle_ts TEXT NOT NULL,
                    open REAL NOT NULL,
                    high REAL NOT NULL,
                    low REAL NOT NULL,
                    close REAL NOT NULL,
                    max_bid REAL,
                    min_ask REAL,
                    change_pct REAL,
                    coin_trade_value_24h REAL,
                    unit_trade_value_24h REAL,
                    sample_count INTEGER NOT NULL DEFAULT 1,
                    first_polled_at TEXT NOT NULL,
                    last_polled_at TEXT NOT NULL,
                    PRIMARY KEY (pair, candle_ts)
                )
                """
            )
            connection.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_ohlcv_1m_last_polled_at
                ON ohlcv_1m (last_polled_at)
                """
            )
        return self.db_path

    def database_exists(self) -> bool:
        """Return whether the sqlite file has already been created."""
        return self.db_path.exists()

    def upsert_ticker_batch(self, snapshots: Iterable[TickerSnapshot]) -> int:
        """Insert or update minute candles from a batch of ticker snapshots."""
        snapshot_batch = list(snapshots)
        if not snapshot_batch:
            return 0

        self.initialize()
        with sqlite3.connect(self.db_path) as connection:
            for snapshot in snapshot_batch:
                candle_ts = self._minute_bucket(snapshot.polled_at)
                connection.execute(
                    """
                    INSERT INTO ohlcv_1m (
                        pair,
                        candle_ts,
                        open,
                        high,
                        low,
                        close,
                        max_bid,
                        min_ask,
                        change_pct,
                        coin_trade_value_24h,
                        unit_trade_value_24h,
                        sample_count,
                        first_polled_at,
                        last_polled_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(pair, candle_ts) DO UPDATE SET
                        high = MAX(ohlcv_1m.high, excluded.high),
                        low = MIN(ohlcv_1m.low, excluded.low),
                        close = excluded.close,
                        max_bid = excluded.max_bid,
                        min_ask = excluded.min_ask,
                        change_pct = excluded.change_pct,
                        coin_trade_value_24h = excluded.coin_trade_value_24h,
                        unit_trade_value_24h = excluded.unit_trade_value_24h,
                        sample_count = ohlcv_1m.sample_count + 1,
                        last_polled_at = excluded.last_polled_at
                    """,
                    (
                        snapshot.pair,
                        candle_ts,
                        snapshot.last_price,
                        snapshot.last_price,
                        snapshot.last_price,
                        snapshot.last_price,
                        snapshot.max_bid,
                        snapshot.min_ask,
                        snapshot.change_pct,
                        snapshot.coin_trade_value_24h,
                        snapshot.unit_trade_value_24h,
                        1,
                        snapshot.polled_at.isoformat(),
                        snapshot.polled_at.isoformat(),
                    ),
                )
        return len(snapshot_batch)

    def fetch_candles(
        self,
        pair: str | None = None,
        *,
        pairs: Iterable[str] | None = None,
        since: datetime | None = None,
        limit: int | None = None,
    ) -> list[dict[str, Any]]:
        """Return stored candles filtered by pair(s), time window, and/or row limit.

        Parameters
        ----------
        pair : single pair string (e.g. ``"BTC/USD"``)
        pairs : iterable of pair strings — takes precedence over *pair*
        since : only return candles at or after this timestamp
        limit : max rows to return (default unlimited when *since* is set,
                otherwise 100)
        """
        self.initialize()

        _COLUMNS = (
            "pair, candle_ts, open, high, low, close, max_bid, min_ask, "
            "change_pct, coin_trade_value_24h, unit_trade_value_24h, "
            "sample_count, first_polled_at, last_polled_at"
        )
        clauses: list[str] = []
        params: list[Any] = []

        pair_list = list(pairs) if pairs else ([pair] if pair else [])
        if pair_list:
            placeholders = ", ".join("?" for _ in pair_list)
            clauses.append(f"pair IN ({placeholders})")
            params.extend(pair_list)

        if since is not None:
            ts = since.astimezone(timezone.utc).isoformat()
            clauses.append("candle_ts >= ?")
            params.append(ts)

        where = (" WHERE " + " AND ".join(clauses)) if clauses else ""
        row_limit = limit if limit is not None else (None if since else 100)

        query = f"SELECT {_COLUMNS} FROM ohlcv_1m{where} ORDER BY candle_ts ASC"
        if row_limit is not None:
            query += " LIMIT ?"
            params.append(row_limit)

        with sqlite3.connect(self.db_path) as connection:
            connection.row_factory = sqlite3.Row
            rows = connection.execute(query, params).fetchall()
        return [dict(row) for row in rows]

    def prune(self, max_days: int = 30) -> int:
        """Delete candles older than *max_days*. Returns rows deleted."""
        cutoff = datetime.now(timezone.utc) - __import__("datetime").timedelta(days=max_days)
        cutoff_iso = cutoff.replace(second=0, microsecond=0).isoformat()
        self.initialize()
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.execute(
                "DELETE FROM ohlcv_1m WHERE candle_ts < ?", (cutoff_iso,)
            )
            return cursor.rowcount

    @staticmethod
    def _minute_bucket(timestamp: datetime) -> str:
        normalized = timestamp.astimezone(timezone.utc).replace(second=0, microsecond=0)
        return normalized.isoformat()

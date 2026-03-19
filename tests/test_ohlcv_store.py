"""Tests for ticker-derived OHLCV persistence."""

from __future__ import annotations

from datetime import datetime
from datetime import timezone
from pathlib import Path
import tempfile
import unittest

from bot.data.ohlcv_store import OhlcvStore
from bot.data.ohlcv_store import TickerSnapshot


class OhlcvStoreTests(unittest.TestCase):
    def test_upsert_ticker_batch_aggregates_same_minute_prices(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            store = OhlcvStore(Path(tmp_dir) / "live_ohlcv.db")
            base_time = datetime(2026, 3, 19, 12, 0, 5, tzinfo=timezone.utc)

            store.upsert_ticker_batch(
                [
                    TickerSnapshot(pair="BTCUSD", polled_at=base_time, last_price=100.0),
                    TickerSnapshot(
                        pair="BTCUSD",
                        polled_at=base_time.replace(second=45),
                        last_price=102.0,
                    ),
                ]
            )

            candles = store.fetch_candles("BTCUSD")

        self.assertEqual(len(candles), 1)
        self.assertEqual(candles[0]["open"], 100.0)
        self.assertEqual(candles[0]["high"], 102.0)
        self.assertEqual(candles[0]["low"], 100.0)
        self.assertEqual(candles[0]["close"], 102.0)
        self.assertEqual(candles[0]["sample_count"], 2)

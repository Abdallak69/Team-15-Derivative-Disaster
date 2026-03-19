"""Tests for the ticker polling pipeline."""

from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

from bot.data.ohlcv_store import OhlcvStore
from bot.data.ticker_poller import TickerPoller


class FakeTickerClient:
    def get_ticker(self) -> list[dict[str, str]]:
        return [
            {
                "Pair": "BTCUSD",
                "LastPrice": "101.5",
                "MaxBid": "101.4",
                "MinAsk": "101.6",
                "UnitTradeValue": "1000000",
            },
            {
                "Pair": "ETHUSD",
                "LastPrice": "55.2",
                "MaxBid": "55.1",
                "MinAsk": "55.3",
                "UnitTradeValue": "500000",
            },
        ]


class TickerPollerTests(unittest.TestCase):
    def test_poll_filters_untracked_pairs_and_persists_results(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            store = OhlcvStore(Path(tmp_dir) / "live_ohlcv.db")
            poller = TickerPoller(
                client=FakeTickerClient(),
                store=store,
                pairs=("BTCUSD",),
            )

            result = poller.poll()
            candles = store.fetch_candles("BTCUSD")

        self.assertEqual(result.snapshot_count, 1)
        self.assertEqual(result.stored_snapshot_count, 1)
        self.assertEqual(len(candles), 1)
        self.assertEqual(candles[0]["pair"], "BTCUSD")

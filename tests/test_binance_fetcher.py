"""Tests for Binance historical data helpers."""

from __future__ import annotations

import unittest

from bot.data.binance_fetcher import BinanceFetcher
from bot.data.binance_fetcher import normalize_binance_symbol


def _kline_row(open_time_ms: int, close_price: float) -> list[object]:
    return [
        open_time_ms,
        str(close_price),
        str(close_price + 1.0),
        str(close_price - 1.0),
        str(close_price),
        "100.0",
        open_time_ms + 3_599_999,
        "10000000.0",
        42,
        "50.0",
        "5000000.0",
        "0",
    ]


class FakeResponse:
    def __init__(self, payload: object) -> None:
        self.payload = payload

    def raise_for_status(self) -> None:
        return None

    def json(self) -> object:
        return self.payload


class FakeSession:
    def __init__(self, payloads: list[object]) -> None:
        self.payloads = list(payloads)
        self.calls: list[dict[str, object]] = []

    def get(self, url: str, *, params: dict[str, object], timeout: float) -> FakeResponse:
        self.calls.append({"url": url, "params": dict(params), "timeout": timeout})
        return FakeResponse(self.payloads.pop(0))


class BinanceFetcherTests(unittest.TestCase):
    def test_normalize_binance_symbol_maps_usd_pairs_to_usdt(self) -> None:
        self.assertEqual(normalize_binance_symbol("btcusd"), "BTCUSDT")
        self.assertEqual(normalize_binance_symbol("ETHUSDT"), "ETHUSDT")

    def test_fetch_historical_klines_paginates_from_last_open_time(self) -> None:
        session = FakeSession(
            [
                [_kline_row(0, 100.0), _kline_row(3_600_000, 101.0)],
                [_kline_row(7_200_000, 102.0)],
            ]
        )
        fetcher = BinanceFetcher(session=session)

        klines = fetcher.fetch_historical_klines(
            symbol="BTCUSD",
            interval="1h",
            start_time_ms=0,
            end_time_ms=10_800_000,
        )

        self.assertEqual(len(klines), 3)
        self.assertEqual(klines[0].symbol, "BTCUSDT")
        self.assertEqual(session.calls[1]["params"]["startTime"], 7_200_000)


if __name__ == "__main__":
    unittest.main()

"""Tests for the Roostoo client."""

from __future__ import annotations

from unittest.mock import patch
import unittest

from bot.api.roostoo_client import RoostooClient


class FakeResponse:
    def __init__(self, json_payload: object, status_code: int = 200) -> None:
        self._json_payload = json_payload
        self.status_code = status_code

    def json(self) -> object:
        return self._json_payload

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")


class FakeSession:
    def __init__(self, responses: list[FakeResponse]) -> None:
        self.responses = responses
        self.calls: list[dict[str, object]] = []

    def request(self, **kwargs: object) -> FakeResponse:
        self.calls.append(kwargs)
        return self.responses.pop(0)


class RoostooClientTests(unittest.TestCase):
    def test_endpoint_registry_contains_expected_urls(self) -> None:
        client = RoostooClient()

        self.assertIn("ticker", client.available_endpoints())
        self.assertEqual(client.endpoint_url("ticker"), "https://mock-api.roostoo.com/v3/ticker")

    def test_get_ticker_adds_timestamp_and_normalizes_records(self) -> None:
        session = FakeSession(
            [
                FakeResponse(
                    {
                        "Data": {
                            "BTCUSD": {"LastPrice": "101.5", "MaxBid": "101.4"},
                            "ETHUSD": {"LastPrice": "55.2", "MaxBid": "55.1"},
                        }
                    }
                )
            ]
        )
        client = RoostooClient(session=session)

        with patch("bot.api.roostoo_client.current_timestamp_ms", return_value=1710800000000):
            tickers = client.get_ticker()

        self.assertEqual(len(tickers), 2)
        self.assertEqual(session.calls[0]["params"], {"timestamp": 1710800000000})
        self.assertEqual(tickers[0]["symbol"], "BTCUSD")

    def test_sync_server_time_updates_clock_offset(self) -> None:
        session = FakeSession([FakeResponse({"Data": {"serverTime": 2000}})])
        client = RoostooClient(session=session)

        with patch("bot.api.roostoo_client.current_timestamp_ms", side_effect=[1000, 1200]):
            server_time_ms = client.sync_server_time()

        self.assertEqual(server_time_ms, 2000)
        self.assertEqual(client.clock_offset_ms, 900)

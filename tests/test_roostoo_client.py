"""Pytest coverage for the Roostoo client."""

from __future__ import annotations

from unittest.mock import patch

import pytest
import requests

from bot.api.auth import API_KEY_HEADER
from bot.api.auth import SIGNATURE_HEADER
from bot.api.auth import AuthCredentials
from bot.api.auth import build_signature_payload
from bot.api.auth import sign_request
from bot.api.roostoo_client import ApiError
from bot.api.roostoo_client import RoostooClient


class FakeResponse:
    def __init__(
        self,
        json_payload: object | None,
        status_code: int = 200,
        json_error: Exception | None = None,
    ) -> None:
        self._json_payload = json_payload
        self.status_code = status_code
        self._json_error = json_error

    def json(self) -> object:
        if self._json_error is not None:
            raise self._json_error
        return self._json_payload

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise requests.HTTPError(f"HTTP {self.status_code}")


class FakeSession:
    def __init__(self, responses: list[FakeResponse]) -> None:
        self.responses = responses
        self.calls: list[dict[str, object]] = []

    def request(self, **kwargs: object) -> FakeResponse:
        self.calls.append(kwargs)
        return self.responses.pop(0)


def test_endpoint_registry_contains_expected_urls() -> None:
    client = RoostooClient()

    assert "ticker" in client.available_endpoints()
    assert client.endpoint_url("ticker") == "https://mock-api.roostoo.com/v3/ticker"


def test_get_ticker_adds_timestamp_and_normalizes_records() -> None:
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

    assert len(tickers) == 2
    assert session.calls[0]["params"] == {"timestamp": 1710800000000}
    assert tickers[0]["symbol"] == "BTCUSD"


def test_sync_server_time_updates_clock_offset() -> None:
    session = FakeSession([FakeResponse({"Data": {"serverTime": 2000}})])
    client = RoostooClient(session=session)

    with patch("bot.api.roostoo_client.current_timestamp_ms", side_effect=[1000, 1200]):
        server_time_ms = client.sync_server_time()

    assert server_time_ms == 2000
    assert client.clock_offset_ms == 900


def test_get_server_time_returns_parsed_value_without_mutating_offset() -> None:
    session = FakeSession([FakeResponse({"Data": {"serverTime": 3456}})])
    client = RoostooClient(session=session, clock_offset_ms=99)

    server_time_ms = client.get_server_time()

    assert server_time_ms == 3456
    assert client.clock_offset_ms == 99


def test_signed_request_includes_hmac_headers() -> None:
    session = FakeSession([FakeResponse({"Data": {"orderId": 123}})])
    client = RoostooClient(
        session=session,
        credentials=AuthCredentials(api_key="api-key", secret_key="secret-key"),
    )

    payload = client._request_json(
        "POST",
        "place_order",
        params={"timestamp": 1710800000000},
        data={"pair": "BTC/USD", "side": "BUY"},
        signed=True,
    )

    sent_headers = session.calls[0]["headers"]
    expected_signature = sign_request(
        "secret-key",
        build_signature_payload(
            {
                "pair": "BTC/USD",
                "side": "BUY",
                "timestamp": 1710800000000,
            }
        ),
    )

    assert payload == {"Data": {"orderId": 123}}
    assert sent_headers[API_KEY_HEADER] == "api-key"
    assert sent_headers[SIGNATURE_HEADER] == expected_signature
    assert sent_headers["Content-Type"] == "application/x-www-form-urlencoded"


def test_get_balance_uses_signed_get_request() -> None:
    session = FakeSession([FakeResponse({"Data": {"USD": {"Free": "1000000"}}})])
    client = RoostooClient(
        session=session,
        credentials=AuthCredentials(api_key="api-key", secret_key="secret-key"),
    )

    with patch("bot.api.roostoo_client.current_timestamp_ms", return_value=1710800000000):
        balance = client.get_balance()

    assert balance["USD"]["Free"] == "1000000"
    assert session.calls[0]["method"] == "GET"
    assert session.calls[0]["params"] == {"timestamp": 1710800000000}
    assert session.calls[0]["headers"][API_KEY_HEADER] == "api-key"


def test_place_order_uses_signed_post_payload() -> None:
    session = FakeSession([FakeResponse({"Data": {"orderId": 456}})])
    client = RoostooClient(
        session=session,
        credentials=AuthCredentials(api_key="api-key", secret_key="secret-key"),
    )

    with patch("bot.api.roostoo_client.current_timestamp_ms", return_value=1710800000000):
        payload = client.place_order(
            pair="BTC/USD",
            side="BUY",
            order_type="LIMIT",
            quantity=1.5,
            price=65000.0,
        )

    assert payload == {"Data": {"orderId": 456}}
    assert session.calls[0]["method"] == "POST"
    assert session.calls[0]["data"] == {
        "timestamp": 1710800000000,
        "pair": "BTC/USD",
        "side": "BUY",
        "type": "LIMIT",
        "quantity": 1.5,
        "price": 65000.0,
    }


def test_signed_request_requires_credentials() -> None:
    client = RoostooClient(session=FakeSession([FakeResponse({"Data": []})]))

    with pytest.raises(ApiError, match="without API credentials"):
        client._request_json("POST", "place_order", signed=True)


def test_request_retries_retryable_http_status() -> None:
    session = FakeSession(
        [
            FakeResponse({"Message": "busy"}, status_code=500),
            FakeResponse({"Data": [{"Pair": "BTCUSD"}]}),
        ]
    )
    client = RoostooClient(session=session)

    payload = client._request_json("GET", "exchange_info")

    assert payload == {"Data": [{"Pair": "BTCUSD"}]}
    assert len(session.calls) == 2


def test_request_raises_for_unsuccessful_api_payload() -> None:
    session = FakeSession([FakeResponse({"Success": False, "Message": "denied"})])
    client = RoostooClient(session=session)

    with pytest.raises(ApiError, match="denied"):
        client._request_json("GET", "ticker")


def test_request_raises_for_invalid_json_payload() -> None:
    session = FakeSession([FakeResponse(None, json_error=ValueError("bad json"))])
    client = RoostooClient(session=session)

    with pytest.raises(ApiError, match="Invalid JSON response"):
        client._request_json("GET", "ticker")

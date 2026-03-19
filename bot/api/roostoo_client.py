"""Roostoo API client primitives for the data-ingestion pipeline."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from dataclasses import field
import logging
from typing import Any

import requests
from tenacity import before_sleep_log
from tenacity import retry
from tenacity import retry_if_exception_type
from tenacity import stop_after_attempt
from tenacity import wait_exponential

from .auth import AuthCredentials
from .auth import build_auth_headers
from .auth import current_timestamp_ms


DEFAULT_BASE_URL = "https://mock-api.roostoo.com"
DEFAULT_ENDPOINTS = {
    "balance": "/v3/balance",
    "cancel_order": "/v3/cancel_order",
    "exchange_info": "/v3/exchangeInfo",
    "pending_count": "/v3/pending_count",
    "place_order": "/v3/place_order",
    "query_order": "/v3/query_order",
    "server_time": "/v3/serverTime",
    "ticker": "/v3/ticker",
}

LOGGER = logging.getLogger("tradingbot.system")


class ApiError(RuntimeError):
    """Raised when the Roostoo API returns an invalid response."""


class TransientRequestError(RuntimeError):
    """Raised for retryable transport or server-side failures."""


@dataclass(slots=True)
class RoostooClient:
    """HTTP client for Roostoo market-data endpoints."""

    base_url: str = DEFAULT_BASE_URL
    credentials: AuthCredentials | None = None
    timeout_seconds: float = 10.0
    session: requests.Session | Any = field(default_factory=requests.Session)
    clock_offset_ms: int = 0

    def __post_init__(self) -> None:
        self.base_url = self.base_url.rstrip("/")

    def available_endpoints(self) -> dict[str, str]:
        """Return the configured endpoint map."""
        return dict(DEFAULT_ENDPOINTS)

    def endpoint_url(self, endpoint_name: str) -> str:
        """Return the fully-qualified URL for a configured endpoint."""
        path = DEFAULT_ENDPOINTS[endpoint_name]
        return f"{self.base_url}{path}"

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=1, max=8),
        retry=retry_if_exception_type(
            (requests.ConnectionError, requests.Timeout, TransientRequestError)
        ),
        before_sleep=before_sleep_log(LOGGER, logging.WARNING),
        reraise=True,
    )
    def _request_json(
        self,
        method: str,
        endpoint_name: str,
        *,
        params: Mapping[str, Any] | None = None,
        data: Mapping[str, Any] | None = None,
        signed: bool = False,
    ) -> Any:
        request_params = dict(params or {})
        headers: dict[str, str] = {}

        if signed:
            if self.credentials is None:
                raise ApiError("Signed endpoint requested without API credentials.")
            headers.update(build_auth_headers(self.credentials, request_params | dict(data or {})))

        if method.upper() == "POST":
            headers["Content-Type"] = "application/x-www-form-urlencoded"

        response = self.session.request(
            method=method.upper(),
            url=self.endpoint_url(endpoint_name),
            params=request_params or None,
            data=dict(data or {}) or None,
            headers=headers or None,
            timeout=self.timeout_seconds,
        )

        if response.status_code == 429 or response.status_code >= 500:
            raise TransientRequestError(
                f"Retryable HTTP status {response.status_code} from {endpoint_name}"
            )

        response.raise_for_status()

        try:
            payload = response.json()
        except ValueError as exc:
            raise ApiError(f"Invalid JSON response from {endpoint_name}") from exc

        if isinstance(payload, dict) and payload.get("Success") is False:
            message = payload.get("Message") or payload.get("message") or "Unknown API error"
            raise ApiError(message)

        return payload

    def sync_server_time(self) -> int:
        """Refresh the local clock offset against the Roostoo server."""
        started_at_ms = current_timestamp_ms()
        payload = self._request_json("GET", "server_time")
        finished_at_ms = current_timestamp_ms()
        server_time_ms = self._extract_server_time(payload)
        local_midpoint_ms = (started_at_ms + finished_at_ms) // 2
        self.clock_offset_ms = server_time_ms - local_midpoint_ms
        return server_time_ms

    def get_server_time(self) -> int:
        """Return the current server time without mutating the local clock offset."""
        payload = self._request_json("GET", "server_time")
        return self._extract_server_time(payload)

    def get_exchange_info(self) -> list[dict[str, Any]]:
        """Return the normalized exchange info records."""
        payload = self._request_json("GET", "exchange_info")
        return self._extract_records(payload)

    def get_ticker(self, pair: str | None = None) -> list[dict[str, Any]]:
        """Return the normalized ticker records for one pair or the full universe."""
        params: dict[str, Any] = {
            "timestamp": current_timestamp_ms(clock_offset_ms=self.clock_offset_ms),
        }
        if pair:
            params["pair"] = pair
        payload = self._request_json("GET", "ticker", params=params)
        return self._extract_records(payload)

    def get_balance(self) -> dict[str, Any]:
        """Return the current account balances from the signed balance endpoint."""
        payload = self._request_json(
            "GET",
            "balance",
            params=self._signed_payload(),
            signed=True,
        )
        data = self._unwrap_payload(payload)
        if isinstance(data, Mapping):
            return dict(data)
        raise ApiError("Unable to parse balance response.")

    def get_pending_count(self, pair: str | None = None) -> Any:
        """Return the pending-order count payload from the signed endpoint."""
        params = self._signed_payload({"pair": pair} if pair else None)
        payload = self._request_json(
            "GET",
            "pending_count",
            params=params,
            signed=True,
        )
        return self._unwrap_payload(payload)

    def place_order(
        self,
        *,
        pair: str,
        side: str,
        order_type: str,
        quantity: float,
        price: float | None = None,
    ) -> Any:
        """Place a signed order via the Roostoo API."""
        data = self._signed_payload(
            {
                "pair": pair,
                "side": side,
                "type": order_type,
                "quantity": quantity,
                "price": price,
            }
        )
        return self._request_json("POST", "place_order", data=data, signed=True)

    def query_order(
        self,
        *,
        order_id: int | None = None,
        pair: str | None = None,
        pending_only: bool | None = None,
    ) -> Any:
        """Query signed order history or pending orders."""
        data = self._signed_payload(
            {
                "order_id": order_id,
                "pair": pair,
                "pending_only": pending_only,
            }
        )
        return self._request_json("POST", "query_order", data=data, signed=True)

    def cancel_order(
        self,
        *,
        order_id: int | None = None,
        pair: str | None = None,
        cancel_all: bool | None = None,
    ) -> Any:
        """Cancel one or more pending orders via the signed endpoint."""
        data = self._signed_payload(
            {
                "order_id": order_id,
                "pair": pair,
                "cancel_all": cancel_all,
            }
        )
        return self._request_json("POST", "cancel_order", data=data, signed=True)

    def _extract_server_time(self, payload: Any) -> int:
        data = self._unwrap_payload(payload)
        if isinstance(data, Mapping):
            for key in ("serverTime", "ServerTime", "timestamp", "Timestamp", "time", "Time"):
                if key in data:
                    return int(data[key])
        if isinstance(data, (int, float, str)):
            return int(data)
        raise ApiError("Unable to parse server time response.")

    def _extract_records(self, payload: Any) -> list[dict[str, Any]]:
        data = self._unwrap_payload(payload)

        if data is None:
            return []

        if isinstance(data, list):
            return [dict(item) for item in data if isinstance(item, Mapping)]

        if isinstance(data, Mapping):
            for key in ("symbols", "Symbols", "pairs", "Pairs", "tickers", "Tickers"):
                value = data.get(key)
                if isinstance(value, list):
                    return [dict(item) for item in value if isinstance(item, Mapping)]

            records: list[dict[str, Any]] = []
            for symbol, value in data.items():
                if not isinstance(value, Mapping):
                    continue
                record = dict(value)
                if not any(field in record for field in ("Pair", "pair", "symbol", "Symbol")):
                    record["symbol"] = symbol
                records.append(record)
            if records:
                return records

            return [dict(data)]

        raise ApiError("Unable to normalize API response records.")

    @staticmethod
    def _unwrap_payload(payload: Any) -> Any:
        if isinstance(payload, Mapping):
            for key in ("Data", "data", "Result", "result"):
                if key in payload:
                    return payload[key]
        return payload

    def _signed_payload(self, extra_fields: Mapping[str, Any] | None = None) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "timestamp": current_timestamp_ms(clock_offset_ms=self.clock_offset_ms),
        }
        if extra_fields:
            payload.update(extra_fields)
        return payload

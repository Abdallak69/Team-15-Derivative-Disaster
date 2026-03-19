"""Import-safe baseline client wrapper for Roostoo API endpoints."""

from __future__ import annotations

from dataclasses import dataclass


DEFAULT_BASE_URL = "https://api.roostoo.com"
DEFAULT_ENDPOINTS = {
    "account_balance": "/v3/account/balance",
    "cancel_order": "/v3/order/cancel",
    "exchange_info": "/v3/exchangeInfo",
    "open_orders": "/v3/openOrders",
    "order_detail": "/v3/order",
    "place_order": "/v3/order",
    "server_time": "/v3/serverTime",
    "ticker": "/v3/ticker",
}


@dataclass(slots=True)
class RoostooClient:
    """Small endpoint registry until the HTTP client is implemented."""

    base_url: str = DEFAULT_BASE_URL

    def available_endpoints(self) -> dict[str, str]:
        """Return the configured endpoint map."""
        return dict(DEFAULT_ENDPOINTS)

    def endpoint_url(self, endpoint_name: str) -> str:
        """Return the fully-qualified URL for a configured endpoint."""
        path = DEFAULT_ENDPOINTS[endpoint_name]
        return f"{self.base_url.rstrip('/')}{path}"


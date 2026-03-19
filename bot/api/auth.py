"""Authentication utilities for Roostoo API requests."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
import hashlib
import hmac
import os
import time
from typing import Any


API_KEY_HEADER = "RST-API-KEY"
SIGNATURE_HEADER = "MSG-SIGNATURE"


@dataclass(frozen=True, slots=True)
class AuthCredentials:
    """Container for API credential values."""

    api_key: str
    secret_key: str

    @classmethod
    def from_env(cls) -> AuthCredentials | None:
        """Build credentials from environment variables when available."""
        api_key = os.getenv("ROOSTOO_API_KEY")
        secret_key = os.getenv("ROOSTOO_SECRET_KEY")
        if not api_key or not secret_key:
            return None
        return cls(api_key=api_key, secret_key=secret_key)


def current_timestamp_ms(clock_offset_ms: int = 0) -> int:
    """Return the current Unix timestamp in milliseconds."""
    return int(time.time() * 1000) + clock_offset_ms


def _stringify_param_value(value: Any) -> str:
    if isinstance(value, bool):
        return str(value).lower()
    return str(value)


def build_signature_payload(
    params: Mapping[str, Any],
) -> str:
    """Construct an alphabetically sorted key=value payload for signing."""
    filtered_items = [
        (key, _stringify_param_value(value))
        for key, value in params.items()
        if value is not None
    ]
    filtered_items.sort(key=lambda item: item[0])
    return "&".join(f"{key}={value}" for key, value in filtered_items)


def sign_request(secret_key: str, payload: str) -> str:
    """Return the HMAC SHA256 digest for the supplied payload."""
    return hmac.new(
        secret_key.encode("utf-8"),
        payload.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()


def build_auth_headers(
    credentials: AuthCredentials,
    params: Mapping[str, Any],
) -> dict[str, str]:
    """Return API key and signature headers for signed endpoints."""
    payload = build_signature_payload(params)
    return {
        API_KEY_HEADER: credentials.api_key,
        SIGNATURE_HEADER: sign_request(credentials.secret_key, payload),
    }

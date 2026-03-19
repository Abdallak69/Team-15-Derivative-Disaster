"""Authentication utilities for signed API requests."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import hmac


@dataclass(frozen=True, slots=True)
class AuthCredentials:
    """Container for API credential values."""

    api_key: str
    secret_key: str


def build_signature_payload(
    timestamp_ms: int,
    method: str,
    path: str,
    body: str = "",
) -> str:
    """Construct a deterministic request-signing payload."""
    return f"{timestamp_ms}{method.upper()}{path}{body}"


def sign_request(secret_key: str, payload: str) -> str:
    """Return the HMAC SHA256 digest for the supplied payload."""
    return hmac.new(
        secret_key.encode("utf-8"),
        payload.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()


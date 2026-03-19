"""Pytest coverage for request signing and secret loading."""

from __future__ import annotations

import pytest

from bot.api.auth import API_KEY_HEADER
from bot.api.auth import SIGNATURE_HEADER
from bot.api.auth import AuthCredentials
from bot.api.auth import build_auth_headers
from bot.api.auth import build_signature_payload
from bot.api.auth import sign_request
from bot.environment import SecretConfigurationError


def test_hmac_signature_matches_documented_example() -> None:
    secret = "S1XP1e3UZj6A7H5fATj0jNhqPxxdSJYdInClVN65XAbvqqMKjVHjA7PZj4W12oep"
    params = "pair=BNB/USD&quantity=2000&side=BUY&timestamp=1580774512000&type=MARKET"
    expected = "20b7fd5550b67b3bf0c1684ed0f04885261db8fdabd38611e9e6af23c19b7fff"

    assert sign_request(secret, params) == expected


def test_signature_payload_is_sorted_filters_none_and_normalizes_bools() -> None:
    payload = build_signature_payload(
        {
            "timestamp": 1710800000000,
            "pair": "BTCUSD",
            "postOnly": True,
            "ignored": None,
        }
    )

    assert payload == "pair=BTCUSD&postOnly=true&timestamp=1710800000000"


def test_build_auth_headers_includes_api_key_and_signature() -> None:
    credentials = AuthCredentials(api_key="api-key", secret_key="secret")

    headers = build_auth_headers(
        credentials,
        {"pair": "BTCUSD", "timestamp": 1710800000000},
    )

    assert headers[API_KEY_HEADER] == "api-key"
    assert SIGNATURE_HEADER in headers


def test_credentials_from_env_reject_partial_secret_configuration(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("ROOSTOO_API_KEY", raising=False)
    monkeypatch.setenv("ROOSTOO_SECRET_KEY", "real-secret")

    with pytest.raises(SecretConfigurationError, match="ROOSTOO_API_KEY"):
        AuthCredentials.from_env()


def test_credentials_from_env_requires_real_values(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("ROOSTOO_API_KEY", "replace_me")
    monkeypatch.setenv("ROOSTOO_SECRET_KEY", "replace_me")

    assert AuthCredentials.from_env() is None

    with pytest.raises(SecretConfigurationError, match="must be set in .env"):
        AuthCredentials.from_env(required=True)

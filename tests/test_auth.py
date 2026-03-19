"""Tests for baseline request-signing helpers."""

from __future__ import annotations

import unittest

from bot.api.auth import API_KEY_HEADER
from bot.api.auth import SIGNATURE_HEADER
from bot.api.auth import AuthCredentials
from bot.api.auth import build_auth_headers
from bot.api.auth import build_signature_payload
from bot.api.auth import sign_request


class AuthTests(unittest.TestCase):
    def test_signature_payload_is_sorted_and_filters_none(self) -> None:
        payload = build_signature_payload(
            {
                "timestamp": 1710800000000,
                "pair": "BTCUSD",
                "ignored": None,
            }
        )
        self.assertEqual(payload, "pair=BTCUSD&timestamp=1710800000000")

    def test_signature_has_expected_shape(self) -> None:
        signature = sign_request("secret", "payload")
        self.assertRegex(signature, r"^[0-9a-f]{64}$")

    def test_build_auth_headers_includes_api_key_and_signature(self) -> None:
        credentials = AuthCredentials(api_key="api-key", secret_key="secret")
        headers = build_auth_headers(
            credentials,
            {"pair": "BTCUSD", "timestamp": 1710800000000},
        )

        self.assertEqual(headers[API_KEY_HEADER], "api-key")
        self.assertIn(SIGNATURE_HEADER, headers)

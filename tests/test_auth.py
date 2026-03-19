"""Tests for baseline request-signing helpers."""

from __future__ import annotations

import unittest

from bot.api.auth import build_signature_payload, sign_request


class AuthTests(unittest.TestCase):
    def test_signature_payload_is_deterministic(self) -> None:
        payload = build_signature_payload(1710800000000, "get", "/v3/ticker")
        self.assertEqual(payload, "1710800000000GET/v3/ticker")

    def test_signature_has_expected_shape(self) -> None:
        signature = sign_request("secret", "payload")
        self.assertRegex(signature, r"^[0-9a-f]{64}$")


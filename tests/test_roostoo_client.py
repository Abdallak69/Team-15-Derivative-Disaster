"""Tests for the baseline Roostoo client scaffold."""

from __future__ import annotations

import unittest

from bot.api.roostoo_client import RoostooClient


class RoostooClientTests(unittest.TestCase):
    def test_endpoint_registry_contains_expected_urls(self) -> None:
        client = RoostooClient()

        self.assertIn("ticker", client.available_endpoints())
        self.assertEqual(client.endpoint_url("ticker"), "https://api.roostoo.com/v3/ticker")


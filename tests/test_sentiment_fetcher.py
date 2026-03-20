"""Tests for the sentiment fetcher module."""

from __future__ import annotations

import json
import unittest
from dataclasses import dataclass

from bot.data.sentiment_fetcher import (
    SentimentFetcher,
    SentimentSnapshot,
    compute_deployment_multiplier,
)


class DeploymentMultiplierTests(unittest.TestCase):
    def test_extreme_fear_returns_high_multiplier(self) -> None:
        self.assertAlmostEqual(compute_deployment_multiplier(10), 1.30)

    def test_fear_returns_moderate_multiplier(self) -> None:
        self.assertAlmostEqual(compute_deployment_multiplier(30), 1.15)

    def test_neutral_returns_unity(self) -> None:
        self.assertAlmostEqual(compute_deployment_multiplier(50), 1.00)

    def test_greed_returns_low_multiplier(self) -> None:
        self.assertAlmostEqual(compute_deployment_multiplier(76), 0.85)

    def test_extreme_greed_returns_lowest_multiplier(self) -> None:
        self.assertAlmostEqual(compute_deployment_multiplier(90), 0.70)

    def test_boundary_at_fear_threshold(self) -> None:
        self.assertAlmostEqual(compute_deployment_multiplier(25), 1.15)
        self.assertAlmostEqual(compute_deployment_multiplier(24), 1.30)

    def test_boundary_at_greed_threshold(self) -> None:
        self.assertAlmostEqual(compute_deployment_multiplier(75), 1.00)
        self.assertAlmostEqual(compute_deployment_multiplier(76), 0.85)


@dataclass
class FakeSentimentResponse:
    status_code: int = 200

    def json(self) -> dict:
        return {
            "name": "Fear and Greed Index",
            "data": [
                {
                    "value": "22",
                    "value_classification": "Extreme Fear",
                    "timestamp": "1711000000",
                }
            ],
        }

    def raise_for_status(self) -> None:
        pass


@dataclass
class FakeSentimentSession:
    def get(self, url: str, **kwargs) -> FakeSentimentResponse:
        return FakeSentimentResponse()


class SentimentFetcherTests(unittest.TestCase):
    def test_fetch_fear_and_greed_parses_response(self) -> None:
        fetcher = SentimentFetcher(session=FakeSentimentSession())
        snapshot = fetcher.fetch_fear_and_greed()

        self.assertIsInstance(snapshot, SentimentSnapshot)
        self.assertEqual(snapshot.fgi_value, 22)
        self.assertEqual(snapshot.fgi_classification, "Extreme Fear")
        self.assertAlmostEqual(snapshot.deployment_multiplier, 1.30)

    def test_fear_and_greed_url_construction(self) -> None:
        fetcher = SentimentFetcher(base_url="https://api.example.com")
        self.assertEqual(fetcher.fear_and_greed_url(), "https://api.example.com/fng/")

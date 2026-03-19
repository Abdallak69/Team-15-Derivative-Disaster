"""Sentiment data endpoint helpers."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(slots=True)
class SentimentFetcher:
    """Minimal endpoint builder for sentiment data sources."""

    base_url: str = "https://api.alternative.me"

    def fear_and_greed_url(self) -> str:
        """Return the baseline Fear and Greed endpoint URL."""
        return f"{self.base_url.rstrip('/')}/fng/"


"""Sentiment data fetching — Fear & Greed Index and deployment multiplier."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

import requests
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

logger = logging.getLogger("tradingbot.signals")


@dataclass(frozen=True, slots=True)
class SentimentSnapshot:
    """Point-in-time sentiment reading."""

    fgi_value: int
    fgi_classification: str
    deployment_multiplier: float


def compute_deployment_multiplier(
    fgi_value: int,
    *,
    extreme_fear: int = 25,
    fear: int = 35,
    greed: int = 75,
    extreme_greed: int = 80,
    mult_extreme_fear: float = 1.30,
    mult_fear: float = 1.15,
    mult_greed: float = 0.85,
    mult_extreme_greed: float = 0.70,
) -> float:
    """Map Fear & Greed Index value to a deployment multiplier.

    Thresholds: <25 extreme fear, 25-34 fear, 35-75 neutral, 76-80 greed, >80 extreme greed.
    """
    if fgi_value < extreme_fear:
        return mult_extreme_fear
    if fgi_value < fear:
        return mult_fear
    if fgi_value <= greed:
        return 1.0
    if fgi_value <= extreme_greed:
        return mult_greed
    return mult_extreme_greed


class TransientSentimentError(Exception):
    """Raised for retryable sentiment fetch failures."""


@dataclass(slots=True)
class SentimentFetcher:
    """Fetches Fear & Greed Index from Alternative.me and computes deployment multipliers."""

    base_url: str = "https://api.alternative.me"
    timeout_seconds: float = 10.0
    session: Any = field(default_factory=requests.Session)

    extreme_fear: int = 25
    fear: int = 35
    greed: int = 75
    extreme_greed: int = 80
    mult_extreme_fear: float = 1.30
    mult_fear: float = 1.15
    mult_greed: float = 0.85
    mult_extreme_greed: float = 0.70

    def fear_and_greed_url(self) -> str:
        """Return the baseline Fear and Greed endpoint URL."""
        return f"{self.base_url.rstrip('/')}/fng/"

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=30),
        retry=retry_if_exception_type(
            (requests.ConnectionError, requests.Timeout, TransientSentimentError)
        ),
        before_sleep=lambda rs: logger.warning(
            "Sentiment fetch retry #%d: %s", rs.attempt_number, rs.outcome.exception()
        ),
    )
    def fetch_fear_and_greed(self) -> SentimentSnapshot:
        """Fetch the latest Fear & Greed Index value and return a snapshot."""
        url = self.fear_and_greed_url()
        response = self.session.get(url, timeout=self.timeout_seconds)

        status = getattr(response, "status_code", 200)
        if status in (429, 500, 502, 503, 504):
            raise TransientSentimentError(f"Retryable HTTP status {status}")
        response.raise_for_status()

        payload = response.json()
        data_list = payload.get("data")
        if not data_list or not isinstance(data_list, list):
            raise ValueError("Unexpected F&G response: missing 'data' list")

        entry = data_list[0]
        fgi_value = int(entry["value"])
        fgi_class = str(entry.get("value_classification", "Unknown"))

        multiplier = compute_deployment_multiplier(
            fgi_value,
            extreme_fear=self.extreme_fear,
            fear=self.fear,
            greed=self.greed,
            extreme_greed=self.extreme_greed,
            mult_extreme_fear=self.mult_extreme_fear,
            mult_fear=self.mult_fear,
            mult_greed=self.mult_greed,
            mult_extreme_greed=self.mult_extreme_greed,
        )

        return SentimentSnapshot(
            fgi_value=fgi_value,
            fgi_classification=fgi_class,
            deployment_multiplier=multiplier,
        )

    def fetch_funding_rates(
        self,
        symbols: list[str],
        *,
        binance_futures_url: str = "https://fapi.binance.com",
    ) -> dict[str, float]:
        """Fetch latest Binance perpetual funding rates (public, no auth).

        Returns {symbol: last_funding_rate} for requested symbols.
        """
        try:
            response = self.session.get(
                f"{binance_futures_url}/fapi/v1/premiumIndex",
                timeout=self.timeout_seconds,
            )
            status = getattr(response, "status_code", 200)
            if status >= 400:
                logger.warning("Funding rate fetch returned status %d", status)
                return {}
            entries = response.json()
        except Exception:
            logger.warning("Funding rate fetch failed", exc_info=True)
            return {}

        if not isinstance(entries, list):
            return {}

        wanted = {s.upper() for s in symbols}
        rates: dict[str, float] = {}
        for entry in entries:
            sym = str(entry.get("symbol", ""))
            if sym in wanted:
                rate = entry.get("lastFundingRate")
                if rate is not None:
                    rates[sym] = float(rate)
        return rates

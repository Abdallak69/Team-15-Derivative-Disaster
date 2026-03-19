"""Telegram alert formatting helpers."""

from __future__ import annotations

from dataclasses import dataclass
from dataclasses import field
import logging
from typing import Any

import requests
from tenacity import before_sleep_log
from tenacity import retry
from tenacity import retry_if_exception_type
from tenacity import stop_after_attempt
from tenacity import wait_exponential


LOGGER = logging.getLogger("tradingbot.system")


class TelegramDeliveryError(RuntimeError):
    """Raised when Telegram message delivery fails."""


@dataclass(slots=True)
class TelegramAlerter:
    """Telegram formatter and delivery helper."""

    bot_token: str = ""
    chat_id: str = ""
    timeout_seconds: float = 10.0
    session: requests.Session | Any = field(default_factory=requests.Session)

    def format_message(self, title: str, body: str) -> str:
        """Return a single-line Telegram-friendly message."""
        return f"[{title}] {body}"

    def send_titled_message(self, title: str, body: str) -> dict[str, Any]:
        """Send a formatted title/body message to the configured Telegram chat."""
        return self.send_message(self.format_message(title, body))

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=1, max=8),
        retry=retry_if_exception_type(
            (requests.ConnectionError, requests.Timeout, TelegramDeliveryError)
        ),
        before_sleep=before_sleep_log(LOGGER, logging.WARNING),
        reraise=True,
    )
    def send_message(self, text: str) -> dict[str, Any]:
        """Deliver a message to Telegram using the Bot API."""
        if not self.bot_token or not self.chat_id:
            raise TelegramDeliveryError("Telegram bot token and chat ID are required.")

        response = self.session.post(
            self.api_url(),
            data={"chat_id": self.chat_id, "text": text},
            timeout=self.timeout_seconds,
        )

        if response.status_code == 429 or response.status_code >= 500:
            raise TelegramDeliveryError(
                f"Retryable Telegram status {response.status_code} while sending message."
            )

        response.raise_for_status()
        payload = response.json()
        if not isinstance(payload, dict) or payload.get("ok") is False:
            raise TelegramDeliveryError("Telegram returned an invalid response payload.")
        return payload

    def api_url(self) -> str:
        """Return the HTTPS endpoint for the configured Telegram bot."""
        return f"https://api.telegram.org/bot{self.bot_token}/sendMessage"

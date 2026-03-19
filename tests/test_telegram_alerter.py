"""Tests for Telegram alert formatting and delivery helpers."""

from __future__ import annotations

import pytest
import requests

from bot.monitoring.telegram_alerter import TelegramAlerter
from bot.monitoring.telegram_alerter import TelegramDeliveryError


class FakeResponse:
    def __init__(self, payload: object, status_code: int = 200) -> None:
        self.payload = payload
        self.status_code = status_code

    def json(self) -> object:
        return self.payload

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise requests.HTTPError(f"HTTP {self.status_code}")


class FakeSession:
    def __init__(self, responses: list[FakeResponse]) -> None:
        self.responses = responses
        self.calls: list[dict[str, object]] = []

    def post(self, url: str, **kwargs: object) -> FakeResponse:
        self.calls.append({"url": url, **kwargs})
        return self.responses.pop(0)


def test_format_message_returns_single_line_text() -> None:
    alerter = TelegramAlerter()

    assert alerter.format_message("Startup", "Bot ready") == "[Startup] Bot ready"


def test_send_message_posts_to_telegram_api() -> None:
    session = FakeSession([FakeResponse({"ok": True, "result": {"message_id": 1}})])
    alerter = TelegramAlerter(
        bot_token="bot-token",
        chat_id="chat-id",
        session=session,
    )

    payload = alerter.send_message("hello world")

    assert payload["ok"] is True
    assert session.calls[0]["url"] == "https://api.telegram.org/botbot-token/sendMessage"
    assert session.calls[0]["data"] == {"chat_id": "chat-id", "text": "hello world"}


def test_send_message_requires_credentials() -> None:
    alerter = TelegramAlerter()

    with pytest.raises(TelegramDeliveryError, match="required"):
        alerter.send_message("missing credentials")

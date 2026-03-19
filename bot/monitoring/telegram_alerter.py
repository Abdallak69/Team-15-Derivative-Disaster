"""Telegram alert formatting helpers."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(slots=True)
class TelegramAlerter:
    """Minimal formatter until the HTTP alert transport is implemented."""

    chat_id: str = ""

    def format_message(self, title: str, body: str) -> str:
        """Return a single-line Telegram-friendly message."""
        return f"[{title}] {body}"


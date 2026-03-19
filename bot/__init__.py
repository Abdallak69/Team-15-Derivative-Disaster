"""Core trading bot package."""

from __future__ import annotations

from typing import Any


__all__ = ["TradingBot"]


def __getattr__(name: str) -> Any:
    """Lazily expose package-level symbols without importing bot.main eagerly."""
    if name == "TradingBot":
        from .main import TradingBot

        return TradingBot
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")

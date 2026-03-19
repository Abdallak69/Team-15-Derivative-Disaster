"""Tests for baseline state persistence helpers."""

from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

from bot.main import TradingBot


class StatePersistenceTests(unittest.TestCase):
    def test_save_state_round_trips(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            state_path = Path(tmp_dir) / "bot_state.json"
            bot = TradingBot(
                config_path=Path(tmp_dir) / "strategy_params.yaml",
                state_path=state_path,
            )

            payload = {
                "environment": "testing",
                "paused": True,
                "portfolio_value": 1234.5,
                "positions": {"BTCUSD": 0.1},
            }

            bot.save_state(payload)

            self.assertEqual(bot.load_state(), payload)

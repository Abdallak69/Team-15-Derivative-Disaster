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
                db_path=Path(tmp_dir) / "live_ohlcv.db",
            )

            payload = {
                "clock_offset_ms": 0,
                "db_path": str(Path(tmp_dir) / "live_ohlcv.db"),
                "environment": "testing",
                "last_poll_at": None,
                "last_snapshot_count": 0,
                "last_stored_snapshot_count": 0,
                "paused": True,
                "portfolio_value": 1234.5,
                "positions": {"BTCUSD": 0.1},
                "universe": ["BTCUSD"],
                "universe_size": 1,
            }

            bot.save_state(payload)

            self.assertEqual(bot.load_state(), payload)

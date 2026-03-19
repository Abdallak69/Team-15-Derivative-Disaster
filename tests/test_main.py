"""Baseline tests for the TradingBot entrypoint."""

from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

from bot.main import TradingBot


class TradingBotTests(unittest.TestCase):
    def test_status_exposes_expected_fields(self) -> None:
        bot = TradingBot()
        status = bot.status()

        self.assertEqual(status["environment"], bot.environment)
        self.assertFalse(status["is_running"])
        self.assertTrue(status["config_path"].endswith("config/strategy_params.yaml"))

    def test_bootstrap_state_creates_state_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            state_path = Path(tmp_dir) / "bot_state.json"
            bot = TradingBot(
                config_path=Path(tmp_dir) / "strategy_params.yaml",
                state_path=state_path,
            )

            created_path = bot.bootstrap_state()

            self.assertEqual(created_path, state_path)
            self.assertTrue(state_path.exists())


"""Baseline tests for the TradingBot entrypoint."""

from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

from bot.main import _build_cli_parser
from bot.main import TradingBot


class StubRoostooClient:
    def __init__(self) -> None:
        self.clock_offset_ms = 0

    def sync_server_time(self) -> int:
        self.clock_offset_ms = 250
        return 1710800000000

    def get_exchange_info(self) -> list[dict[str, object]]:
        return [
            {"Pair": "BTCUSD", "Status": "TRADING"},
            {"Pair": "ETHUSD", "Status": "TRADING"},
        ]

    def get_ticker(self) -> list[dict[str, str]]:
        return [
            {"Pair": "BTCUSD", "LastPrice": "101.0", "MaxBid": "100.9"},
            {"Pair": "ETHUSD", "LastPrice": "55.0", "MaxBid": "54.9"},
        ]


class TradingBotTests(unittest.TestCase):
    def test_status_exposes_expected_fields(self) -> None:
        bot = TradingBot()
        status = bot.status()

        self.assertEqual(status["environment"], bot.environment)
        self.assertFalse(status["is_running"])
        self.assertFalse(status["is_bootstrapped"])
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

    def test_run_poll_cycle_bootstraps_and_persists_pipeline_state(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            bot = TradingBot(
                state_path=Path(tmp_dir) / "bot_state.json",
                db_path=Path(tmp_dir) / "live_ohlcv.db",
                client=StubRoostooClient(),
            )

            result = bot.run_poll_cycle()
            state = bot.load_state()

        self.assertTrue(bot.is_bootstrapped)
        self.assertEqual(result["snapshot_count"], 2)
        self.assertEqual(state["universe_size"], 2)
        self.assertEqual(state["last_stored_snapshot_count"], 2)

    def test_startup_check_runs_bootstrap_and_stops(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            bot = TradingBot(
                state_path=Path(tmp_dir) / "bot_state.json",
                db_path=Path(tmp_dir) / "live_ohlcv.db",
                client=StubRoostooClient(),
            )

            status = bot.startup_check()

        self.assertTrue(status["is_bootstrapped"])
        self.assertFalse(status["is_running"])
        self.assertFalse(bot.is_running)


class MainCliTests(unittest.TestCase):
    def test_status_flag_prints_status_without_running_forever(self) -> None:
        parser = _build_cli_parser()
        args = parser.parse_args(["--status"])

        self.assertTrue(args.status)
        self.assertFalse(args.startup_check)

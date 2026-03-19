"""Baseline tests for the TradingBot entrypoint."""

from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

from bot.main import _build_cli_parser
from bot.main import TradingBot


def _write_strategy_config(path: Path) -> None:
    path.write_text(
        "\n".join(
            [
                "api:",
                "  base_url: https://mock-api.roostoo.com",
                "  timeout_seconds: 10.0",
                "runtime:",
                "  environment: testing",
                "  poll_interval_seconds: 60",
                "  trading_cycle_interval_seconds: 300",
                "  heartbeat_interval_seconds: 3600",
                "  clock_sync_interval_seconds: 3600",
                "regime:",
                "  ema_fast_period: 20",
                "  ema_slow_period: 50",
                "  volatility_lookback: 14",
                "  volatility_threshold_multiplier: 1.5",
                "  confirmation_periods: 2",
                "momentum:",
                "  lookback_days: [3, 5, 7]",
                "  rsi_threshold: 45",
                "  macd_fast: 12",
                "  macd_slow: 26",
                "  macd_signal: 9",
                "  top_n_assets: 8",
                "mean_reversion:",
                "  rsi_oversold: 30",
                "  bollinger_period: 20",
                "  bollinger_std: 2.0",
                "  min_volume_usd: 10000000",
                "  max_hold_days: 3",
                "  stop_loss_pct: 0.05",
                "risk:",
                "  max_position_pct: 0.10",
                "  cash_floor_bull: 0.20",
                "  cash_floor_ranging: 0.40",
                "  cash_floor_bear: 0.50",
                "  stop_loss_pct: 0.03",
                "  circuit_breaker_l1: 0.03",
                "  circuit_breaker_l2: 0.05",
                "  daily_loss_limit: 0.02",
                "execution:",
                "  prefer_limit_orders: true",
                "  limit_offset_pct: 0.0001",
                "  min_rebalance_drift: 0.15",
                "  order_spacing_seconds: 65",
                "",
            ]
        ),
        encoding="utf-8",
    )


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

    def get_balance(self) -> dict[str, object]:
        return {
            "Data": {
                "portfolioValue": "1000000.0",
                "balances": [
                    {
                        "asset": "BTCUSD",
                        "quantity": "0.1",
                        "usdValue": "6000.0",
                    }
                ],
            }
        }

    def query_order(self, *, pending_only: bool | None = None) -> dict[str, object]:
        return {
            "Data": {
                "orders": [
                    {
                        "order_id": 123,
                        "pair": "BTCUSD",
                        "status": "NEW",
                        "pending_only": pending_only,
                    }
                ]
            }
        }


class StubAlerter:
    def __init__(self) -> None:
        self.messages: list[tuple[str, str]] = []

    def send_titled_message(self, title: str, body: str) -> dict[str, object]:
        self.messages.append((title, body))
        return {"ok": True}


class TradingBotTests(unittest.TestCase):
    def test_status_exposes_expected_fields(self) -> None:
        bot = TradingBot()
        status = bot.status()

        self.assertEqual(status["environment"], bot.environment)
        self.assertFalse(status["is_running"])
        self.assertFalse(status["is_bootstrapped"])
        self.assertTrue(status["config_path"].endswith("config/strategy_params.yaml"))
        self.assertIn("last_reconciled_at", status)
        self.assertIn("pending_order_count", status)
        self.assertIn("trading_cycle_interval_seconds", status)
        self.assertIn("heartbeat_interval_seconds", status)

    def test_bootstrap_state_creates_state_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            config_path = Path(tmp_dir) / "strategy_params.yaml"
            state_path = Path(tmp_dir) / "bot_state.json"
            _write_strategy_config(config_path)
            bot = TradingBot(
                config_path=config_path,
                state_path=state_path,
            )

            created_path = bot.bootstrap_state()

            self.assertEqual(created_path, state_path)
            self.assertTrue(state_path.exists())

    def test_run_poll_cycle_bootstraps_and_persists_pipeline_state(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            config_path = Path(tmp_dir) / "strategy_params.yaml"
            _write_strategy_config(config_path)
            bot = TradingBot(
                config_path=config_path,
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
        self.assertEqual(state["portfolio_value"], 1000000.0)
        self.assertEqual(state["pending_order_count"], 1)
        self.assertEqual(state["positions"], {"BTCUSD": 0.1})
        self.assertIsNotNone(state["last_reconciled_at"])

    def test_startup_check_runs_bootstrap_and_stops(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            config_path = Path(tmp_dir) / "strategy_params.yaml"
            _write_strategy_config(config_path)
            bot = TradingBot(
                config_path=config_path,
                state_path=Path(tmp_dir) / "bot_state.json",
                db_path=Path(tmp_dir) / "live_ohlcv.db",
                client=StubRoostooClient(),
            )

            status = bot.startup_check()

        self.assertTrue(status["is_bootstrapped"])
        self.assertFalse(status["is_running"])
        self.assertFalse(bot.is_running)

    def test_startup_check_sends_startup_alert_when_telegram_is_configured(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            config_path = Path(tmp_dir) / "strategy_params.yaml"
            _write_strategy_config(config_path)
            alerter = StubAlerter()
            bot = TradingBot(
                config_path=config_path,
                state_path=Path(tmp_dir) / "bot_state.json",
                db_path=Path(tmp_dir) / "live_ohlcv.db",
                client=StubRoostooClient(),
                alerter=alerter,
            )

            status = bot.startup_check()

        self.assertTrue(status["telegram_configured"])
        self.assertEqual(alerter.messages[0][0], "Bot Started")
        self.assertIn("portfolio_value=1000000.0", alerter.messages[0][1])

    def test_send_heartbeat_updates_state_when_delivered(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            config_path = Path(tmp_dir) / "strategy_params.yaml"
            _write_strategy_config(config_path)
            alerter = StubAlerter()
            bot = TradingBot(
                config_path=config_path,
                state_path=Path(tmp_dir) / "bot_state.json",
                db_path=Path(tmp_dir) / "live_ohlcv.db",
                client=StubRoostooClient(),
                alerter=alerter,
            )
            bot.bootstrap()

            heartbeat = bot.send_heartbeat()
            state = bot.load_state()

        self.assertIsNotNone(heartbeat["last_heartbeat_at"])
        self.assertEqual(state["last_heartbeat_at"], heartbeat["last_heartbeat_at"])
        self.assertEqual(alerter.messages[-1][0], "Heartbeat")
        self.assertIn("pending_orders=1", alerter.messages[-1][1])


class MainCliTests(unittest.TestCase):
    def test_status_flag_prints_status_without_running_forever(self) -> None:
        parser = _build_cli_parser()
        args = parser.parse_args(["--status"])

        self.assertTrue(args.status)
        self.assertFalse(args.startup_check)

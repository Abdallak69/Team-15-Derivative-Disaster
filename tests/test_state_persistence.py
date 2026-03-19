"""Tests for baseline state persistence helpers."""

from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

from bot.main import TradingBot


def _write_strategy_config(path: Path, *, strategy_mode: str = "disabled") -> None:
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
                f"  strategy_mode: {strategy_mode}",
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


class StatePersistenceTests(unittest.TestCase):
    def test_save_state_round_trips(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            config_path = Path(tmp_dir) / "strategy_params.yaml"
            _write_strategy_config(config_path)
            state_path = Path(tmp_dir) / "bot_state.json"
            bot = TradingBot(
                config_path=config_path,
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

    def test_load_state_quarantines_corrupt_json_and_restores_defaults(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            config_path = Path(tmp_dir) / "strategy_params.yaml"
            _write_strategy_config(config_path, strategy_mode="paper")
            state_path = Path(tmp_dir) / "bot_state.json"
            state_path.write_text("{invalid json", encoding="utf-8")
            bot = TradingBot(
                config_path=config_path,
                state_path=state_path,
                db_path=Path(tmp_dir) / "live_ohlcv.db",
            )

            state = bot.load_state()
            quarantined_paths = sorted(Path(tmp_dir).glob("bot_state.corrupt-*.json"))

        self.assertEqual(state["environment"], "testing")
        self.assertEqual(state["strategy_mode"], "paper")
        self.assertEqual(state["strategy_cycle_status"], "pending")
        self.assertFalse(state_path.exists())
        self.assertEqual(len(quarantined_paths), 1)

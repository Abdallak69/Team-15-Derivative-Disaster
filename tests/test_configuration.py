"""Tests for semantic YAML configuration validation."""

from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

from bot.configuration import ConfigError
from bot.configuration import load_yaml_config


def _base_config_text(*, strategy_mode: str = "disabled") -> str:
    return "\n".join(
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
    )


class ConfigurationTests(unittest.TestCase):
    def test_load_yaml_config_accepts_valid_strategy_mode(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            config_path = Path(tmp_dir) / "strategy_params.yaml"
            config_path.write_text(_base_config_text(strategy_mode="paper"), encoding="utf-8")

            config = load_yaml_config(config_path)

        self.assertEqual(config["runtime"]["strategy_mode"], "paper")

    def test_load_yaml_config_rejects_invalid_strategy_mode(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            config_path = Path(tmp_dir) / "strategy_params.yaml"
            config_path.write_text(_base_config_text(strategy_mode="shadow"), encoding="utf-8")

            with self.assertRaisesRegex(ConfigError, "runtime.strategy_mode"):
                load_yaml_config(config_path)

    def test_load_yaml_config_rejects_inverted_circuit_breakers(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            config_path = Path(tmp_dir) / "strategy_params.yaml"
            config_path.write_text(
                _base_config_text().replace(
                    "  circuit_breaker_l2: 0.05",
                    "  circuit_breaker_l2: 0.02",
                ),
                encoding="utf-8",
            )

            with self.assertRaisesRegex(ConfigError, "circuit_breaker_l2 must exceed"):
                load_yaml_config(config_path)

    def test_load_yaml_config_rejects_non_positive_runtime_interval(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            config_path = Path(tmp_dir) / "strategy_params.yaml"
            config_path.write_text(
                _base_config_text().replace(
                    "  trading_cycle_interval_seconds: 300",
                    "  trading_cycle_interval_seconds: 0",
                ),
                encoding="utf-8",
            )

            with self.assertRaisesRegex(ConfigError, "runtime.trading_cycle_interval_seconds"):
                load_yaml_config(config_path)


if __name__ == "__main__":
    unittest.main()

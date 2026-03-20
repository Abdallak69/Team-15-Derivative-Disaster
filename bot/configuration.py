"""YAML-backed runtime and strategy configuration helpers."""

from __future__ import annotations

from collections.abc import Mapping
from numbers import Real
from pathlib import Path
import re
from typing import Any

import yaml


CONFIG_KEY_PATTERN = re.compile(r"^[a-z][a-z0-9_]*$")
SENSITIVE_KEYWORDS = ("secret", "token", "password", "private_key", "api_key")
REQUIRED_TOP_LEVEL_SECTIONS = (
    "api",
    "runtime",
    "regime",
    "momentum",
    "mean_reversion",
    "risk",
    "execution",
)


class ConfigError(ValueError):
    """Raised when the YAML configuration is invalid."""


def load_yaml_config(path: Path) -> dict[str, Any]:
    """Load and validate the project YAML configuration."""
    if not path.exists():
        raise ConfigError(f"Config file does not exist: {path}")

    try:
        loaded = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except yaml.YAMLError as exc:
        raise ConfigError(f"Invalid YAML in {path}") from exc

    if not isinstance(loaded, Mapping):
        raise ConfigError(f"Config root must be a mapping in {path}")

    config = _validate_mapping(loaded, context=path.name)
    missing_sections = sorted(set(REQUIRED_TOP_LEVEL_SECTIONS) - set(config))
    if missing_sections:
        missing_list = ", ".join(missing_sections)
        raise ConfigError(f"Missing required config sections in {path}: {missing_list}")

    _validate_semantics(config, path=path)
    return config


def read_config_value(
    config: Mapping[str, Any],
    *path: str,
    default: Any = None,
) -> Any:
    """Return a nested config value or a default when not configured."""
    current: Any = config
    for segment in path:
        if not isinstance(current, Mapping) or segment not in current:
            return default
        current = current[segment]
    return current


def _validate_mapping(mapping: Mapping[object, object], *, context: str) -> dict[str, Any]:
    normalized: dict[str, Any] = {}

    for raw_key, value in mapping.items():
        if not isinstance(raw_key, str):
            raise ConfigError(f"Config key at {context} must be a string")

        key = raw_key.strip()
        if not CONFIG_KEY_PATTERN.fullmatch(key):
            raise ConfigError(
                f"Config key '{key}' at {context} must use lower_snake_case naming"
            )
        if _looks_sensitive(key):
            raise ConfigError(
                f"Secret-like key '{key}' found at {context}; keep secrets in .env instead"
            )

        normalized[key] = _validate_value(value, context=f"{context}.{key}")

    return normalized


def _validate_list(values: list[Any], *, context: str) -> list[Any]:
    return [
        _validate_value(value, context=f"{context}[{index}]")
        for index, value in enumerate(values)
    ]


def _validate_value(value: Any, *, context: str) -> Any:
    if isinstance(value, Mapping):
        return _validate_mapping(value, context=context)
    if isinstance(value, list):
        return _validate_list(value, context=context)
    return value


def _looks_sensitive(key: str) -> bool:
    normalized = key.lower()
    return any(token in normalized for token in SENSITIVE_KEYWORDS)


def _validate_semantics(config: Mapping[str, Any], *, path: Path) -> None:
    _require_positive_number(
        read_config_value(config, "api", "timeout_seconds"),
        path=path,
        label="api.timeout_seconds",
    )

    for key in (
        "poll_interval_seconds",
        "trading_cycle_interval_seconds",
        "heartbeat_interval_seconds",
        "clock_sync_interval_seconds",
    ):
        _require_positive_integer(
            read_config_value(config, "runtime", key),
            path=path,
            label=f"runtime.{key}",
        )

    strategy_mode = read_config_value(config, "runtime", "strategy_mode", default="disabled")
    if strategy_mode not in {"disabled", "paper", "live"}:
        raise ConfigError(
            f"Invalid runtime.strategy_mode in {path}: expected one of disabled, paper, live"
        )

    day1_deploy = read_config_value(config, "runtime", "day1_max_deploy")
    if day1_deploy is not None:
        _require_fraction(day1_deploy, path=path, label="runtime.day1_max_deploy")
    day2_deploy = read_config_value(config, "runtime", "day2_max_deploy")
    if day2_deploy is not None:
        _require_fraction(day2_deploy, path=path, label="runtime.day2_max_deploy")
    day1_stop = read_config_value(config, "runtime", "day1_stop_loss_pct")
    if day1_stop is not None:
        _require_fraction(day1_stop, path=path, label="runtime.day1_stop_loss_pct")

    ema_fast = _require_positive_integer(
        read_config_value(config, "regime", "ema_fast_period"),
        path=path,
        label="regime.ema_fast_period",
    )
    ema_slow = _require_positive_integer(
        read_config_value(config, "regime", "ema_slow_period"),
        path=path,
        label="regime.ema_slow_period",
    )
    if ema_slow <= ema_fast:
        raise ConfigError(
            f"Invalid regime EMA periods in {path}: ema_slow_period must be greater than ema_fast_period"
        )
    _require_positive_integer(
        read_config_value(config, "regime", "volatility_lookback"),
        path=path,
        label="regime.volatility_lookback",
    )
    _require_positive_number(
        read_config_value(config, "regime", "volatility_threshold_multiplier"),
        path=path,
        label="regime.volatility_threshold_multiplier",
    )
    _require_positive_integer(
        read_config_value(config, "regime", "confirmation_periods"),
        path=path,
        label="regime.confirmation_periods",
    )

    lookback_periods = read_config_value(config, "momentum", "lookback_periods")
    if not isinstance(lookback_periods, list) or not lookback_periods:
        raise ConfigError(f"Invalid momentum.lookback_periods in {path}: expected a non-empty list")
    for index, value in enumerate(lookback_periods):
        _require_positive_integer(
            value,
            path=path,
            label=f"momentum.lookback_periods[{index}]",
        )
    _require_percentage(
        read_config_value(config, "momentum", "rsi_threshold"),
        path=path,
        label="momentum.rsi_threshold",
    )
    _require_positive_integer(
        read_config_value(config, "momentum", "top_n_assets"),
        path=path,
        label="momentum.top_n_assets",
    )

    _require_percentage(
        read_config_value(config, "mean_reversion", "rsi_oversold"),
        path=path,
        label="mean_reversion.rsi_oversold",
    )
    _require_positive_integer(
        read_config_value(config, "mean_reversion", "bollinger_period"),
        path=path,
        label="mean_reversion.bollinger_period",
    )
    _require_positive_number(
        read_config_value(config, "mean_reversion", "bollinger_std"),
        path=path,
        label="mean_reversion.bollinger_std",
    )
    _require_non_negative_number(
        read_config_value(config, "mean_reversion", "min_volume_usd"),
        path=path,
        label="mean_reversion.min_volume_usd",
    )
    _require_positive_integer(
        read_config_value(config, "mean_reversion", "max_hold_days"),
        path=path,
        label="mean_reversion.max_hold_days",
    )
    _require_fraction(
        read_config_value(config, "mean_reversion", "stop_loss_pct"),
        path=path,
        label="mean_reversion.stop_loss_pct",
    )

    _require_fraction(
        read_config_value(config, "risk", "max_position_pct"),
        path=path,
        label="risk.max_position_pct",
    )
    max_sector = read_config_value(config, "risk", "max_sector_pct")
    if max_sector is not None:
        _require_fraction(max_sector, path=path, label="risk.max_sector_pct")
    take_profit = read_config_value(config, "risk", "take_profit_pct")
    if take_profit is not None:
        _require_fraction(take_profit, path=path, label="risk.take_profit_pct")
    for key in ("cash_floor_bull", "cash_floor_ranging", "cash_floor_bear"):
        _require_fraction(
            read_config_value(config, "risk", key),
            path=path,
            label=f"risk.{key}",
        )
    _require_fraction(
        read_config_value(config, "risk", "stop_loss_pct"),
        path=path,
        label="risk.stop_loss_pct",
    )
    circuit_breaker_l1 = _require_fraction(
        read_config_value(config, "risk", "circuit_breaker_l1"),
        path=path,
        label="risk.circuit_breaker_l1",
    )
    circuit_breaker_l2 = _require_fraction(
        read_config_value(config, "risk", "circuit_breaker_l2"),
        path=path,
        label="risk.circuit_breaker_l2",
    )
    if circuit_breaker_l2 <= circuit_breaker_l1:
        raise ConfigError(
            f"Invalid circuit breaker thresholds in {path}: circuit_breaker_l2 must exceed circuit_breaker_l1"
        )
    _require_fraction(
        read_config_value(config, "risk", "daily_loss_limit"),
        path=path,
        label="risk.daily_loss_limit",
    )

    _require_non_negative_number(
        read_config_value(config, "execution", "limit_offset_pct"),
        path=path,
        label="execution.limit_offset_pct",
    )
    _require_non_negative_number(
        read_config_value(config, "execution", "min_rebalance_drift"),
        path=path,
        label="execution.min_rebalance_drift",
    )
    _require_positive_integer(
        read_config_value(config, "execution", "order_spacing_seconds"),
        path=path,
        label="execution.order_spacing_seconds",
    )


def _require_positive_integer(value: Any, *, path: Path, label: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
        raise ConfigError(f"Invalid {label} in {path}: expected a positive integer")
    return int(value)


def _require_positive_number(value: Any, *, path: Path, label: str) -> float:
    if not isinstance(value, Real) or isinstance(value, bool) or float(value) <= 0.0:
        raise ConfigError(f"Invalid {label} in {path}: expected a positive number")
    return float(value)


def _require_non_negative_number(value: Any, *, path: Path, label: str) -> float:
    if not isinstance(value, Real) or isinstance(value, bool) or float(value) < 0.0:
        raise ConfigError(f"Invalid {label} in {path}: expected a non-negative number")
    return float(value)


def _require_fraction(value: Any, *, path: Path, label: str) -> float:
    numeric = _require_non_negative_number(value, path=path, label=label)
    if numeric > 1.0:
        raise ConfigError(f"Invalid {label} in {path}: expected a value between 0 and 1")
    return numeric


def _require_percentage(value: Any, *, path: Path, label: str) -> float:
    numeric = _require_non_negative_number(value, path=path, label=label)
    if numeric > 100.0:
        raise ConfigError(f"Invalid {label} in {path}: expected a value between 0 and 100")
    return numeric

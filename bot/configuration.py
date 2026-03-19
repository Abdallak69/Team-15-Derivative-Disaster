"""YAML-backed runtime and strategy configuration helpers."""

from __future__ import annotations

from collections.abc import Mapping
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

"""Logging helpers for the trading bot runtime."""

from __future__ import annotations

from datetime import datetime
from datetime import timezone
import json
import logging
import logging.config
from pathlib import Path
import time
from typing import Any

import yaml


STANDARD_RECORD_FIELDS = frozenset(logging.makeLogRecord({}).__dict__)


class UtcFormatter(logging.Formatter):
    """Formatter that emits timestamps in UTC."""

    converter = time.gmtime


class JsonLineFormatter(logging.Formatter):
    """Formatter for machine-parseable JSONL trade logs."""

    converter = time.gmtime

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "ts": datetime.fromtimestamp(record.created, tz=timezone.utc)
            .isoformat()
            .replace("+00:00", "Z"),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }

        for key, value in record.__dict__.items():
            if key in STANDARD_RECORD_FIELDS or key.startswith("_"):
                continue
            payload[key] = value

        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)

        return json.dumps(payload, separators=(",", ":"), sort_keys=True)


def configure_logging(config_path: Path, project_root: Path) -> None:
    """Apply the YAML logging configuration using project-root-relative files."""
    with config_path.open("r", encoding="utf-8") as handle:
        raw_config = yaml.safe_load(handle)

    if not isinstance(raw_config, dict):
        raise ValueError(f"Logging config must be a mapping: {config_path}")

    handlers = raw_config.get("handlers", {})
    if isinstance(handlers, dict):
        for handler_config in handlers.values():
            if not isinstance(handler_config, dict):
                continue
            filename = handler_config.get("filename")
            if isinstance(filename, str) and not Path(filename).is_absolute():
                handler_config["filename"] = str(project_root / filename)

    (project_root / "logs").mkdir(parents=True, exist_ok=True)
    logging.config.dictConfig(raw_config)

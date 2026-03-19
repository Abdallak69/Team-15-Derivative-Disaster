"""Main application entrypoint for the trading bot."""

from __future__ import annotations

from dataclasses import dataclass, field
import json
import os
from pathlib import Path
import tempfile
from typing import Any


ROOT_DIR = Path(__file__).resolve().parent.parent


def _project_path(*parts: str) -> Path:
    return ROOT_DIR.joinpath(*parts)


@dataclass(slots=True)
class TradingBot:
    """Minimal import-safe bot entrypoint used for repo bootstrap."""

    config_path: Path = field(
        default_factory=lambda: _project_path("config", "strategy_params.yaml")
    )
    state_path: Path = field(default_factory=lambda: _project_path("data", "bot_state.json"))
    environment: str = field(default_factory=lambda: os.getenv("ENVIRONMENT", "development"))
    is_running: bool = False

    def default_state(self) -> dict[str, Any]:
        """Return the baseline persisted state structure."""
        return {
            "environment": self.environment,
            "paused": False,
            "portfolio_value": None,
            "positions": {},
        }

    def ensure_runtime_directories(self) -> None:
        """Create runtime directories that should exist before the bot starts."""
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        _project_path("logs").mkdir(parents=True, exist_ok=True)

    def bootstrap_state(self) -> Path:
        """Create the state file if it does not exist yet."""
        self.ensure_runtime_directories()
        if not self.state_path.exists():
            self.save_state(self.default_state())
        return self.state_path

    def load_state(self) -> dict[str, Any]:
        """Load persisted state, or the default structure when none exists."""
        if not self.state_path.exists():
            return self.default_state()
        return json.loads(self.state_path.read_text(encoding="utf-8"))

    def save_state(self, state: dict[str, Any] | None = None) -> Path:
        """Persist state via an atomic replace to avoid partial writes."""
        payload = state or self.default_state()
        self.ensure_runtime_directories()

        file_descriptor, temp_name = tempfile.mkstemp(
            dir=str(self.state_path.parent),
            prefix=f"{self.state_path.stem}-",
            suffix=".tmp",
        )
        try:
            with os.fdopen(file_descriptor, "w", encoding="utf-8") as handle:
                json.dump(payload, handle, indent=2, sort_keys=True)
                handle.write("\n")
            Path(temp_name).replace(self.state_path)
        finally:
            temp_path = Path(temp_name)
            if temp_path.exists():
                temp_path.unlink()
        return self.state_path

    def start(self) -> dict[str, Any]:
        """Mark the bot as running and ensure baseline runtime files exist."""
        self.is_running = True
        self.bootstrap_state()
        return self.status()

    def stop(self) -> dict[str, Any]:
        """Mark the bot as stopped."""
        self.is_running = False
        return self.status()

    def status(self) -> dict[str, Any]:
        """Expose a small status payload for bootstrap verification."""
        return {
            "config_path": str(self.config_path),
            "environment": self.environment,
            "is_running": self.is_running,
            "state_path": str(self.state_path),
        }


if __name__ == "__main__":
    print(TradingBot().status())


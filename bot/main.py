"""Main application entrypoint for the data-pipeline vertical slice."""

from __future__ import annotations

import argparse
from dataclasses import dataclass, field
from datetime import datetime
from datetime import timezone
import json
import os
from pathlib import Path
import tempfile
import time
from typing import Any

from bot.api import AuthCredentials
from bot.api import RoostooClient
from bot.api.roostoo_client import DEFAULT_BASE_URL
from bot.data import OhlcvStore
from bot.data import TickerPoller
from bot.data import UniverseBuilder


ROOT_DIR = Path(__file__).resolve().parent.parent


def _project_path(*parts: str) -> Path:
    return ROOT_DIR.joinpath(*parts)


def _load_dotenv_if_available() -> None:
    try:
        from dotenv import load_dotenv
    except ImportError:
        return

    load_dotenv(_project_path(".env"))


@dataclass(slots=True)
class TradingBot:
    """Single-process market data collector for the Roostoo ticker feed."""

    config_path: Path = field(
        default_factory=lambda: _project_path("config", "strategy_params.yaml")
    )
    state_path: Path = field(default_factory=lambda: _project_path("data", "bot_state.json"))
    db_path: Path = field(default_factory=lambda: _project_path("data", "live_ohlcv.db"))
    environment: str = field(default_factory=lambda: os.getenv("ENVIRONMENT", "development"))
    poll_interval_seconds: int = field(
        default_factory=lambda: int(os.getenv("POLL_INTERVAL_SECONDS", "60"))
    )
    client: RoostooClient | None = None
    store: OhlcvStore | None = None
    universe_builder: UniverseBuilder = field(default_factory=UniverseBuilder)
    poller: TickerPoller | None = None
    is_running: bool = False
    is_bootstrapped: bool = False
    universe: tuple[str, ...] = field(default_factory=tuple)
    scheduler: Any = field(default=None, init=False, repr=False)

    def __post_init__(self) -> None:
        _load_dotenv_if_available()
        self.environment = os.getenv("ENVIRONMENT", self.environment)
        self.poll_interval_seconds = int(
            os.getenv("POLL_INTERVAL_SECONDS", str(self.poll_interval_seconds))
        )

        if self.client is None:
            self.client = RoostooClient(
                base_url=os.getenv("ROOSTOO_BASE_URL", DEFAULT_BASE_URL),
                credentials=AuthCredentials.from_env(),
            )
        if self.store is None:
            self.store = OhlcvStore(self.db_path)
        if self.poller is None:
            self.poller = TickerPoller(client=self.client, store=self.store, pairs=self.universe)

    def default_state(self) -> dict[str, Any]:
        """Return the baseline persisted state structure."""
        return {
            "clock_offset_ms": self.client.clock_offset_ms if self.client else 0,
            "db_path": str(self.db_path),
            "environment": self.environment,
            "last_poll_at": None,
            "last_snapshot_count": 0,
            "last_stored_snapshot_count": 0,
            "paused": False,
            "portfolio_value": None,
            "positions": {},
            "universe": list(self.universe),
            "universe_size": len(self.universe),
        }

    def ensure_runtime_directories(self) -> None:
        """Create runtime directories that should exist before the bot starts."""
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
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

    def sync_server_time(self) -> int:
        """Sync the local clock offset and persist the updated state."""
        if self.client is None:
            raise RuntimeError("Roostoo client is not configured.")

        server_time_ms = self.client.sync_server_time()
        state = self.load_state()
        state["clock_offset_ms"] = self.client.clock_offset_ms
        state["server_time_ms"] = server_time_ms
        self.save_state(state)
        return server_time_ms

    def bootstrap(self) -> dict[str, Any]:
        """Prepare the client, universe, store, and state for polling."""
        if self.client is None or self.store is None or self.poller is None:
            raise RuntimeError("Trading bot dependencies are not configured.")

        self.ensure_runtime_directories()
        self.store.initialize()
        server_time_ms = self.sync_server_time()
        exchange_info = self.client.get_exchange_info()
        self.universe = tuple(self.universe_builder.build_from_exchange_info(exchange_info))
        self.poller.pairs = self.universe
        self.is_bootstrapped = True

        state = self.load_state()
        state.update(
            {
                "clock_offset_ms": self.client.clock_offset_ms,
                "db_path": str(self.db_path),
                "server_time_ms": server_time_ms,
                "universe": list(self.universe),
                "universe_size": len(self.universe),
            }
        )
        self.save_state(state)
        return self.status()

    def run_poll_cycle(self) -> dict[str, Any]:
        """Execute one ticker polling cycle and persist the result."""
        if not self.is_bootstrapped:
            self.bootstrap()
        if self.poller is None or self.client is None:
            raise RuntimeError("Polling pipeline is not configured.")

        result = self.poller.poll()
        state = self.load_state()
        state.update(
            {
                "clock_offset_ms": self.client.clock_offset_ms,
                "db_path": str(self.db_path),
                "last_poll_at": result.polled_at,
                "last_snapshot_count": result.snapshot_count,
                "last_stored_snapshot_count": result.stored_snapshot_count,
                "universe": list(self.universe),
                "universe_size": len(self.universe),
            }
        )
        self.save_state(state)
        return result.to_dict()

    def start(self) -> dict[str, Any]:
        """Prepare the pipeline and mark the bot as running."""
        self.is_running = True
        self.bootstrap()
        return self.status()

    def startup_check(self) -> dict[str, Any]:
        """Run the same bootstrap path as production startup, then exit."""
        self.start()
        return self.stop()

    def stop(self) -> dict[str, Any]:
        """Stop the scheduler loop."""
        if self.scheduler is not None:
            self.scheduler.shutdown(wait=False)
            self.scheduler = None
        self.is_running = False
        return self.status()

    def run_forever(self) -> None:
        """Start the scheduled polling loop."""
        self.start()
        scheduler = self._build_scheduler()
        if scheduler is None:
            self._run_fallback_loop()
            return

        self.scheduler = scheduler
        next_run_time = datetime.now(timezone.utc)
        scheduler.add_job(
            self.run_poll_cycle,
            "interval",
            seconds=self.poll_interval_seconds,
            id="ticker_poll",
            next_run_time=next_run_time,
            coalesce=True,
            max_instances=1,
        )
        scheduler.add_job(
            self.sync_server_time,
            "interval",
            hours=1,
            id="clock_sync",
            next_run_time=next_run_time,
            coalesce=True,
            max_instances=1,
        )
        try:
            scheduler.start()
        except (KeyboardInterrupt, SystemExit):
            self.stop()

    def status(self) -> dict[str, Any]:
        """Expose the current runtime state of the data collector."""
        return {
            "config_path": str(self.config_path),
            "clock_offset_ms": self.client.clock_offset_ms if self.client else 0,
            "db_path": str(self.db_path),
            "environment": self.environment,
            "is_bootstrapped": self.is_bootstrapped,
            "is_running": self.is_running,
            "poll_interval_seconds": self.poll_interval_seconds,
            "state_path": str(self.state_path),
            "universe_size": len(self.universe),
        }

    def _build_scheduler(self) -> Any | None:
        try:
            from apscheduler.executors.debug import DebugExecutor
            from apscheduler.schedulers.blocking import BlockingScheduler
        except ImportError:
            return None

        return BlockingScheduler(
            timezone=timezone.utc,
            executors={"default": DebugExecutor()},
        )

    def _run_fallback_loop(self) -> None:
        last_sync_monotonic = time.monotonic()
        try:
            self.run_poll_cycle()
            while self.is_running:
                time.sleep(self.poll_interval_seconds)
                if time.monotonic() - last_sync_monotonic >= 3600:
                    self.sync_server_time()
                    last_sync_monotonic = time.monotonic()
                self.run_poll_cycle()
        except KeyboardInterrupt:
            self.stop()


def _build_cli_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Roostoo trading bot entrypoint")
    parser.add_argument(
        "--startup-check",
        action="store_true",
        help="Run startup/bootstrap once and exit.",
    )
    parser.add_argument(
        "--status",
        action="store_true",
        help="Print the current bot status without network calls.",
    )
    return parser


if __name__ == "__main__":
    args = _build_cli_parser().parse_args()
    bot = TradingBot()

    if args.status:
        print(bot.status())
    elif args.startup_check:
        print(bot.startup_check())
    else:
        bot.run_forever()

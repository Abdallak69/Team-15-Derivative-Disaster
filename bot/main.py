"""Main application entrypoint for the current trading-bot runtime slice."""

from __future__ import annotations

import argparse
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime
from datetime import timedelta
from datetime import timezone
import json
import logging
import os
from pathlib import Path
import tempfile
import time
from typing import Any

from bot.api import AuthCredentials
from bot.api import RoostooClient
from bot.api.roostoo_client import DEFAULT_BASE_URL
from bot.configuration import read_config_value
from bot.configuration import load_yaml_config
from bot.data import OhlcvStore
from bot.data import TickerPoller
from bot.data import UniverseBuilder
from bot.environment import SecretConfigurationError
from bot.environment import load_secret_from_env
from bot.environment import load_project_env
from bot.logging_utils import configure_logging
from bot.monitoring import TelegramAlerter
from bot.monitoring import compute_drawdown
from bot.monitoring import compute_return
from bot.risk import CircuitBreaker
from bot.risk import RiskManager


ROOT_DIR = Path(__file__).resolve().parent.parent
SYSTEM_LOGGER = logging.getLogger("tradingbot.system")
SIGNALS_LOGGER = logging.getLogger("tradingbot.signals")


def _project_path(*parts: str) -> Path:
    return ROOT_DIR.joinpath(*parts)


def _first_present(payload: Mapping[str, Any], *keys: str) -> Any:
    for key in keys:
        if key in payload and payload[key] not in (None, ""):
            return payload[key]
    return None


def _coerce_float(value: Any) -> float | None:
    if value in (None, ""):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


@dataclass(slots=True)
class TradingBot:
    """Single-process orchestrator for the current trading-bot runtime."""

    config_path: Path = field(
        default_factory=lambda: _project_path("config", "strategy_params.yaml")
    )
    logging_config_path: Path = field(
        default_factory=lambda: _project_path("config", "logging_config.yaml")
    )
    state_path: Path = field(default_factory=lambda: _project_path("data", "bot_state.json"))
    db_path: Path = field(default_factory=lambda: _project_path("data", "live_ohlcv.db"))
    environment: str = "development"
    poll_interval_seconds: int = 60
    trading_cycle_interval_seconds: int = 300
    heartbeat_interval_seconds: int = 3600
    clock_sync_interval_seconds: int = 3600
    daily_loss_limit: float = 0.02
    min_rebalance_drift: float = 0.15
    order_spacing_seconds: int = 65
    client: RoostooClient | None = None
    store: OhlcvStore | None = None
    universe_builder: UniverseBuilder = field(default_factory=UniverseBuilder)
    alerter: TelegramAlerter | None = None
    risk_manager: RiskManager | None = None
    circuit_breaker: CircuitBreaker | None = None
    poller: TickerPoller | None = None
    is_running: bool = False
    is_bootstrapped: bool = False
    universe: tuple[str, ...] = field(default_factory=tuple)
    config: dict[str, Any] = field(default_factory=dict, init=False, repr=False)
    scheduler: Any = field(default=None, init=False, repr=False)

    def __post_init__(self) -> None:
        load_project_env(_project_path(".env"))
        self.config = load_yaml_config(self.config_path)
        configure_logging(self.logging_config_path, ROOT_DIR)

        self.environment = str(
            read_config_value(self.config, "runtime", "environment", default=self.environment)
        )
        self.poll_interval_seconds = int(
            read_config_value(
                self.config,
                "runtime",
                "poll_interval_seconds",
                default=self.poll_interval_seconds,
            )
        )
        self.trading_cycle_interval_seconds = int(
            read_config_value(
                self.config,
                "runtime",
                "trading_cycle_interval_seconds",
                default=self.trading_cycle_interval_seconds,
            )
        )
        self.heartbeat_interval_seconds = int(
            read_config_value(
                self.config,
                "runtime",
                "heartbeat_interval_seconds",
                default=self.heartbeat_interval_seconds,
            )
        )
        self.clock_sync_interval_seconds = int(
            read_config_value(
                self.config,
                "runtime",
                "clock_sync_interval_seconds",
                default=self.clock_sync_interval_seconds,
            )
        )
        max_position_pct = float(
            read_config_value(self.config, "risk", "max_position_pct", default=0.10)
        )
        circuit_breaker_level_one = float(
            read_config_value(self.config, "risk", "circuit_breaker_l1", default=0.03)
        )
        circuit_breaker_level_two = float(
            read_config_value(self.config, "risk", "circuit_breaker_l2", default=0.05)
        )
        self.daily_loss_limit = float(
            read_config_value(
                self.config,
                "risk",
                "daily_loss_limit",
                default=self.daily_loss_limit,
            )
        )
        self.min_rebalance_drift = float(
            read_config_value(
                self.config,
                "execution",
                "min_rebalance_drift",
                default=self.min_rebalance_drift,
            )
        )
        self.order_spacing_seconds = int(
            read_config_value(
                self.config,
                "execution",
                "order_spacing_seconds",
                default=self.order_spacing_seconds,
            )
        )

        if self.client is None:
            api_base_url = str(
                read_config_value(
                    self.config,
                    "api",
                    "base_url",
                    default=os.getenv("ROOSTOO_BASE_URL", DEFAULT_BASE_URL),
                )
            )
            timeout_seconds = float(
                read_config_value(self.config, "api", "timeout_seconds", default=10.0)
            )
            self.client = RoostooClient(
                base_url=api_base_url,
                credentials=AuthCredentials.from_env(),
                timeout_seconds=timeout_seconds,
            )
        if self.alerter is None:
            self.alerter = self._build_telegram_alerter()
        if self.risk_manager is None:
            self.risk_manager = RiskManager(max_position_pct=max_position_pct)
        if self.circuit_breaker is None:
            self.circuit_breaker = CircuitBreaker(
                level_one=circuit_breaker_level_one,
                level_two=circuit_breaker_level_two,
            )
        if self.store is None:
            self.store = OhlcvStore(self.db_path)
        if self.poller is None:
            self.poller = TickerPoller(client=self.client, store=self.store, pairs=self.universe)

        SYSTEM_LOGGER.info(
            "Initialized trading bot environment=%s poll_interval_seconds=%s "
            "trading_cycle_interval_seconds=%s heartbeat_interval_seconds=%s "
            "config=%s telegram_configured=%s",
            self.environment,
            self.poll_interval_seconds,
            self.trading_cycle_interval_seconds,
            self.heartbeat_interval_seconds,
            self.config_path,
            self.alerter is not None,
        )
        SYSTEM_LOGGER.info(
            "Loaded risk and execution config max_position_pct=%s "
            "circuit_breaker_l1=%s circuit_breaker_l2=%s daily_loss_limit=%s "
            "min_rebalance_drift=%s order_spacing_seconds=%s",
            self.risk_manager.max_position_pct if self.risk_manager else None,
            self.circuit_breaker.level_one if self.circuit_breaker else None,
            self.circuit_breaker.level_two if self.circuit_breaker else None,
            self.daily_loss_limit,
            self.min_rebalance_drift,
            self.order_spacing_seconds,
        )

    def default_state(self) -> dict[str, Any]:
        """Return the baseline persisted state structure."""
        return {
            "balance_snapshot": {},
            "clock_offset_ms": self.client.clock_offset_ms if self.client else 0,
            "circuit_breaker_status": "ok",
            "cumulative_return": 0.0,
            "db_path": str(self.db_path),
            "drawdown_pct": 0.0,
            "environment": self.environment,
            "last_heartbeat_at": None,
            "last_poll_at": None,
            "last_reconciled_at": None,
            "last_snapshot_count": 0,
            "last_stored_snapshot_count": 0,
            "pending_order_count": 0,
            "pending_orders": [],
            "paused": False,
            "peak_portfolio_value": None,
            "portfolio_value": None,
            "positions": {},
            "regime": "unknown",
            "start_portfolio_value": None,
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
        state = self._state_with_defaults(self.load_state())
        state["clock_offset_ms"] = self.client.clock_offset_ms
        state["server_time_ms"] = server_time_ms
        self.save_state(state)
        SYSTEM_LOGGER.info(
            "Clock synced server_time_ms=%s clock_offset_ms=%s",
            server_time_ms,
            self.client.clock_offset_ms,
        )
        return server_time_ms

    def bootstrap(self) -> dict[str, Any]:
        """Prepare the client, universe, store, and state for polling."""
        if self.client is None or self.store is None or self.poller is None:
            raise RuntimeError("Trading bot dependencies are not configured.")
        if isinstance(self.client, RoostooClient) and self.client.credentials is None:
            raise SecretConfigurationError(
                "Real Roostoo API credentials must be set in .env before startup"
            )

        self.ensure_runtime_directories()
        SYSTEM_LOGGER.info("Bootstrapping trading bot runtime")
        self.store.initialize()
        server_time_ms = self.sync_server_time()
        exchange_info = self.client.get_exchange_info()
        self.universe = tuple(self.universe_builder.build_from_exchange_info(exchange_info))
        self.poller.pairs = self.universe
        self.is_bootstrapped = True
        SIGNALS_LOGGER.info("Loaded tradeable universe with %s pairs", len(self.universe))

        state = self._state_with_defaults(self.load_state())
        state.update(
            {
                "clock_offset_ms": self.client.clock_offset_ms,
                "db_path": str(self.db_path),
                "server_time_ms": server_time_ms,
                "universe": list(self.universe),
                "universe_size": len(self.universe),
            }
        )
        state = self._reconcile_state(state, save=False)
        self.save_state(state)
        SYSTEM_LOGGER.info(
            "Bootstrap complete universe_size=%s clock_offset_ms=%s",
            len(self.universe),
            self.client.clock_offset_ms,
        )
        return self.status()

    def run_poll_cycle(self) -> dict[str, Any]:
        """Execute one ticker polling cycle and persist the result."""
        if not self.is_bootstrapped:
            self.bootstrap()
        if self.poller is None or self.client is None:
            raise RuntimeError("Polling pipeline is not configured.")

        result = self.poller.poll()
        state = self._state_with_defaults(self.load_state())
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
        SYSTEM_LOGGER.info(
            "Poll cycle completed snapshot_count=%s stored_snapshot_count=%s",
            result.snapshot_count,
            result.stored_snapshot_count,
        )
        return result.to_dict()

    def run_operational_cycle(self) -> dict[str, Any]:
        """Run the current non-order operational cycle for state reconciliation."""
        if not self.is_bootstrapped:
            self.bootstrap()

        state = self._reconcile_state()
        SYSTEM_LOGGER.info(
            "Operational cycle completed portfolio_value=%s pending_order_count=%s paused=%s",
            state["portfolio_value"],
            state["pending_order_count"],
            state["paused"],
        )
        return {
            "circuit_breaker_status": state["circuit_breaker_status"],
            "drawdown_pct": state["drawdown_pct"],
            "last_reconciled_at": state["last_reconciled_at"],
            "paused": state["paused"],
            "pending_order_count": state["pending_order_count"],
            "portfolio_value": state["portfolio_value"],
        }

    def start(self) -> dict[str, Any]:
        """Prepare the pipeline and mark the bot as running."""
        self.is_running = True
        SYSTEM_LOGGER.info("Starting trading bot")
        try:
            self.bootstrap()
        except Exception:
            self.is_running = False
            SYSTEM_LOGGER.exception("Trading bot startup failed")
            raise

        self._send_startup_alert()
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
        SYSTEM_LOGGER.info("Stopping trading bot")
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
            self.run_operational_cycle,
            "interval",
            seconds=self.trading_cycle_interval_seconds,
            id="operational_cycle",
            next_run_time=next_run_time,
            coalesce=True,
            max_instances=1,
        )
        scheduler.add_job(
            self.send_heartbeat,
            "interval",
            seconds=self.heartbeat_interval_seconds,
            id="heartbeat",
            next_run_time=next_run_time + timedelta(seconds=self.heartbeat_interval_seconds),
            coalesce=True,
            max_instances=1,
        )
        scheduler.add_job(
            self.sync_server_time,
            "interval",
            seconds=self.clock_sync_interval_seconds,
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
        """Expose the current runtime state without making network calls."""
        state = self._state_with_defaults(self.load_state())
        return {
            "config_path": str(self.config_path),
            "logging_config_path": str(self.logging_config_path),
            "clock_offset_ms": self.client.clock_offset_ms if self.client else 0,
            "circuit_breaker_status": state["circuit_breaker_status"],
            "db_path": str(self.db_path),
            "environment": self.environment,
            "heartbeat_interval_seconds": self.heartbeat_interval_seconds,
            "is_bootstrapped": self.is_bootstrapped,
            "is_running": self.is_running,
            "last_heartbeat_at": state["last_heartbeat_at"],
            "last_poll_at": state["last_poll_at"],
            "last_reconciled_at": state["last_reconciled_at"],
            "paused": state["paused"],
            "pending_order_count": state["pending_order_count"],
            "poll_interval_seconds": self.poll_interval_seconds,
            "portfolio_value": state["portfolio_value"],
            "state_path": str(self.state_path),
            "telegram_configured": self.alerter is not None,
            "trading_cycle_interval_seconds": self.trading_cycle_interval_seconds,
            "universe_size": len(self.universe) or state["universe_size"],
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
        last_operational_monotonic = time.monotonic()
        last_heartbeat_monotonic = time.monotonic()
        try:
            self.run_poll_cycle()
            self.run_operational_cycle()
            while self.is_running:
                time.sleep(self.poll_interval_seconds)
                current_monotonic = time.monotonic()
                if current_monotonic - last_sync_monotonic >= self.clock_sync_interval_seconds:
                    self.sync_server_time()
                    last_sync_monotonic = current_monotonic
                if (
                    current_monotonic - last_operational_monotonic
                    >= self.trading_cycle_interval_seconds
                ):
                    self.run_operational_cycle()
                    last_operational_monotonic = current_monotonic
                if (
                    current_monotonic - last_heartbeat_monotonic
                    >= self.heartbeat_interval_seconds
                ):
                    self.send_heartbeat()
                    last_heartbeat_monotonic = current_monotonic
                self.run_poll_cycle()
        except KeyboardInterrupt:
            self.stop()

    def send_heartbeat(self) -> dict[str, Any]:
        """Send an operational heartbeat when Telegram monitoring is configured."""
        state = self._state_with_defaults(self.load_state())
        message = (
            f"env={self.environment} universe={len(self.universe)} "
            f"portfolio_value={state['portfolio_value']} "
            f"drawdown_pct={state['drawdown_pct']} "
            f"pending_orders={state['pending_order_count']} "
            f"last_poll_at={state['last_poll_at']}"
        )
        delivered = self._send_telegram_message("Heartbeat", message)
        if delivered:
            state["last_heartbeat_at"] = datetime.now(timezone.utc).isoformat()
            self.save_state(state)
            SYSTEM_LOGGER.info(
                "Heartbeat emitted portfolio_value=%s pending_order_count=%s",
                state["portfolio_value"],
                state["pending_order_count"],
            )
        return {
            "last_heartbeat_at": state["last_heartbeat_at"],
            "pending_order_count": state["pending_order_count"],
            "portfolio_value": state["portfolio_value"],
        }

    def _reconcile_state(self, state: dict[str, Any] | None = None, *, save: bool = True) -> dict[str, Any]:
        if self.client is None:
            raise RuntimeError("Roostoo client is not configured.")

        current_state = self._state_with_defaults(state or self.load_state())
        balance_payload = self._request_if_available("get_balance")
        orders_payload = self._request_if_available("query_order", pending_only=True)

        extracted_portfolio_value = self._extract_portfolio_value(balance_payload)
        portfolio_value = (
            current_state["portfolio_value"]
            if balance_payload is None and extracted_portfolio_value is None
            else extracted_portfolio_value
        )
        extracted_positions = self._extract_positions(balance_payload)
        positions = (
            current_state["positions"]
            if balance_payload is None and not extracted_positions
            else extracted_positions
        )
        extracted_pending_orders = self._extract_pending_orders(orders_payload)
        pending_orders = (
            current_state["pending_orders"]
            if orders_payload is None and not extracted_pending_orders
            else extracted_pending_orders
        )
        pending_order_count = (
            current_state["pending_order_count"]
            if orders_payload is None and not extracted_pending_orders
            else self._extract_pending_order_count(orders_payload, pending_orders)
        )
        reconciled_at = datetime.now(timezone.utc).isoformat()

        if portfolio_value is not None:
            peak_portfolio_value = current_state["peak_portfolio_value"] or portfolio_value
            peak_portfolio_value = max(float(peak_portfolio_value), portfolio_value)
            start_portfolio_value = current_state["start_portfolio_value"] or portfolio_value
            drawdown_pct = compute_drawdown(peak_portfolio_value, portfolio_value)
            cumulative_return = compute_return(start_portfolio_value, portfolio_value)
        else:
            peak_portfolio_value = current_state["peak_portfolio_value"]
            start_portfolio_value = current_state["start_portfolio_value"]
            drawdown_pct = current_state["drawdown_pct"]
            cumulative_return = current_state["cumulative_return"]

        circuit_breaker_status = (
            self.circuit_breaker.evaluate(drawdown_pct) if self.circuit_breaker else "ok"
        )
        paused = circuit_breaker_status == "halt"

        current_state.update(
            {
                "balance_snapshot": (
                    dict(balance_payload)
                    if isinstance(balance_payload, Mapping)
                    else current_state["balance_snapshot"]
                ),
                "circuit_breaker_status": circuit_breaker_status,
                "cumulative_return": cumulative_return,
                "drawdown_pct": drawdown_pct,
                "last_reconciled_at": reconciled_at,
                "paused": paused,
                "peak_portfolio_value": peak_portfolio_value,
                "pending_order_count": pending_order_count,
                "pending_orders": pending_orders,
                "portfolio_value": portfolio_value,
                "positions": positions,
                "start_portfolio_value": start_portfolio_value,
            }
        )

        if save:
            self.save_state(current_state)

        SYSTEM_LOGGER.info(
            "State reconciled portfolio_value=%s positions=%s pending_order_count=%s "
            "drawdown_pct=%s circuit_breaker_status=%s",
            portfolio_value,
            len(positions),
            pending_order_count,
            drawdown_pct,
            circuit_breaker_status,
        )
        return current_state

    def _request_if_available(self, method_name: str, **kwargs: Any) -> Any:
        method = getattr(self.client, method_name, None)
        if callable(method):
            return method(**kwargs)
        SYSTEM_LOGGER.info("Skipping %s; client does not implement it", method_name)
        return None

    def _build_telegram_alerter(self) -> TelegramAlerter | None:
        bot_token = load_secret_from_env("TELEGRAM_BOT_TOKEN")
        chat_id = load_secret_from_env("TELEGRAM_CHAT_ID")

        if bot_token is None and chat_id is None:
            return None
        if bot_token is None or chat_id is None:
            raise SecretConfigurationError(
                "Incomplete Telegram configuration; TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID must both be set"
            )
        return TelegramAlerter(bot_token=bot_token, chat_id=chat_id)

    def _send_startup_alert(self) -> None:
        state = self._state_with_defaults(self.load_state())
        message = (
            f"env={self.environment} universe={len(self.universe)} "
            f"portfolio_value={state['portfolio_value']} "
            f"pending_orders={state['pending_order_count']}"
        )
        self._send_telegram_message("Bot Started", message)

    def _send_telegram_message(self, title: str, body: str) -> bool:
        if self.alerter is None:
            SYSTEM_LOGGER.info(
                "Telegram alert skipped title=%s because Telegram is not configured",
                title,
            )
            return False

        try:
            self.alerter.send_titled_message(title, body)
        except Exception:
            SYSTEM_LOGGER.exception("Telegram alert failed title=%s", title)
            return False
        else:
            SYSTEM_LOGGER.info("Telegram alert delivered title=%s", title)
            return True

    def _state_with_defaults(self, state: dict[str, Any] | None = None) -> dict[str, Any]:
        merged = self.default_state()
        if state:
            merged.update(state)
        return merged

    def _unwrap_response_payload(self, payload: Any) -> Any:
        current = payload
        while isinstance(current, Mapping):
            for key in ("Data", "data", "Result", "result", "Results", "results", "payload"):
                if key in current and current[key] is not None:
                    current = current[key]
                    break
            else:
                return current
        return current

    def _extract_record_list(self, payload: Any, keys: tuple[str, ...]) -> list[dict[str, Any]]:
        if isinstance(payload, list):
            return [dict(item) for item in payload if isinstance(item, Mapping)]
        if isinstance(payload, Mapping):
            for key in keys:
                value = payload.get(key)
                if isinstance(value, list):
                    return [dict(item) for item in value if isinstance(item, Mapping)]
        return []

    def _extract_portfolio_value(self, payload: Any) -> float | None:
        data = self._unwrap_response_payload(payload)
        if isinstance(data, Mapping):
            direct_value = _coerce_float(
                _first_present(
                    data,
                    "portfolio_value",
                    "portfolioValue",
                    "total_equity",
                    "totalEquity",
                    "equity",
                    "account_value",
                    "accountValue",
                    "net_asset_value",
                    "netAssetValue",
                    "total_balance",
                    "totalBalance",
                )
            )
            if direct_value is not None:
                return direct_value

            total_value = 0.0
            found_values = False
            for record in self._extract_record_list(
                data,
                ("balances", "Balances", "positions", "Positions", "assets", "Assets", "holdings"),
            ):
                record_value = _coerce_float(
                    _first_present(
                        record,
                        "usd_value",
                        "usdValue",
                        "market_value",
                        "marketValue",
                        "value",
                        "Value",
                        "notional",
                        "Notional",
                    )
                )
                if record_value is None:
                    continue
                total_value += record_value
                found_values = True
            if found_values:
                return total_value

        return _coerce_float(data)

    def _extract_positions(self, payload: Any) -> dict[str, float]:
        data = self._unwrap_response_payload(payload)
        positions: dict[str, float] = {}
        records = self._extract_record_list(
            data,
            ("balances", "Balances", "positions", "Positions", "assets", "Assets", "holdings"),
        )

        if not records and isinstance(data, Mapping):
            scalar_mapping = {}
            for key, value in data.items():
                amount = _coerce_float(value)
                if amount is None or amount == 0.0:
                    continue
                scalar_mapping[str(key)] = amount
            if scalar_mapping:
                return scalar_mapping

        for record in records:
            symbol = _first_present(
                record,
                "pair",
                "Pair",
                "symbol",
                "Symbol",
                "asset",
                "Asset",
                "coin",
                "Coin",
                "currency",
                "Currency",
            )
            quantity = _coerce_float(
                _first_present(
                    record,
                    "quantity",
                    "Quantity",
                    "qty",
                    "Qty",
                    "position",
                    "Position",
                    "amount",
                    "Amount",
                    "balance",
                    "Balance",
                    "available",
                    "Available",
                    "free",
                    "Free",
                    "total",
                    "Total",
                )
            )
            if symbol and quantity not in (None, 0.0):
                positions[str(symbol)] = float(quantity)
        return positions

    def _extract_pending_orders(self, payload: Any) -> list[dict[str, Any]]:
        data = self._unwrap_response_payload(payload)
        return self._extract_record_list(
            data,
            (
                "orders",
                "Orders",
                "pending_orders",
                "pendingOrders",
                "items",
                "Items",
            ),
        )

    def _extract_pending_order_count(self, payload: Any, orders: list[dict[str, Any]]) -> int:
        if orders:
            return len(orders)

        data = self._unwrap_response_payload(payload)
        if isinstance(data, Mapping):
            count = _coerce_float(
                _first_present(
                    data,
                    "pending_count",
                    "pendingCount",
                    "count",
                    "Count",
                    "total",
                    "Total",
                )
            )
            if count is not None:
                return int(count)
        return 0


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

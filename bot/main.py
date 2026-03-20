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
from bot.backtest import CoreModuleBacktester
from bot.configuration import read_config_value
from bot.configuration import load_yaml_config
from bot.data import BinanceFetcher
from bot.data import BinanceHistoryStore
from bot.data import OhlcvStore
from bot.data import SentimentFetcher
from bot.data import MarketDefinition
from bot.data import TickerPoller
from bot.data import UniverseBuilder
from bot.environment import SecretConfigurationError
from bot.environment import load_secret_from_env
from bot.environment import load_project_env
from bot.execution import generate_rebalance_orders
from bot.execution import execute_orders
from bot.logging_utils import configure_logging
from bot.monitoring import MetricsTracker
from bot.monitoring import TelegramAlerter
from bot.monitoring import compute_return
from bot.risk import CircuitBreaker
from bot.risk import RiskDecision
from bot.risk import RiskManager
from bot.signals.momentum import rank_assets_by_momentum
from bot.signals.mean_reversion import find_oversold_assets
from bot.signals.momentum import calculate_rsi
from bot.signals.pairs_rotation import pairs_rotation_weights as compute_pairs_weights
from bot.signals.sector_rotation import sector_rotation_weights
from bot.strategy import PortfolioOptimizer
from bot.strategy import ensemble_combine
from bot.strategy import detect_regime
from bot.strategy import strategy_pipeline_ready


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


def _parse_symbol_list(raw_symbols: str | None) -> tuple[str, ...]:
    if not raw_symbols:
        return ()
    return tuple(
        symbol.strip()
        for symbol in raw_symbols.split(",")
        if symbol.strip()
    )


def _resolve_backtest_symbols(bot: TradingBot, explicit_symbols: str | None) -> tuple[str, ...]:
    requested_symbols = _parse_symbol_list(explicit_symbols)
    if requested_symbols:
        return requested_symbols

    state_universe = bot.load_state().get("universe", [])
    if isinstance(state_universe, list) and state_universe:
        return tuple(str(symbol) for symbol in state_universe if symbol)

    if bot.client is not None:
        exchange_info = bot.client.get_exchange_info()
        universe = bot.universe_builder.build_from_exchange_info(exchange_info)
        if universe:
            return tuple(universe)

    raise RuntimeError(
        "Unable to resolve a symbol universe. Run local polling/bootstrap first or pass --symbols."
    )


def _run_core_module_backtest(bot: TradingBot, args: argparse.Namespace) -> dict[str, Any]:
    symbols = _resolve_backtest_symbols(bot, args.symbols)
    history_store = BinanceHistoryStore(
        Path(args.historical_db_path)
        if args.historical_db_path
        else _project_path("data", "binance_historical.db")
    )
    backtester = CoreModuleBacktester(
        config=bot.config,
        history_store=history_store,
        fetcher=BinanceFetcher(),
    )
    report = backtester.run(
        symbols=symbols,
        history_days=args.history_days,
        train_days=args.train_days,
        validation_days=args.validation_days,
        benchmark_symbol=args.benchmark_symbol,
    )
    SYSTEM_LOGGER.info(
        "Core-module backtest completed symbols=%s history_days=%s db_path=%s",
        len(symbols),
        args.history_days,
        history_store.db_path,
    )
    return report


@dataclass(frozen=True, slots=True)
class StrategyCycleResult:
    """Serializable summary of one strategy-cycle decision point."""

    mode: str
    status: str
    triggered_at: str
    notes: tuple[str, ...] = ()
    target_weights: dict[str, float] = field(default_factory=dict)
    proposed_orders: tuple[dict[str, Any], ...] = ()

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-serializable representation of the strategy-cycle status."""
        return {
            "mode": self.mode,
            "notes": list(self.notes),
            "proposed_orders": [dict(order) for order in self.proposed_orders],
            "status": self.status,
            "target_weights": dict(self.target_weights),
            "triggered_at": self.triggered_at,
        }


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
    strategy_mode: str = "disabled"
    daily_loss_limit: float = 0.02
    min_rebalance_drift: float = 0.15
    order_spacing_seconds: int = 65
    sentiment_refresh_interval_seconds: int = 14400
    client: RoostooClient | None = None
    store: OhlcvStore | None = None
    universe_builder: UniverseBuilder = field(default_factory=UniverseBuilder)
    alerter: TelegramAlerter | None = None
    risk_manager: RiskManager | None = None
    circuit_breaker: CircuitBreaker | None = None
    poller: TickerPoller | None = None
    portfolio_optimizer: PortfolioOptimizer | None = None
    sentiment_fetcher: SentimentFetcher | None = None
    metrics_tracker: MetricsTracker | None = None
    is_running: bool = False
    is_bootstrapped: bool = False
    universe: tuple[str, ...] = field(default_factory=tuple)
    last_sentiment_multiplier: float = field(default=1.0, init=False, repr=False)
    last_regime: str = field(default="ranging", init=False, repr=False)
    config: dict[str, Any] = field(default_factory=dict, init=False, repr=False)
    scheduler: Any = field(default=None, init=False, repr=False)
    _ema_fast_period: int = field(default=20, init=False, repr=False)
    _ema_slow_period: int = field(default=50, init=False, repr=False)
    _vol_threshold_mult: float = field(default=1.5, init=False, repr=False)
    _market_definitions: dict[str, MarketDefinition] = field(default_factory=dict, init=False, repr=False)
    _regime_streak_count: int = field(default=0, init=False, repr=False)
    _regime_streak_value: str = field(default="unknown", init=False, repr=False)
    _confirmation_periods: int = field(default=2, init=False, repr=False)
    _competition_start_time: datetime | None = field(default=None, init=False, repr=False)

    def __post_init__(self) -> None:
        load_project_env(_project_path(".env"))
        self.config = load_yaml_config(self.config_path)
        configure_logging(self.logging_config_path, ROOT_DIR)

        configured_environment = str(
            read_config_value(self.config, "runtime", "environment", default=self.environment)
        )
        environment_override = os.getenv("ENVIRONMENT")
        self.environment = (
            environment_override.strip()
            if environment_override is not None and environment_override.strip()
            else configured_environment
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
        self.sentiment_refresh_interval_seconds = int(
            read_config_value(
                self.config,
                "runtime",
                "sentiment_refresh_interval_seconds",
                default=self.sentiment_refresh_interval_seconds,
            )
        )
        self.strategy_mode = str(
            read_config_value(
                self.config,
                "runtime",
                "strategy_mode",
                default=self.strategy_mode,
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
        stop_loss_pct = float(
            read_config_value(self.config, "risk", "stop_loss_pct", default=0.03)
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
        self._ema_fast_period = int(
            read_config_value(self.config, "regime", "ema_fast_period", default=20)
        )
        self._ema_slow_period = int(
            read_config_value(self.config, "regime", "ema_slow_period", default=50)
        )
        self._vol_threshold_mult = float(
            read_config_value(self.config, "regime", "volatility_threshold_multiplier", default=1.5)
        )
        self._confirmation_periods = int(
            read_config_value(self.config, "regime", "confirmation_periods", default=2)
        )

        competition_start_raw = read_config_value(
            self.config, "runtime", "competition_start", default=None,
        )
        if competition_start_raw:
            self._competition_start_time = datetime.fromisoformat(str(competition_start_raw))

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
            take_profit_pct = float(
                read_config_value(self.config, "risk", "take_profit_pct", default=0.08)
            )
            self.risk_manager = RiskManager(
                max_position_pct=max_position_pct,
                stop_loss_pct=stop_loss_pct,
                daily_loss_limit=self.daily_loss_limit,
                take_profit_pct=take_profit_pct,
            )
        if self.circuit_breaker is None:
            self.circuit_breaker = CircuitBreaker(
                level_one=circuit_breaker_level_one,
                level_two=circuit_breaker_level_two,
            )
        if self.store is None:
            self.store = OhlcvStore(self.db_path)
        if self.poller is None:
            self.poller = TickerPoller(client=self.client, store=self.store, pairs=self.universe)
        if self.portfolio_optimizer is None:
            cash_floor_bull = float(
                read_config_value(self.config, "risk", "cash_floor_bull", default=0.20)
            )
            cash_floor_ranging = float(
                read_config_value(self.config, "risk", "cash_floor_ranging", default=0.40)
            )
            cash_floor_bear = float(
                read_config_value(self.config, "risk", "cash_floor_bear", default=0.50)
            )
            max_sector_pct = float(
                read_config_value(self.config, "risk", "max_sector_pct", default=0.30)
            )
            self.portfolio_optimizer = PortfolioOptimizer(
                max_position_pct=max_position_pct,
                max_sector_pct=max_sector_pct,
                cash_floor_bull=cash_floor_bull,
                cash_floor_ranging=cash_floor_ranging,
                cash_floor_bear=cash_floor_bear,
            )
        if self.sentiment_fetcher is None:
            self.sentiment_fetcher = SentimentFetcher(
                extreme_fear=int(read_config_value(self.config, "sentiment", "fgi_extreme_fear", default=20)),
                fear=int(read_config_value(self.config, "sentiment", "fgi_fear", default=35)),
                greed=int(read_config_value(self.config, "sentiment", "fgi_greed", default=65)),
                extreme_greed=int(read_config_value(self.config, "sentiment", "fgi_extreme_greed", default=80)),
                mult_extreme_fear=float(read_config_value(self.config, "sentiment", "multiplier_extreme_fear", default=1.30)),
                mult_fear=float(read_config_value(self.config, "sentiment", "multiplier_fear", default=1.15)),
                mult_greed=float(read_config_value(self.config, "sentiment", "multiplier_greed", default=0.85)),
                mult_extreme_greed=float(read_config_value(self.config, "sentiment", "multiplier_extreme_greed", default=0.70)),
            )
        if self.metrics_tracker is None:
            self.metrics_tracker = MetricsTracker()

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
            "btc_dominance": None,
            "clock_offset_ms": self.client.clock_offset_ms if self.client else 0,
            "circuit_breaker_status": "ok",
            "cumulative_return": 0.0,
            "db_path": str(self.db_path),
            "drawdown_pct": 0.0,
            "environment": self.environment,
            "last_heartbeat_at": None,
            "last_poll_at": None,
            "last_reconciled_at": None,
            "last_strategy_cycle": {},
            "last_strategy_cycle_at": None,
            "last_snapshot_count": 0,
            "last_stored_snapshot_count": 0,
            "max_drawdown": 0.0,
            "pending_order_count": 0,
            "pending_orders": [],
            "paused": False,
            "paused_until": None,
            "peak_portfolio_value": None,
            "portfolio_value": None,
            "positions": {},
            "previous_btc_dominance": None,
            "regime": "unknown",
            "risk_decision": self._default_risk_decision(),
            "risk_state": {},
            "start_portfolio_value": None,
            "strategy_cycle_status": "disabled" if self.strategy_mode == "disabled" else "pending",
            "strategy_mode": self.strategy_mode,
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
        try:
            payload = json.loads(self.state_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            quarantined_path = self._quarantine_corrupt_state_file()
            SYSTEM_LOGGER.exception(
                "State file could not be read; restored defaults state_path=%s quarantined_path=%s",
                self.state_path,
                quarantined_path,
            )
            return self.default_state()

        if not isinstance(payload, dict):
            quarantined_path = self._quarantine_corrupt_state_file()
            SYSTEM_LOGGER.error(
                "State file root was not a JSON object; restored defaults state_path=%s quarantined_path=%s",
                self.state_path,
                quarantined_path,
            )
            return self.default_state()

        return payload

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
        self._market_definitions = self.universe_builder.parse_exchange_info(exchange_info)
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

        state = self._reconcile_state(save=False)
        strategy_cycle = self._run_strategy_cycle()
        state.update(
            {
                "last_strategy_cycle": strategy_cycle.to_dict(),
                "last_strategy_cycle_at": strategy_cycle.triggered_at,
                "strategy_cycle_status": strategy_cycle.status,
                "strategy_mode": strategy_cycle.mode,
            }
        )
        self.save_state(state)
        SYSTEM_LOGGER.info(
            "Operational cycle completed portfolio_value=%s pending_order_count=%s paused=%s strategy_cycle_status=%s",
            state["portfolio_value"],
            state["pending_order_count"],
            state["paused"],
            strategy_cycle.status,
        )
        return {
            "block_new_buys": state["risk_decision"]["block_new_buys"],
            "circuit_breaker_status": state["circuit_breaker_status"],
            "drawdown_pct": state["drawdown_pct"],
            "last_reconciled_at": state["last_reconciled_at"],
            "last_strategy_cycle_at": state["last_strategy_cycle_at"],
            "max_drawdown": state["max_drawdown"],
            "paused": state["paused"],
            "paused_until": state["paused_until"],
            "pending_order_count": state["pending_order_count"],
            "portfolio_value": state["portfolio_value"],
            "risk_decision": dict(state["risk_decision"]),
            "strategy_cycle_status": state["strategy_cycle_status"],
            "strategy_mode": state["strategy_mode"],
            "strategy_pipeline_ready": strategy_pipeline_ready(),
        }

    def start(self) -> dict[str, Any]:
        """Prepare the pipeline and mark the bot as running."""
        self._assert_runtime_mode_supported()
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

    def poll_once(self) -> dict[str, Any]:
        """Bootstrap and execute one poll cycle without scheduler or Telegram side effects."""
        poll_result = self.run_poll_cycle()
        state = self._state_with_defaults(self.load_state())
        return {
            "db_path": str(self.db_path),
            "environment": self.environment,
            "is_bootstrapped": self.is_bootstrapped,
            "last_poll_at": state["last_poll_at"],
            "pending_order_count": state["pending_order_count"],
            "poll_interval_seconds": self.poll_interval_seconds,
            "portfolio_value": state["portfolio_value"],
            "snapshot_count": poll_result["snapshot_count"],
            "stored_snapshot_count": poll_result["stored_snapshot_count"],
            "telegram_configured": self.alerter is not None,
            "universe_size": len(self.universe),
        }

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
        scheduler.add_job(
            self.refresh_sentiment,
            "interval",
            seconds=self.sentiment_refresh_interval_seconds,
            id="sentiment_refresh",
            next_run_time=next_run_time,
            coalesce=True,
            max_instances=1,
        )
        scheduler.add_job(
            self.run_daily_maintenance,
            "interval",
            seconds=86400,
            id="daily_maintenance",
            next_run_time=next_run_time + timedelta(seconds=86400),
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
            "block_new_buys": state["risk_decision"]["block_new_buys"],
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
            "last_strategy_cycle_at": state["last_strategy_cycle_at"],
            "max_drawdown": state["max_drawdown"],
            "paused": state["paused"],
            "paused_until": state["paused_until"],
            "pending_order_count": state["pending_order_count"],
            "poll_interval_seconds": self.poll_interval_seconds,
            "portfolio_value": state["portfolio_value"],
            "risk_decision": dict(state["risk_decision"]),
            "state_path": str(self.state_path),
            "strategy_cycle_status": state["strategy_cycle_status"],
            "strategy_mode": self.strategy_mode,
            "strategy_pipeline_ready": strategy_pipeline_ready(),
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
        last_sentiment_monotonic = time.monotonic()
        last_maintenance_monotonic = time.monotonic()
        try:
            self.run_poll_cycle()
            self.run_operational_cycle()
            self.refresh_sentiment()
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
                    current_monotonic - last_sentiment_monotonic
                    >= self.sentiment_refresh_interval_seconds
                ):
                    self.refresh_sentiment()
                    last_sentiment_monotonic = current_monotonic
                if (
                    current_monotonic - last_heartbeat_monotonic
                    >= self.heartbeat_interval_seconds
                ):
                    self.send_heartbeat()
                    last_heartbeat_monotonic = current_monotonic
                if current_monotonic - last_maintenance_monotonic >= 86400:
                    self.run_daily_maintenance()
                    last_maintenance_monotonic = current_monotonic
                self.run_poll_cycle()
        except KeyboardInterrupt:
            self.stop()

    def run_daily_maintenance(self) -> None:
        """Prune old candle data and run garbage collection (24-hour job)."""
        import gc
        if self.store is not None:
            try:
                deleted = self.store.prune(max_days=30)
                SYSTEM_LOGGER.info("Daily maintenance: pruned %d old candle rows", deleted)
            except Exception:
                SYSTEM_LOGGER.warning("Daily maintenance: prune failed", exc_info=True)
        gc.collect()
        SYSTEM_LOGGER.info("Daily maintenance: gc.collect completed")

    def send_heartbeat(self) -> dict[str, Any]:
        """Send an operational heartbeat when Telegram monitoring is configured."""
        state = self._state_with_defaults(self.load_state())
        message = (
            f"env={self.environment} universe={len(self.universe)} "
            f"portfolio_value={state['portfolio_value']} "
            f"drawdown_pct={state['drawdown_pct']} "
            f"risk_priority={state['risk_decision']['priority']} "
            f"pending_orders={state['pending_order_count']} "
            f"strategy_mode={state['strategy_mode']} "
            f"strategy_status={state['strategy_cycle_status']} "
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
            start_portfolio_value = current_state["start_portfolio_value"] or portfolio_value
            cumulative_return = compute_return(start_portfolio_value, portfolio_value)
        else:
            start_portfolio_value = current_state["start_portfolio_value"]
            cumulative_return = current_state["cumulative_return"]

        current_state.update(
            {
                "balance_snapshot": (
                    dict(balance_payload)
                    if isinstance(balance_payload, Mapping)
                    else current_state["balance_snapshot"]
                ),
                "cumulative_return": cumulative_return,
                "pending_order_count": pending_order_count,
                "pending_orders": pending_orders,
                "portfolio_value": portfolio_value,
                "positions": positions,
                "start_portfolio_value": start_portfolio_value,
            }
        )

        peak_portfolio_value = current_state["peak_portfolio_value"]
        drawdown_pct = current_state["drawdown_pct"]
        max_drawdown = current_state["max_drawdown"]
        circuit_breaker_status = current_state["circuit_breaker_status"]
        paused = current_state["paused"]
        paused_until = current_state["paused_until"]
        risk_state = current_state["risk_state"]
        risk_decision = current_state["risk_decision"]

        if portfolio_value is not None:
            risk_state, risk_decision = self._evaluate_risk_state(current_state)
            peak_portfolio_value = risk_state["peak_value"]
            drawdown_pct = float(risk_decision["current_drawdown"])
            max_drawdown = float(risk_decision["max_drawdown"])
            circuit_breaker_status = self._resolve_circuit_breaker_status(risk_decision)
            paused = bool(risk_decision["paused"])
            paused_until = risk_decision["paused_until"]

        current_state.update(
            {
                "circuit_breaker_status": circuit_breaker_status,
                "drawdown_pct": drawdown_pct,
                "last_reconciled_at": reconciled_at,
                "max_drawdown": max_drawdown,
                "paused": paused,
                "paused_until": paused_until,
                "peak_portfolio_value": peak_portfolio_value,
                "risk_decision": risk_decision,
                "risk_state": risk_state,
            }
        )

        if save:
            self.save_state(current_state)

        SYSTEM_LOGGER.info(
            "State reconciled portfolio_value=%s positions=%s pending_order_count=%s "
            "drawdown_pct=%s circuit_breaker_status=%s risk_priority=%s",
            portfolio_value,
            len(positions),
            pending_order_count,
            drawdown_pct,
            circuit_breaker_status,
            risk_decision["priority"],
        )
        return current_state

    def _default_risk_decision(self) -> dict[str, Any]:
        return RiskDecision().to_dict()

    def _build_risk_snapshot(self, state: Mapping[str, Any]) -> dict[str, Any]:
        balance_snapshot = self._unwrap_response_payload(state.get("balance_snapshot", {}))
        balance_records = self._extract_record_list(
            balance_snapshot,
            ("balances", "Balances", "positions", "Positions", "assets", "Assets", "holdings"),
        )
        raw_positions = state.get("positions", {})
        current_positions = raw_positions if isinstance(raw_positions, Mapping) else {}
        positions: list[dict[str, Any]] = []
        seen_pairs: set[str] = set()

        for record in balance_records:
            pair = _first_present(
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
            if pair in (None, "") or quantity in (None, 0.0):
                continue

            market_value = _coerce_float(
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
            last_price = _coerce_float(
                _first_present(
                    record,
                    "last_price",
                    "lastPrice",
                    "mark_price",
                    "markPrice",
                    "price",
                    "Price",
                )
            )
            if last_price is None and market_value is not None and quantity:
                last_price = market_value / quantity

            positions.append(
                {
                    "entry_price": _coerce_float(
                        _first_present(
                            record,
                            "entry_price",
                            "entryPrice",
                            "avg_entry_price",
                            "avgEntryPrice",
                            "average_entry_price",
                            "averageEntryPrice",
                            "cost_basis",
                            "costBasis",
                            "avg_cost",
                            "avgCost",
                        )
                    ),
                    "last_price": last_price,
                    "market_value_usd": market_value,
                    "pair": str(pair),
                    "quantity": float(quantity),
                }
            )
            seen_pairs.add(str(pair))

        for pair, quantity in current_positions.items():
            if pair in seen_pairs:
                continue
            amount = _coerce_float(quantity)
            if amount in (None, 0.0):
                continue
            positions.append(
                {
                    "entry_price": None,
                    "last_price": None,
                    "market_value_usd": None,
                    "pair": str(pair),
                    "quantity": float(amount),
                }
            )

        portfolio_value = _coerce_float(state.get("portfolio_value")) or 0.0
        return {
            "cash_usd": 0.0,
            "pending_orders": list(state.get("pending_orders", [])),
            "positions": positions,
            "timestamp": int(datetime.now(timezone.utc).timestamp()),
            "total_portfolio_value_usd": portfolio_value,
        }

    def _initialize_risk_state(
        self,
        state: Mapping[str, Any],
        snapshot: Mapping[str, Any],
    ) -> dict[str, Any]:
        if self.risk_manager is None:
            raise RuntimeError("Risk manager is not configured.")

        existing_state = state.get("risk_state")
        if isinstance(existing_state, Mapping) and existing_state:
            return dict(existing_state)

        risk_state = self.risk_manager.make_initial_state(snapshot)
        peak_portfolio_value = _coerce_float(state.get("peak_portfolio_value"))
        if peak_portfolio_value is not None and peak_portfolio_value > 0:
            risk_state["peak_value"] = peak_portfolio_value
        max_drawdown = _coerce_float(state.get("max_drawdown"))
        if max_drawdown is not None:
            risk_state["max_drawdown"] = max_drawdown
        paused_until = _coerce_float(state.get("paused_until"))
        if paused_until is not None:
            risk_state["paused_until"] = int(paused_until)
        return risk_state

    def _resolve_risk_priority(
        self,
        portfolio_action: str | None,
        forced_sells: list[dict[str, Any]],
        block_new_buys: bool,
    ) -> str:
        if portfolio_action == "LIQUIDATE_ALL":
            return "LIQUIDATE_ALL"
        if portfolio_action == "REDUCE_ALL_50":
            return "REDUCE_ALL_50"
        if forced_sells:
            return "FORCED_SELLS"
        if block_new_buys:
            return "BLOCK_NEW_BUYS"
        return "NONE"

    def _build_risk_decision(
        self,
        *,
        risk_state: Mapping[str, Any],
        current_drawdown: float,
        portfolio_action: str | None = None,
        forced_sells: list[dict[str, Any]] | None = None,
        block_new_buys: bool = False,
        reason: str = "ok",
        paused: bool = False,
    ) -> dict[str, Any]:
        orders = forced_sells or []
        return RiskDecision(
            portfolio_action=portfolio_action,
            forced_sells=tuple(dict(order) for order in orders),
            block_new_buys=block_new_buys,
            current_drawdown=current_drawdown,
            max_drawdown=float(risk_state["max_drawdown"]),
            daily_loss_hit_today=bool(risk_state["daily_loss_hit_today"]),
            paused_until=risk_state["paused_until"],
            paused=paused,
            priority=self._resolve_risk_priority(portfolio_action, orders, block_new_buys),
            reason=reason,
        ).to_dict()

    def _resolve_circuit_breaker_status(self, risk_decision: Mapping[str, Any]) -> str:
        if risk_decision.get("paused"):
            return "paused"
        portfolio_action = risk_decision.get("portfolio_action")
        if portfolio_action == "LIQUIDATE_ALL":
            return "halt"
        if portfolio_action == "REDUCE_ALL_50":
            return "reduce"
        if self.circuit_breaker is None:
            return "ok"
        return self.circuit_breaker.evaluate(float(risk_decision["current_drawdown"]))

    def _evaluate_risk_state(self, state: Mapping[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
        if self.risk_manager is None or self.circuit_breaker is None:
            raise RuntimeError("Risk components are not configured.")

        snapshot = self._build_risk_snapshot(state)
        risk_state = self._initialize_risk_state(state, snapshot)
        now = int(snapshot["timestamp"])

        paused_until = risk_state.get("paused_until")
        if paused_until is not None and now < int(paused_until):
            self.risk_manager.rollover_day_if_needed(snapshot, risk_state)
            self.risk_manager.refresh_pending_exit_pairs(snapshot, risk_state)
            risk_state, current_drawdown = self.circuit_breaker.update_drawdown(snapshot, risk_state)
            return risk_state, self._build_risk_decision(
                risk_state=risk_state,
                current_drawdown=current_drawdown,
                block_new_buys=True,
                paused=True,
                reason="paused_until",
            )

        risk_state, portfolio_action, current_drawdown = self.circuit_breaker.check_circuit_breaker(
            snapshot,
            risk_state,
        )
        if portfolio_action is not None:
            return risk_state, self._build_risk_decision(
                risk_state=risk_state,
                current_drawdown=current_drawdown,
                portfolio_action=portfolio_action,
                block_new_buys=True,
                paused=portfolio_action == "LIQUIDATE_ALL",
                reason="circuit_breaker",
            )

        atr_values: dict[str, float] | None = None
        if self.store is not None:
            try:
                position_pairs = [str(p["pair"]) for p in snapshot["positions"]]
                if position_pairs:
                    candles = self.store.fetch_candles(
                        pairs=position_pairs,
                        since=datetime.now(timezone.utc) - timedelta(days=14),
                    )
                    if candles:
                        import pandas as _pd
                        _cdf = _pd.DataFrame(candles)
                        atr_values = {}
                        for pair in position_pairs:
                            _pair_data = _cdf[_cdf["pair"] == pair].sort_values("candle_ts")
                            if len(_pair_data) < 14:
                                continue
                            _h = _pair_data["high"].astype(float)
                            _l = _pair_data["low"].astype(float)
                            _c = _pair_data["close"].astype(float)
                            _cp = _c.shift(1)
                            _tr = _pd.concat([
                                (_h - _l),
                                (_h - _cp).abs(),
                                (_l - _cp).abs(),
                            ], axis=1).max(axis=1)
                            atr_values[pair] = float(_tr.iloc[-14:].mean())
            except Exception:
                SYSTEM_LOGGER.warning("ATR computation for risk failed", exc_info=True)

        risk_result = self.risk_manager.evaluate_risk(snapshot, risk_state, atr_values=atr_values)
        risk_state = risk_result["state"]
        forced_sells = list(risk_result["forced_sells"])
        block_new_buys = bool(risk_result["block_new_buys"])
        reason = "ok"
        has_stop = any(fs.get("reason") == "stop_loss" for fs in forced_sells)
        has_tp = any(fs.get("reason") == "take_profit" for fs in forced_sells)
        if has_stop and has_tp:
            reason = "stop_loss+take_profit"
        elif has_stop:
            reason = "stop_loss"
        elif has_tp:
            reason = "take_profit"
        elif block_new_buys:
            reason = "daily_loss_limit"

        return risk_state, self._build_risk_decision(
            risk_state=risk_state,
            current_drawdown=current_drawdown,
            forced_sells=forced_sells,
            block_new_buys=block_new_buys,
            reason=reason,
        )

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

    def _assert_runtime_mode_supported(self) -> None:
        if self.strategy_mode not in ("disabled", "paper", "live"):
            raise RuntimeError(
                f"Unsupported runtime.strategy_mode={self.strategy_mode!r}; expected disabled, paper, or live."
            )

    def refresh_sentiment(self) -> None:
        """Fetch latest sentiment data and cache the deployment multiplier."""
        if self.sentiment_fetcher is None:
            return
        try:
            snapshot = self.sentiment_fetcher.fetch_fear_and_greed()
            self.last_sentiment_multiplier = snapshot.deployment_multiplier
            SIGNALS_LOGGER.info(
                "Sentiment refreshed fgi=%d classification=%s multiplier=%.2f",
                snapshot.fgi_value, snapshot.fgi_classification, snapshot.deployment_multiplier,
            )
        except Exception:
            SYSTEM_LOGGER.warning("Sentiment fetch failed; retaining previous multiplier=%.2f", self.last_sentiment_multiplier)

    def _build_price_map(self, state: Mapping[str, Any]) -> dict[str, float]:
        """Extract a {symbol: last_price} map from the current state/ticker data."""
        prices: dict[str, float] = {}
        balance_snapshot = self._unwrap_response_payload(state.get("balance_snapshot", {}))
        records = self._extract_record_list(
            balance_snapshot,
            ("balances", "Balances", "positions", "Positions", "assets", "Assets", "holdings"),
        )
        for record in records:
            pair = _first_present(record, "pair", "Pair", "symbol", "Symbol")
            price = _coerce_float(_first_present(record, "last_price", "lastPrice", "LastPrice", "price", "Price"))
            if pair and price and price > 0:
                prices[str(pair)] = price
        return prices

    def _build_current_weights(self, state: Mapping[str, Any]) -> dict[str, float]:
        """Compute current portfolio weights from positions and portfolio value."""
        portfolio_value = _coerce_float(state.get("portfolio_value"))
        if not portfolio_value or portfolio_value <= 0:
            return {}
        positions = state.get("positions", {})
        if not isinstance(positions, Mapping):
            return {}
        weights: dict[str, float] = {}
        prices = self._build_price_map(state)
        for pair, qty in positions.items():
            amount = _coerce_float(qty)
            if not amount or amount <= 0:
                continue
            price = prices.get(pair, 0.0)
            if price <= 0:
                continue
            weights[pair] = (amount * price) / portfolio_value
        return weights

    def _get_competition_day(self) -> int:
        """Return how many days since competition start (1-indexed). 0 = not set."""
        if self._competition_start_time is None:
            return 0
        delta = datetime.now(timezone.utc) - self._competition_start_time
        return max(int(delta.total_seconds() // 86400) + 1, 1)

    def _run_strategy_cycle(self) -> StrategyCycleResult:
        triggered_at = datetime.now(timezone.utc).isoformat()
        notes: list[str] = []

        if self.strategy_mode == "disabled":
            return StrategyCycleResult(
                mode=self.strategy_mode,
                status="disabled",
                triggered_at=triggered_at,
                notes=("Strategy cycle disabled by runtime.strategy_mode.",),
            )

        state = self._state_with_defaults(self.load_state())
        risk_decision = state.get("risk_decision", self._default_risk_decision())

        if state.get("paused"):
            notes.append("Bot is paused by circuit breaker — skipping strategy cycle.")
            return StrategyCycleResult(
                mode=self.strategy_mode,
                status="paused",
                triggered_at=triggered_at,
                notes=tuple(notes),
            )

        if risk_decision.get("block_new_buys"):
            notes.append(f"New buys blocked — reason: {risk_decision.get('reason', 'unknown')}")

        portfolio_value = _coerce_float(state.get("portfolio_value"))
        if not portfolio_value or portfolio_value <= 0:
            notes.append("No portfolio value available — cannot run strategy cycle.")
            return StrategyCycleResult(
                mode=self.strategy_mode,
                status="no_portfolio_data",
                triggered_at=triggered_at,
                notes=tuple(notes),
            )

        regime = state.get("regime", "ranging")

        momentum_weights: dict[str, float] = {}
        mean_reversion_weights: dict[str, float] = {}
        sector_weights: dict[str, float] = {}

        try:
            if self.store is not None:
                candles = self.store.fetch_candles(
                    pairs=list(self.universe),
                    since=datetime.now(timezone.utc) - timedelta(days=14),
                )
                if candles:
                    import pandas as pd
                    df = pd.DataFrame(candles)
                    if not df.empty and "pair" in df.columns and "close" in df.columns:
                        closes = df.pivot_table(index="candle_ts", columns="pair", values="close")
                        volumes = df.pivot_table(index="candle_ts", columns="pair", values="coin_trade_value_24h")
                        if not closes.empty:
                            try:
                                btc_col = next((c for c in closes.columns if "BTC" in c), None)
                                if btc_col is not None:
                                    btc_closes = closes[btc_col].dropna()
                                    min_periods = max(self._ema_fast_period, self._ema_slow_period) + 1
                                    if len(btc_closes) >= min_periods:
                                        ema_fast_val = btc_closes.ewm(span=self._ema_fast_period, adjust=False).mean().iloc[-1]
                                        ema_slow_val = btc_closes.ewm(span=self._ema_slow_period, adjust=False).mean().iloc[-1]
                                        returns = btc_closes.pct_change().dropna()
                                        vol = returns.std() if len(returns) > 1 else 0.0
                                        vol_threshold = returns.std() * self._vol_threshold_mult if len(returns) > 1 else 1.0
                                        raw_regime = detect_regime(
                                            ema_fast=ema_fast_val,
                                            ema_slow=ema_slow_val,
                                            volatility=vol,
                                            volatility_threshold=vol_threshold,
                                            price=btc_closes.iloc[-1],
                                        )
                                        if raw_regime == self._regime_streak_value:
                                            self._regime_streak_count += 1
                                        else:
                                            self._regime_streak_value = raw_regime
                                            self._regime_streak_count = 1
                                        if self.last_regime == "unknown" or self.last_regime == "ranging":
                                            regime = raw_regime
                                        elif raw_regime != self.last_regime and self._regime_streak_count >= self._confirmation_periods:
                                            regime = raw_regime
                                        else:
                                            regime = self.last_regime
                                        SIGNALS_LOGGER.info(
                                            "Regime detected: %s (raw=%s streak=%d ema_fast=%.2f ema_slow=%.2f vol=%.4f)",
                                            regime, raw_regime, self._regime_streak_count, ema_fast_val, ema_slow_val, vol,
                                        )
                            except Exception:
                                SYSTEM_LOGGER.warning("Regime detection failed; using state fallback", exc_info=True)
                            try:
                                mom_signals = rank_assets_by_momentum(
                                    closes, volumes,
                                    lookback_periods=tuple(int(v) for v in read_config_value(self.config, "momentum", "lookback_periods", default=[3, 5, 7])),
                                    rsi_threshold=float(read_config_value(self.config, "momentum", "rsi_threshold", default=45)),
                                    top_n_assets=int(read_config_value(self.config, "momentum", "top_n_assets", default=8)),
                                )
                                momentum_weights = {s.symbol: s.normalized_score for s in mom_signals}
                                SIGNALS_LOGGER.info("Momentum signals generated: %d assets", len(momentum_weights))
                            except Exception:
                                SYSTEM_LOGGER.warning("Momentum signal generation failed", exc_info=True)

                            try:
                                rsi_threshold = float(read_config_value(self.config, "mean_reversion", "rsi_oversold", default=30))
                                rsi_values: dict[str, float] = {}
                                for col in closes.columns:
                                    series = closes[col].dropna()
                                    if len(series) >= 15:
                                        rsi = calculate_rsi(series, period=14)
                                        last_rsi = rsi.dropna()
                                        if not last_rsi.empty:
                                            rsi_values[col] = float(last_rsi.iloc[-1])
                                oversold_symbols = find_oversold_assets(rsi_values, threshold=rsi_threshold)
                                mean_reversion_weights = {s: 0.5 for s in oversold_symbols}
                                SIGNALS_LOGGER.info("Mean-reversion signals: %d assets (RSI <= %.0f)", len(mean_reversion_weights), rsi_threshold)
                            except Exception:
                                SYSTEM_LOGGER.warning("Mean-reversion signal generation failed", exc_info=True)

            try:
                btc_dominance = _coerce_float(state.get("btc_dominance")) or 58.0
                previous_dominance = _coerce_float(state.get("previous_btc_dominance")) or 57.5

                btc_price_direction = "flat"
                if "BTCUSDT" in closes.columns and len(closes) >= 2:
                    btc_last = float(closes["BTCUSDT"].dropna().iloc[-1])
                    btc_prev = float(closes["BTCUSDT"].dropna().iloc[-2])
                    if btc_prev > 0:
                        btc_pct_change = (btc_last - btc_prev) / btc_prev
                        if btc_pct_change > 0.001:
                            btc_price_direction = "rising"
                        elif btc_pct_change < -0.001:
                            btc_price_direction = "falling"

                sector_weights = sector_rotation_weights(
                    universe=list(self.universe),
                    btc_dominance=btc_dominance,
                    previous_dominance=previous_dominance,
                    btc_price_direction=btc_price_direction,
                )
                SIGNALS_LOGGER.info(
                    "Sector weights generated for %d assets (btc_price_dir=%s)",
                    len(sector_weights), btc_price_direction,
                )
            except Exception:
                SYSTEM_LOGGER.warning("Sector rotation failed", exc_info=True)

            pairs_weights: dict[str, float] = {}
            try:
                if not closes.empty and len(closes) >= 60:
                    pairs_cfg = self.config.get("pairs_rotation", {})
                    pr_lookback = int(pairs_cfg.get("lookback", 60))
                    pr_adf = float(pairs_cfg.get("adf_threshold", 0.05))
                    pr_min_hl = float(pairs_cfg.get("min_half_life", 1.0))
                    pr_max_hl = float(pairs_cfg.get("max_half_life", 30.0))
                    pr_z_entry = float(pairs_cfg.get("z_entry", 2.0))
                    pr_max_pairs = int(pairs_cfg.get("max_pairs", 3))
                    pairs_weights = compute_pairs_weights(
                        closes.iloc[-pr_lookback:],
                        max_pairs=pr_max_pairs,
                        adf_pvalue_threshold=pr_adf,
                        min_half_life=pr_min_hl,
                        max_half_life=pr_max_hl,
                        z_entry_threshold=pr_z_entry,
                    )
                    if pairs_weights:
                        SIGNALS_LOGGER.info("Pairs rotation signals: %d assets", len(pairs_weights))
            except Exception:
                SYSTEM_LOGGER.warning("Pairs rotation failed", exc_info=True)

        except Exception:
            SYSTEM_LOGGER.warning("Signal generation failed", exc_info=True)
            notes.append("Signal generation encountered errors.")

        self.last_regime = regime
        ensemble_result = ensemble_combine(
            regime,
            momentum_weights=momentum_weights or None,
            mean_reversion_weights=mean_reversion_weights or None,
            sector_rotation_weights=sector_weights or None,
            pairs_rotation_weights=pairs_weights or None,
            sentiment_multiplier=self.last_sentiment_multiplier,
        )
        SIGNALS_LOGGER.info(
            "Ensemble combined regime=%s target_assets=%d cash_allocation=%.2f",
            ensemble_result.regime, len(ensemble_result.target_weights), ensemble_result.cash_allocation,
        )

        funding_bonus_threshold = float(
            read_config_value(self.config, "sentiment", "funding_rate_bonus_threshold", default=-0.0001)
        )
        funding_bonus_pct = float(
            read_config_value(self.config, "sentiment", "funding_rate_bonus_pct", default=0.02)
        )
        combined_weights = dict(ensemble_result.target_weights)
        if self.sentiment_fetcher is not None:
            try:
                funding_rates = self.sentiment_fetcher.fetch_funding_rates(list(self.universe))
                for sym, rate in funding_rates.items():
                    if rate < funding_bonus_threshold:
                        combined_weights[sym] = combined_weights.get(sym, 0.0) + funding_bonus_pct
                        SIGNALS_LOGGER.info("Funding rate bonus: %s rate=%.6f bonus=+%.2f%%", sym, rate, funding_bonus_pct * 100)
            except Exception:
                SYSTEM_LOGGER.warning("Funding rate bonus application failed", exc_info=True)

        volatilities: dict[str, float] | None = None
        try:
            if self.store is not None:
                candles = self.store.fetch_candles(
                    pairs=list(self.universe),
                    since=datetime.now(timezone.utc) - timedelta(days=14),
                )
                if candles:
                    import pandas as pd
                    vdf = pd.DataFrame(candles)
                    if not vdf.empty and "pair" in vdf.columns and "close" in vdf.columns:
                        vcloses = vdf.pivot_table(index="candle_ts", columns="pair", values="close")
                        if not vcloses.empty and len(vcloses) > 2:
                            vols = vcloses.pct_change().std()
                            volatilities = {str(s): float(v) for s, v in vols.items() if v > 0 and not pd.isna(v)}
        except Exception:
            SYSTEM_LOGGER.warning("Volatility computation for inverse-vol failed", exc_info=True)

        competition_day = self._get_competition_day()
        day1_max_deploy = float(read_config_value(self.config, "runtime", "day1_max_deploy", default=0.30))
        day2_max_deploy = float(read_config_value(self.config, "runtime", "day2_max_deploy", default=0.60))
        day1_stop_loss = float(read_config_value(self.config, "runtime", "day1_stop_loss_pct", default=0.02))
        deploy_cap: float | None = None

        if competition_day == 1:
            deploy_cap = day1_max_deploy
            btc_eth_only = {"BTCUSDT", "ETHUSDT", "BTCUSD", "ETHUSD"}
            combined_weights = {s: w for s, w in combined_weights.items() if s.upper() in btc_eth_only}
            if self.risk_manager is not None:
                self.risk_manager.stop_loss_pct = day1_stop_loss
            SIGNALS_LOGGER.info("Day 1 protocol: BTC/ETH only, cap=%.0f%%, stop=%.1f%%", deploy_cap * 100, day1_stop_loss * 100)
        elif competition_day == 2:
            deploy_cap = day2_max_deploy
            if self.risk_manager is not None:
                self.risk_manager.stop_loss_pct = float(read_config_value(self.config, "risk", "stop_loss_pct", default=0.03))
            SIGNALS_LOGGER.info("Day 2 protocol: full universe, cap=%.0f%%", deploy_cap * 100)
        elif competition_day >= 3:
            if self.risk_manager is not None:
                self.risk_manager.stop_loss_pct = float(read_config_value(self.config, "risk", "stop_loss_pct", default=0.03))

        win_rates: dict[str, float] | None = None
        avg_wl: dict[str, float] | None = None
        try:
            if not closes.empty and len(closes) > 7:
                daily_rets = closes.pct_change().iloc[-30:]
                wr: dict[str, float] = {}
                awl: dict[str, float] = {}
                for col in daily_rets.columns:
                    s = daily_rets[col].dropna()
                    if len(s) < 10:
                        continue
                    wins = s[s > 0]
                    losses = s[s < 0]
                    if not wins.empty and not losses.empty and abs(float(losses.mean())) > 0:
                        wr[col] = float((s > 0).mean())
                        awl[col] = float(wins.mean()) / abs(float(losses.mean()))
                if wr:
                    win_rates = wr
                    avg_wl = awl
        except Exception:
            SYSTEM_LOGGER.warning("Win-rate / avg-win-loss computation failed", exc_info=True)

        if self.portfolio_optimizer is not None:
            target_weights = self.portfolio_optimizer.optimize(
                combined_weights,
                volatilities=volatilities,
                regime=regime,
                win_rates=win_rates,
                avg_win_loss=avg_wl,
            )
        else:
            target_weights = dict(combined_weights)

        if deploy_cap is not None:
            total_deployed = sum(target_weights.values())
            if total_deployed > deploy_cap and total_deployed > 0:
                scale = deploy_cap / total_deployed
                target_weights = {s: w * scale for s, w in target_weights.items()}

        current_weights = self._build_current_weights(state)
        prices = self._build_price_map(state)

        orders = generate_rebalance_orders(
            current_weights,
            target_weights,
            portfolio_value=portfolio_value,
            prices=prices,
            exchange_info=self._market_definitions or None,
            limit_offset_pct=float(read_config_value(self.config, "execution", "limit_offset_pct", default=0.0001)),
            min_rebalance_drift=self.min_rebalance_drift,
            prefer_limit=bool(read_config_value(self.config, "execution", "prefer_limit_orders", default=True)),
        )

        proposed = tuple(
            {"side": o.side, "symbol": o.symbol, "qty": o.quantity, "price": o.price, "type": o.order_type}
            for o in orders
        )

        if self.strategy_mode == "paper":
            if risk_decision.get("block_new_buys"):
                buy_orders = [o for o in orders if o.side == "BUY"]
                sell_orders = [o for o in orders if o.side == "SELL"]
                if sell_orders:
                    execute_orders(sell_orders, self.client, spacing_seconds=0, dry_run=True)
                if buy_orders:
                    notes.append(f"Paper mode: blocked {len(buy_orders)} BUY orders — risk gating active.")
                notes.append(f"Paper mode: {len(sell_orders)} SELL orders logged (dry run).")
            else:
                if orders:
                    execute_orders(orders, self.client, spacing_seconds=0, dry_run=True)
                    notes.append(f"Paper mode: {len(orders)} orders logged (dry run).")
                else:
                    notes.append("Paper mode: no rebalancing needed (within drift tolerance).")
            return StrategyCycleResult(
                mode=self.strategy_mode,
                status="paper_executed",
                triggered_at=triggered_at,
                target_weights=target_weights,
                proposed_orders=proposed,
                notes=tuple(notes),
            )

        if self.strategy_mode == "live":
            if risk_decision.get("block_new_buys"):
                buy_orders = [o for o in orders if o.side == "BUY"]
                sell_orders = [o for o in orders if o.side == "SELL"]
                if sell_orders:
                    execute_orders(sell_orders, self.client, spacing_seconds=self.order_spacing_seconds, dry_run=False)
                if buy_orders:
                    notes.append(f"Blocked {len(buy_orders)} BUY orders — risk gating active.")
            else:
                if orders:
                    execute_orders(orders, self.client, spacing_seconds=self.order_spacing_seconds, dry_run=False)
            notes.append(f"Live: {len(orders)} orders processed.")
            return StrategyCycleResult(
                mode=self.strategy_mode,
                status="live_executed",
                triggered_at=triggered_at,
                target_weights=target_weights,
                proposed_orders=proposed,
                notes=tuple(notes),
            )

        return StrategyCycleResult(
            mode=self.strategy_mode,
            status="unknown_mode",
            triggered_at=triggered_at,
            notes=(f"Unexpected strategy_mode={self.strategy_mode!r}",),
        )

    def _state_with_defaults(self, state: dict[str, Any] | None = None) -> dict[str, Any]:
        merged = self.default_state()
        if state:
            merged.update(state)
        merged["environment"] = self.environment
        return merged

    def _quarantine_corrupt_state_file(self) -> Path | None:
        if not self.state_path.exists():
            return None
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        quarantined_path = self.state_path.with_name(
            f"{self.state_path.stem}.corrupt-{timestamp}{self.state_path.suffix}"
        )
        self.state_path.replace(quarantined_path)
        return quarantined_path

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

            wallet_value = self._sum_wallet_balances(data)
            if wallet_value is not None:
                return wallet_value

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

    @staticmethod
    def _sum_wallet_balances(data: Mapping[str, Any]) -> float | None:
        """Sum Free+Lock values across SpotWallet/MarginWallet (Roostoo format).

        Roostoo returns ``{"SpotWallet": {"USD": {"Free": 50000, "Lock": 0}}, ...}``.
        """
        total = 0.0
        found = False
        for wallet_key in ("SpotWallet", "MarginWallet"):
            wallet = data.get(wallet_key)
            if not isinstance(wallet, Mapping):
                continue
            for _asset, holdings in wallet.items():
                if not isinstance(holdings, Mapping):
                    continue
                free = _coerce_float(holdings.get("Free")) or 0.0
                lock = _coerce_float(holdings.get("Lock")) or 0.0
                total += free + lock
                found = True
        return total if found else None

    def _extract_positions(self, payload: Any) -> dict[str, float]:
        data = self._unwrap_response_payload(payload)
        positions: dict[str, float] = {}

        if isinstance(data, Mapping):
            wallet_positions = self._extract_wallet_positions(data)
            if wallet_positions:
                return wallet_positions

        records = self._extract_record_list(
            data,
            ("balances", "Balances", "positions", "Positions", "assets", "Assets", "holdings"),
        )

        if not records and isinstance(data, Mapping):
            for key in (
                "balances_by_asset",
                "balancesByAsset",
                "positions_by_symbol",
                "positionsBySymbol",
                "holdings_by_asset",
                "holdingsByAsset",
            ):
                candidate_mapping = data.get(key)
                if not isinstance(candidate_mapping, Mapping):
                    continue

                scalar_mapping = {}
                for raw_symbol, raw_amount in candidate_mapping.items():
                    amount = _coerce_float(raw_amount)
                    if amount is None or amount == 0.0:
                        continue
                    scalar_mapping[str(raw_symbol)] = amount
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

    @staticmethod
    def _extract_wallet_positions(data: Mapping[str, Any]) -> dict[str, float]:
        """Extract per-asset holdings from Roostoo SpotWallet/MarginWallet format."""
        positions: dict[str, float] = {}
        for wallet_key in ("SpotWallet", "MarginWallet"):
            wallet = data.get(wallet_key)
            if not isinstance(wallet, Mapping):
                continue
            for asset, holdings in wallet.items():
                if not isinstance(holdings, Mapping):
                    continue
                free = _coerce_float(holdings.get("Free")) or 0.0
                lock = _coerce_float(holdings.get("Lock")) or 0.0
                total = free + lock
                if total > 0:
                    positions[str(asset)] = total
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
        "--poll-once",
        action="store_true",
        help="Run startup/bootstrap plus one ticker poll, then exit.",
    )
    parser.add_argument(
        "--status",
        action="store_true",
        help="Print the current bot status without network calls.",
    )
    parser.add_argument(
        "--backtest-core-modules",
        action="store_true",
        help="Fetch Binance history and backtest momentum, mean reversion, and regime detection.",
    )
    parser.add_argument(
        "--symbols",
        help="Comma-separated symbol list for the Binance backtest. Defaults to the polled or live universe.",
    )
    parser.add_argument(
        "--history-days",
        type=int,
        default=180,
        help="Total backtest evaluation window in days. Default: 180.",
    )
    parser.add_argument(
        "--train-days",
        type=int,
        default=90,
        help="Training split length in days. Default: 90.",
    )
    parser.add_argument(
        "--validation-days",
        type=int,
        default=90,
        help="Validation split length in days. Default: 90.",
    )
    parser.add_argument(
        "--benchmark-symbol",
        default="BTCUSD",
        help="Benchmark symbol used for regime detection. Default: BTCUSD.",
    )
    parser.add_argument(
        "--historical-db-path",
        help="Optional sqlite cache path for Binance historical klines.",
    )
    return parser


if __name__ == "__main__":
    args = _build_cli_parser().parse_args()
    bot = TradingBot()

    if args.status:
        print(bot.status())
    elif args.poll_once:
        print(bot.poll_once())
    elif args.startup_check:
        print(bot.startup_check())
    elif args.backtest_core_modules:
        print(json.dumps(_run_core_module_backtest(bot, args), indent=2, sort_keys=True))
    else:
        bot.run_forever()

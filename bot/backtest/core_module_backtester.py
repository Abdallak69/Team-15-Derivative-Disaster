"""Backtest only the first three documented core modules."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from datetime import timedelta
from datetime import timezone
import math
from typing import Any
from typing import Sequence

import pandas as pd

from bot.data import BinanceFetcher
from bot.data import BinanceHistoryStore
from bot.data import normalize_binance_symbol
from bot.signals import build_mean_reversion_frame
from bot.signals import rank_assets_by_momentum
from bot.strategy import classify_regime_history


_DAYS_PER_YEAR = 365
_HOURS_PER_DAY = 24


def _to_timestamp_ms(value: datetime) -> int:
    return int(value.astimezone(timezone.utc).timestamp() * 1000)


def _isoformat_from_ms(value: int | None) -> str | None:
    if value is None:
        return None
    return datetime.fromtimestamp(value / 1000, tz=timezone.utc).isoformat()


def _profit_factor(returns: pd.Series) -> float | None:
    cleaned = returns.dropna().astype(float)
    gross_profit = float(cleaned[cleaned > 0.0].sum())
    gross_loss = abs(float(cleaned[cleaned < 0.0].sum()))
    if gross_loss == 0.0:
        return None
    return gross_profit / gross_loss


def _average_win_loss_ratio(returns: pd.Series) -> float | None:
    cleaned = returns.dropna().astype(float)
    wins = cleaned[cleaned > 0.0]
    losses = cleaned[cleaned < 0.0]
    if wins.empty or losses.empty:
        return None
    return float(wins.mean() / abs(losses.mean()))


def _annualized_sharpe(returns: pd.Series, *, periods_per_year: int) -> float | None:
    cleaned = returns.dropna().astype(float)
    if len(cleaned) < 2:
        return None
    volatility = float(cleaned.std(ddof=1))
    if volatility == 0.0:
        return None
    return float((cleaned.mean() / volatility) * math.sqrt(periods_per_year))


def _annualized_sortino(returns: pd.Series, *, periods_per_year: int) -> float | None:
    cleaned = returns.dropna().astype(float)
    if cleaned.empty:
        return None
    downside = cleaned[cleaned < 0.0]
    downside_deviation = float(downside.std(ddof=0)) if not downside.empty else 0.0
    if downside_deviation == 0.0:
        return None
    return float((cleaned.mean() / downside_deviation) * math.sqrt(periods_per_year))


def _max_drawdown(returns: pd.Series) -> float | None:
    cleaned = returns.dropna().astype(float)
    if cleaned.empty:
        return None
    equity_curve = (1.0 + cleaned).cumprod()
    running_peak = equity_curve.cummax()
    drawdown = (equity_curve / running_peak) - 1.0
    return float(drawdown.min())


def _return_metrics(
    returns: pd.Series,
    *,
    periods_per_year: int,
) -> dict[str, Any]:
    cleaned = returns.dropna().astype(float)
    if cleaned.empty:
        return {
            "average_return_pct": 0.0,
            "max_drawdown_pct": 0.0,
            "profit_factor": None,
            "sharpe": None,
            "sortino": None,
        }

    return {
        "average_return_pct": float(cleaned.mean()),
        "max_drawdown_pct": _max_drawdown(cleaned),
        "profit_factor": _profit_factor(cleaned),
        "sharpe": _annualized_sharpe(cleaned, periods_per_year=periods_per_year),
        "sortino": _annualized_sortino(cleaned, periods_per_year=periods_per_year),
    }


@dataclass(slots=True)
class CoreModuleBacktester:
    """Fetch/cache Binance history and evaluate the first three core modules."""

    config: dict[str, Any]
    history_store: BinanceHistoryStore
    fetcher: BinanceFetcher

    def run(
        self,
        *,
        symbols: Sequence[str],
        history_days: int = 180,
        train_days: int = 90,
        validation_days: int = 90,
        benchmark_symbol: str = "BTCUSD",
    ) -> dict[str, Any]:
        """Fetch history and backtest momentum, mean-reversion, and regime detection."""
        if history_days < train_days + validation_days:
            raise ValueError("history_days must be at least train_days + validation_days.")

        normalized_symbols = tuple(sorted({normalize_binance_symbol(symbol) for symbol in symbols}))
        normalized_benchmark = normalize_binance_symbol(benchmark_symbol)
        if normalized_benchmark not in normalized_symbols:
            normalized_symbols = (normalized_benchmark, *normalized_symbols)

        warmup_days = max(
            int(self._config_value("regime", "ema_slow_period", default=50)),
            int(self._config_value("regime", "volatility_baseline_period", default=60)),
            max(self._config_value("momentum", "lookback_days", default=[3, 5, 7])),
            int(self._config_value("mean_reversion", "max_hold_days", default=3)),
            60,
        )
        fetch_days = history_days + warmup_days + 2
        end_at = datetime.now(timezone.utc)
        start_at = end_at - timedelta(days=fetch_days)
        start_time_ms = _to_timestamp_ms(start_at)
        end_time_ms = _to_timestamp_ms(end_at)

        ingestion_summary = self._ensure_history(
            symbols=normalized_symbols,
            start_time_ms=start_time_ms,
            end_time_ms=end_time_ms,
        )

        daily_closes, daily_volumes, daily_counts = self._load_daily_panels(
            normalized_symbols,
            start_time_ms=start_time_ms,
        )
        if daily_closes.empty or normalized_benchmark not in daily_closes.columns:
            raise RuntimeError("Daily Binance history is missing for the requested benchmark symbol.")

        evaluation_dates = list(daily_closes.index[:-1])
        if len(evaluation_dates) < history_days:
            raise RuntimeError(
                f"Need at least {history_days} daily evaluation bars, found {len(evaluation_dates)}."
            )
        evaluation_dates = evaluation_dates[-history_days:]
        train_dates = evaluation_dates[:train_days]
        validation_dates = evaluation_dates[-validation_days:]

        momentum_report, momentum_daily_returns = self._backtest_momentum(
            closes=daily_closes,
            quote_volumes=daily_volumes,
            train_dates=train_dates,
            validation_dates=validation_dates,
        )
        mean_reversion_report, mean_reversion_daily_returns = self._backtest_mean_reversion(
            symbols=normalized_symbols,
            start_time_ms=start_time_ms,
            train_dates=train_dates,
            validation_dates=validation_dates,
        )
        regime_report = self._backtest_regime_detection(
            benchmark_prices=daily_closes[normalized_benchmark].dropna(),
            momentum_daily_returns=momentum_daily_returns,
            mean_reversion_daily_returns=mean_reversion_daily_returns,
            train_dates=train_dates,
            validation_dates=validation_dates,
        )

        return {
            "benchmark_symbol": normalized_benchmark,
            "history_days": history_days,
            "train_days": train_days,
            "validation_days": validation_days,
            "symbols": list(normalized_symbols),
            "data_window": {
                "requested_start": start_at.isoformat(),
                "requested_end": end_at.isoformat(),
                "train_start": train_dates[0].isoformat(),
                "train_end": train_dates[-1].isoformat(),
                "validation_start": validation_dates[0].isoformat(),
                "validation_end": validation_dates[-1].isoformat(),
            },
            "ingestion": ingestion_summary,
            "coverage": {
                "daily_bars_by_symbol": daily_counts,
            },
            "momentum": momentum_report,
            "mean_reversion": mean_reversion_report,
            "regime_detection": regime_report,
        }

    def _ensure_history(
        self,
        *,
        symbols: Sequence[str],
        start_time_ms: int,
        end_time_ms: int,
    ) -> dict[str, Any]:
        self.history_store.initialize()

        fetched_counts: dict[str, int] = {"1d": 0, "1h": 0}
        cached_ranges: dict[str, dict[str, dict[str, str | None]]] = {}
        for interval in ("1d", "1h"):
            interval_ms = self.fetcher.interval_to_milliseconds(interval)
            interval_ranges: dict[str, dict[str, str | None]] = {}
            for symbol in symbols:
                first_cached_ms, last_cached_ms = self.history_store.get_time_range(
                    symbol=symbol,
                    interval=interval,
                )
                interval_ranges[symbol] = {
                    "first_open_time": _isoformat_from_ms(first_cached_ms),
                    "last_open_time": _isoformat_from_ms(last_cached_ms),
                }

                ranges_to_fetch: list[tuple[int, int]] = []
                if first_cached_ms is None or last_cached_ms is None:
                    ranges_to_fetch.append((start_time_ms, end_time_ms))
                else:
                    if first_cached_ms > start_time_ms:
                        ranges_to_fetch.append((start_time_ms, first_cached_ms - interval_ms))
                    if last_cached_ms < end_time_ms - interval_ms:
                        ranges_to_fetch.append((last_cached_ms + interval_ms, end_time_ms))

                for fetch_start_ms, fetch_end_ms in ranges_to_fetch:
                    if fetch_start_ms > fetch_end_ms:
                        continue
                    klines = self.fetcher.fetch_historical_klines(
                        symbol=symbol,
                        interval=interval,
                        start_time_ms=fetch_start_ms,
                        end_time_ms=fetch_end_ms,
                    )
                    fetched_counts[interval] += self.history_store.upsert_klines(klines)

            cached_ranges[interval] = interval_ranges

        return {
            "db_path": str(self.history_store.db_path),
            "fetched_rows": fetched_counts,
            "cached_ranges_before_fetch": cached_ranges,
        }

    def _load_daily_panels(
        self,
        symbols: Sequence[str],
        *,
        start_time_ms: int,
    ) -> tuple[pd.DataFrame, pd.DataFrame, dict[str, int]]:
        close_frames: list[pd.Series] = []
        volume_frames: list[pd.Series] = []
        counts: dict[str, int] = {}

        for symbol in symbols:
            frame = self._load_symbol_frame(symbol=symbol, interval="1d", start_time_ms=start_time_ms)
            counts[symbol] = len(frame)
            if frame.empty:
                continue
            close_frames.append(frame["close"].rename(symbol))
            volume_frames.append(frame["quote_volume"].rename(symbol))

        daily_closes = pd.concat(close_frames, axis=1).sort_index() if close_frames else pd.DataFrame()
        daily_volumes = pd.concat(volume_frames, axis=1).sort_index() if volume_frames else pd.DataFrame()
        return daily_closes, daily_volumes, counts

    def _load_symbol_frame(
        self,
        *,
        symbol: str,
        interval: str,
        start_time_ms: int,
    ) -> pd.DataFrame:
        rows = self.history_store.fetch_klines(
            symbol=symbol,
            interval=interval,
            start_time_ms=start_time_ms,
        )
        if not rows:
            return pd.DataFrame(
                columns=["open", "high", "low", "close", "volume", "quote_volume", "trade_count"]
            )

        frame = pd.DataFrame.from_records(rows)
        frame["open_time"] = pd.to_datetime(frame["open_time_ms"], unit="ms", utc=True)
        frame = frame.set_index("open_time").sort_index()
        return frame[
            ["open", "high", "low", "close", "volume", "quote_volume", "trade_count"]
        ].astype(float)

    def _backtest_momentum(
        self,
        *,
        closes: pd.DataFrame,
        quote_volumes: pd.DataFrame,
        train_dates: Sequence[pd.Timestamp],
        validation_dates: Sequence[pd.Timestamp],
    ) -> tuple[dict[str, Any], pd.Series]:
        lookbacks = tuple(
            int(value) for value in self._config_value("momentum", "lookback_days", default=[3, 5, 7])
        )
        rsi_threshold = float(self._config_value("momentum", "rsi_threshold", default=45.0))
        top_n_assets = int(self._config_value("momentum", "top_n_assets", default=8))
        min_volume_usd = float(
            self._config_value("momentum", "min_volume_usd", default=10_000_000.0)
        )

        returns_by_day: dict[pd.Timestamp, float] = {}
        selections_by_day: dict[pd.Timestamp, int] = {}
        symbols_by_day: dict[pd.Timestamp, list[str]] = {}

        for index_position in range(len(closes.index) - 1):
            current_date = closes.index[index_position]
            next_date = closes.index[index_position + 1]
            signals = rank_assets_by_momentum(
                closes.iloc[: index_position + 1],
                quote_volumes.iloc[: index_position + 1],
                lookback_periods=lookbacks,
                rsi_threshold=rsi_threshold,
                min_volume_usd=min_volume_usd,
                top_n_assets=top_n_assets,
            )
            selected_symbols = [signal.symbol for signal in signals]
            forward_returns = []
            for symbol in selected_symbols:
                current_price = closes.at[current_date, symbol]
                next_price = closes.at[next_date, symbol]
                if pd.isna(current_price) or pd.isna(next_price) or float(current_price) == 0.0:
                    continue
                forward_returns.append((float(next_price) / float(current_price)) - 1.0)

            returns_by_day[current_date] = (
                float(sum(forward_returns) / len(forward_returns)) if forward_returns else 0.0
            )
            selections_by_day[current_date] = len(selected_symbols)
            symbols_by_day[current_date] = selected_symbols

        return_series = pd.Series(returns_by_day).sort_index()
        selection_series = pd.Series(selections_by_day).sort_index()

        return {
            "train": self._summarize_momentum_split(
                return_series.reindex(train_dates),
                selection_series.reindex(train_dates).fillna(0),
                symbols_by_day,
            ),
            "validation": self._summarize_momentum_split(
                return_series.reindex(validation_dates),
                selection_series.reindex(validation_dates).fillna(0),
                symbols_by_day,
            ),
        }, return_series

    def _summarize_momentum_split(
        self,
        returns: pd.Series,
        selection_counts: pd.Series,
        symbols_by_day: dict[pd.Timestamp, list[str]],
    ) -> dict[str, Any]:
        invested_mask = selection_counts.astype(int) > 0
        invested_returns = returns[invested_mask]
        symbol_frequency: dict[str, int] = {}
        for date in returns.index:
            for symbol in symbols_by_day.get(date, []):
                symbol_frequency[symbol] = symbol_frequency.get(symbol, 0) + 1

        summary = _return_metrics(returns.fillna(0.0), periods_per_year=_DAYS_PER_YEAR)
        summary.update(
            {
                "evaluated_days": int(len(returns)),
                "invested_days": int(invested_mask.sum()),
                "average_selected_assets": float(selection_counts[invested_mask].mean())
                if invested_mask.any()
                else 0.0,
                "hit_rate": float((invested_returns > 0.0).mean()) if not invested_returns.empty else None,
                "average_win_loss_ratio": _average_win_loss_ratio(invested_returns),
                "most_frequent_symbols": [
                    symbol
                    for symbol, _ in sorted(
                        symbol_frequency.items(),
                        key=lambda item: item[1],
                        reverse=True,
                    )[:5]
                ],
            }
        )
        return summary

    def _backtest_mean_reversion(
        self,
        *,
        symbols: Sequence[str],
        start_time_ms: int,
        train_dates: Sequence[pd.Timestamp],
        validation_dates: Sequence[pd.Timestamp],
    ) -> tuple[dict[str, Any], pd.Series]:
        rsi_oversold = float(self._config_value("mean_reversion", "rsi_oversold", default=30.0))
        bollinger_period = int(self._config_value("mean_reversion", "bollinger_period", default=20))
        bollinger_std = float(self._config_value("mean_reversion", "bollinger_std", default=2.0))
        min_volume_usd = float(
            self._config_value("mean_reversion", "min_volume_usd", default=10_000_000.0)
        )
        max_hold_days = int(self._config_value("mean_reversion", "max_hold_days", default=3))
        stop_loss_pct = float(self._config_value("mean_reversion", "stop_loss_pct", default=0.05))
        hold_bars = max_hold_days * _HOURS_PER_DAY

        trades: list[dict[str, Any]] = []
        for symbol in symbols:
            frame = self._load_symbol_frame(symbol=symbol, interval="1h", start_time_ms=start_time_ms)
            if frame.empty:
                continue

            indicator_frame = build_mean_reversion_frame(
                frame["close"],
                frame["quote_volume"],
                rsi_oversold=rsi_oversold,
                bollinger_period=bollinger_period,
                bollinger_std=bollinger_std,
            )

            position_index = 0
            while position_index < len(frame.index) - 1:
                current = indicator_frame.iloc[position_index]
                if (
                    pd.isna(current["signal_strength"])
                    or pd.isna(current["moving_average"])
                    or float(current["signal_strength"]) <= 0.0
                    or float(current["volume_24h"]) < min_volume_usd
                ):
                    position_index += 1
                    continue

                entry_time = frame.index[position_index]
                entry_price = float(current["price"])
                exit_index = min(position_index + hold_bars, len(frame.index) - 1)
                exit_reason = "time"

                for candidate_index in range(position_index + 1, exit_index + 1):
                    candidate = indicator_frame.iloc[candidate_index]
                    current_price = float(candidate["price"])
                    moving_average = float(candidate["moving_average"]) if not pd.isna(candidate["moving_average"]) else math.nan
                    if not math.isnan(moving_average) and current_price >= moving_average:
                        exit_index = candidate_index
                        exit_reason = "mean"
                        break
                    if (current_price / entry_price) - 1.0 <= -stop_loss_pct:
                        exit_index = candidate_index
                        exit_reason = "stop"
                        break

                exit_time = frame.index[exit_index]
                exit_price = float(indicator_frame.iloc[exit_index]["price"])
                trades.append(
                    {
                        "symbol": symbol,
                        "open_time": entry_time,
                        "open_date": entry_time.normalize(),
                        "close_time": exit_time,
                        "close_date": exit_time.normalize(),
                        "holding_hours": int((exit_time - entry_time).total_seconds() // 3600),
                        "return_pct": (exit_price / entry_price) - 1.0,
                        "exit_reason": exit_reason,
                        "signal_strength": float(current["signal_strength"]),
                    }
                )
                position_index = exit_index + 1

        trades_frame = pd.DataFrame.from_records(trades)
        if trades_frame.empty:
            empty_summary = {
                "train": self._summarize_mean_reversion_split(pd.DataFrame()),
                "validation": self._summarize_mean_reversion_split(pd.DataFrame()),
            }
            return empty_summary, pd.Series(dtype=float)

        daily_returns = trades_frame.groupby("close_date")["return_pct"].mean().sort_index()
        train_frame = trades_frame[trades_frame["close_date"].isin(train_dates)]
        validation_frame = trades_frame[trades_frame["close_date"].isin(validation_dates)]
        return {
            "train": self._summarize_mean_reversion_split(train_frame),
            "validation": self._summarize_mean_reversion_split(validation_frame),
        }, daily_returns

    def _summarize_mean_reversion_split(self, trades: pd.DataFrame) -> dict[str, Any]:
        if trades.empty:
            return {
                "average_reversion_time_hours": None,
                "average_return_pct": 0.0,
                "profit_factor": None,
                "reversion_probability": None,
                "trade_count": 0,
                "win_rate": None,
            }

        returns = trades["return_pct"].astype(float)
        reverted = trades[trades["exit_reason"] == "mean"]
        return {
            "average_reversion_time_hours": float(reverted["holding_hours"].mean())
            if not reverted.empty
            else None,
            "average_return_pct": float(returns.mean()),
            "profit_factor": _profit_factor(returns),
            "reversion_probability": float((trades["exit_reason"] == "mean").mean()),
            "trade_count": int(len(trades)),
            "win_rate": float((returns > 0.0).mean()),
        }

    def _backtest_regime_detection(
        self,
        *,
        benchmark_prices: pd.Series,
        momentum_daily_returns: pd.Series,
        mean_reversion_daily_returns: pd.Series,
        train_dates: Sequence[pd.Timestamp],
        validation_dates: Sequence[pd.Timestamp],
    ) -> dict[str, Any]:
        regime_frame = classify_regime_history(
            benchmark_prices,
            ema_fast_period=int(self._config_value("regime", "ema_fast_period", default=20)),
            ema_slow_period=int(self._config_value("regime", "ema_slow_period", default=50)),
            volatility_lookback=int(self._config_value("regime", "volatility_lookback", default=14)),
            volatility_baseline_period=int(
                self._config_value("regime", "volatility_baseline_period", default=60)
            ),
            volatility_threshold_multiplier=float(
                self._config_value("regime", "volatility_threshold_multiplier", default=1.5)
            ),
            confirmation_periods=int(
                self._config_value("regime", "confirmation_periods", default=2)
            ),
        )

        forward_benchmark_returns = benchmark_prices.pct_change().shift(-1)
        aligned = regime_frame.copy()
        aligned["momentum_return"] = momentum_daily_returns.reindex(aligned.index).fillna(0.0)
        aligned["mean_reversion_return"] = mean_reversion_daily_returns.reindex(aligned.index).fillna(0.0)
        aligned["benchmark_forward_return"] = forward_benchmark_returns.reindex(aligned.index)
        aligned["is_correct"] = aligned.apply(self._is_regime_classification_correct, axis=1)

        return {
            "train": self._summarize_regime_split(aligned[aligned.index.isin(train_dates)]),
            "validation": self._summarize_regime_split(aligned[aligned.index.isin(validation_dates)]),
        }

    @staticmethod
    def _is_regime_classification_correct(row: pd.Series) -> bool:
        active_regime = row.get("active_regime")
        if active_regime == "bull":
            return float(row.get("momentum_return", 0.0)) > 0.0
        if active_regime == "ranging":
            return float(row.get("mean_reversion_return", 0.0)) > 0.0
        if active_regime == "bear":
            benchmark_forward_return = row.get("benchmark_forward_return")
            return bool(pd.notna(benchmark_forward_return) and float(benchmark_forward_return) <= 0.0)
        return False

    def _summarize_regime_split(self, frame: pd.DataFrame) -> dict[str, Any]:
        evaluated = frame[frame["active_regime"] != "unknown"]
        if evaluated.empty:
            return {
                "accuracy": None,
                "evaluated_days": 0,
                "regime_distribution": {},
            }

        regime_distribution = {
            str(regime): int(count)
            for regime, count in evaluated["active_regime"].value_counts().sort_index().items()
        }
        regime_accuracy = {
            str(regime): float(group["is_correct"].mean())
            for regime, group in evaluated.groupby("active_regime")
        }
        return {
            "accuracy": float(evaluated["is_correct"].mean()),
            "evaluated_days": int(len(evaluated)),
            "regime_accuracy": regime_accuracy,
            "regime_distribution": regime_distribution,
        }

    def _config_value(self, section: str, key: str, *, default: Any) -> Any:
        section_values = self.config.get(section, {})
        if not isinstance(section_values, dict):
            return default
        return section_values.get(key, default)

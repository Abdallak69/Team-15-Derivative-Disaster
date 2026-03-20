"""Synthetic coverage for the staged core-module backtest."""

from __future__ import annotations

from datetime import datetime
from datetime import timedelta
from datetime import timezone
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import pandas as pd

from bot.backtest import CoreModuleBacktester
from bot.data import BinanceFetcher
from bot.data import BinanceHistoryStore
from bot.data.binance_fetcher import BinanceKline


def _build_kline(
    symbol: str,
    interval: str,
    open_time: datetime,
    close_price: float,
    quote_volume: float = 20_000_000.0,
) -> BinanceKline:
    interval_ms = BinanceFetcher.interval_to_milliseconds(interval)
    open_time_ms = int(open_time.timestamp() * 1000)
    return BinanceKline(
        symbol=symbol,
        interval=interval,
        open_time_ms=open_time_ms,
        close_time_ms=open_time_ms + interval_ms - 1,
        open=close_price,
        high=close_price + 1.0,
        low=close_price - 1.0,
        close=close_price,
        volume=100.0,
        quote_volume=quote_volume,
        trade_count=10,
        taker_buy_base_volume=50.0,
        taker_buy_quote_volume=quote_volume / 2.0,
    )


class FakeFetcher(BinanceFetcher):
    def __init__(self) -> None:
        super().__init__(session=object())

    def fetch_historical_klines(self, *, symbol: str, interval: str, start_time_ms: int, end_time_ms: int) -> list[BinanceKline]:
        return []


class CoreModuleBacktesterTests(unittest.TestCase):
    def test_run_returns_reports_for_first_three_modules(self) -> None:
        config = {
            "regime": {
                "ema_fast_period": 3,
                "ema_slow_period": 5,
                "volatility_lookback": 2,
                "volatility_baseline_period": 4,
                "volatility_threshold_multiplier": 10.0,
                "confirmation_periods": 2,
            },
            "momentum": {
                "lookback_periods": [1, 2],
                "rsi_threshold": 0.0,
                "top_n_assets": 1,
            },
            "mean_reversion": {
                "rsi_oversold": 45.0,
                "bollinger_period": 5,
                "bollinger_std": 1.0,
                "min_volume_usd": 0.0,
                "max_hold_days": 1,
                "stop_loss_pct": 0.20,
            },
        }

        with tempfile.TemporaryDirectory() as tmp_dir:
            store = BinanceHistoryStore(Path(tmp_dir) / "binance_history.db")
            store.initialize()
            start_daily = datetime.now(timezone.utc) - timedelta(days=90)
            daily_klines: list[BinanceKline] = []
            hourly_klines: list[BinanceKline] = []

            for day in range(90):
                open_time = start_daily + timedelta(days=day)
                daily_klines.append(_build_kline("BTCUSDT", "1d", open_time, 100.0 + (day * 1.5)))
                daily_klines.append(_build_kline("ETHUSDT", "1d", open_time, 100.0 + ((day % 5) - 2) * 2.0))

            start_hourly = datetime.now(timezone.utc) - timedelta(days=90)
            for hour in range(90 * 24):
                open_time = start_hourly + timedelta(hours=hour)
                btc_price = 100.0 + (hour * 0.05)
                eth_cycle = hour % 24
                eth_price = 100.0 if eth_cycle < 16 else 92.0 + ((eth_cycle - 16) * 2.0)
                hourly_klines.append(_build_kline("BTCUSDT", "1h", open_time, btc_price))
                hourly_klines.append(_build_kline("ETHUSDT", "1h", open_time, eth_price))

            store.upsert_klines(daily_klines)
            store.upsert_klines(hourly_klines)

            backtester = CoreModuleBacktester(
                config=config,
                history_store=store,
                fetcher=FakeFetcher(),
            )

            report = backtester.run(
                symbols=("BTCUSD", "ETHUSD"),
                history_days=10,
                train_days=5,
                validation_days=5,
                benchmark_symbol="BTCUSD",
            )

        self.assertEqual(report["benchmark_symbol"], "BTCUSDT")
        self.assertIn("momentum", report)
        self.assertIn("mean_reversion", report)
        self.assertIn("regime_detection", report)
        self.assertEqual(report["momentum"]["validation"]["evaluated_days"], 5)

    def test_mean_reversion_attributes_realized_returns_to_close_date(self) -> None:
        config = {
            "mean_reversion": {
                "rsi_oversold": 30.0,
                "bollinger_period": 20,
                "bollinger_std": 2.0,
                "min_volume_usd": 0.0,
                "max_hold_days": 2,
                "stop_loss_pct": 0.20,
            }
        }

        with tempfile.TemporaryDirectory() as tmp_dir:
            backtester = CoreModuleBacktester(
                config=config,
                history_store=BinanceHistoryStore(Path(tmp_dir) / "binance_history.db"),
                fetcher=FakeFetcher(),
            )
            start = datetime(2026, 1, 1, tzinfo=timezone.utc)
            index = pd.date_range(start=start, periods=30, freq="h", tz="UTC")
            frame = pd.DataFrame(
                {
                    "open": [100.0] * len(index),
                    "high": [101.0] * len(index),
                    "low": [99.0] * len(index),
                    "close": [100.0] * len(index),
                    "volume": [1.0] * len(index),
                    "quote_volume": [1_000_000.0] * len(index),
                    "trade_count": [1.0] * len(index),
                },
                index=index,
            )
            indicator_frame = pd.DataFrame(
                {
                    "price": [100.0] + ([95.0] * 24) + [101.0] + ([101.0] * 4),
                    "moving_average": [110.0] + ([100.0] * 29),
                    "lower_band": [90.0] * len(index),
                    "rsi": [20.0] * len(index),
                    "volume_24h": [1_000_000.0] * len(index),
                    "signal_strength": [1.0] + ([0.0] * 29),
                },
                index=index,
            )

            with patch.object(CoreModuleBacktester, "_load_symbol_frame", return_value=frame):
                with patch(
                    "bot.backtest.core_module_backtester.build_mean_reversion_frame",
                    return_value=indicator_frame,
                ):
                    report, daily_returns = backtester._backtest_mean_reversion(
                        symbols=("BTCUSDT",),
                        start_time_ms=0,
                        train_dates=[index[0].normalize()],
                        validation_dates=[index[25].normalize()],
                    )

        self.assertEqual(list(daily_returns.index), [index[25].normalize()])
        self.assertEqual(report["train"]["trade_count"], 0)
        self.assertEqual(report["validation"]["trade_count"], 1)


if __name__ == "__main__":
    unittest.main()

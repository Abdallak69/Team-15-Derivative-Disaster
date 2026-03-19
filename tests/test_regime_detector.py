"""Tests for regime detection helpers."""

from __future__ import annotations

import unittest

import pandas as pd

from bot.strategy.regime_detector import classify_regime_history
from bot.strategy.regime_detector import detect_regime


class RegimeDetectorTests(unittest.TestCase):
    def test_detect_regime_uses_price_trend_and_volatility(self) -> None:
        self.assertEqual(
            detect_regime(ema_fast=105.0, ema_slow=100.0, volatility=0.01, volatility_threshold=0.02, price=110.0),
            "bull",
        )
        self.assertEqual(
            detect_regime(ema_fast=95.0, ema_slow=100.0, volatility=0.03, volatility_threshold=0.02, price=90.0),
            "bear",
        )

    def test_classify_regime_history_requires_confirmed_switch(self) -> None:
        prices = pd.Series(
            [100.0, 102.0, 104.0, 106.0, 108.0, 110.0, 112.0, 114.0, 90.0, 88.0, 86.0],
            index=pd.date_range("2026-01-01", periods=11, freq="D", tz="UTC"),
        )

        frame = classify_regime_history(
            prices,
            ema_fast_period=2,
            ema_slow_period=3,
            volatility_lookback=2,
            volatility_baseline_period=2,
            volatility_threshold_multiplier=100.0,
            confirmation_periods=2,
        )

        self.assertEqual(frame["base_regime"].iloc[-2:].tolist(), ["bear", "bear"])
        self.assertEqual(frame["active_regime"].iloc[-3], "bull")
        self.assertEqual(frame["active_regime"].iloc[-2], "bear")
        self.assertEqual(frame["active_regime"].iloc[-1], "bear")


if __name__ == "__main__":
    unittest.main()

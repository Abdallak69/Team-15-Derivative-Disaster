"""Tests for the metrics tracker module."""

from __future__ import annotations

import unittest

from bot.monitoring.metrics_tracker import (
    MetricsSnapshot,
    MetricsTracker,
    compute_drawdown,
    compute_return,
)


class ComputeHelperTests(unittest.TestCase):
    def test_drawdown_from_peak(self) -> None:
        self.assertAlmostEqual(compute_drawdown(100.0, 95.0), 0.05)

    def test_drawdown_clamps_to_zero(self) -> None:
        self.assertAlmostEqual(compute_drawdown(100.0, 110.0), 0.0)

    def test_drawdown_handles_zero_peak(self) -> None:
        self.assertAlmostEqual(compute_drawdown(0.0, 50.0), 0.0)

    def test_return_from_start(self) -> None:
        self.assertAlmostEqual(compute_return(100.0, 110.0), 0.10)

    def test_return_handles_zero_start(self) -> None:
        self.assertAlmostEqual(compute_return(0.0, 50.0), 0.0)


class MetricsTrackerTests(unittest.TestCase):
    def test_sharpe_requires_minimum_data(self) -> None:
        tracker = MetricsTracker()
        tracker.record_daily_return(0.01)
        self.assertIsNone(tracker.compute_sharpe())

    def test_sharpe_with_zero_returns_is_none(self) -> None:
        tracker = MetricsTracker()
        for _ in range(10):
            tracker.record_daily_return(0.0)
        self.assertIsNone(tracker.compute_sharpe())

    def test_sharpe_positive_for_positive_returns(self) -> None:
        tracker = MetricsTracker()
        returns = [0.01, 0.005, 0.008, 0.012, -0.002, 0.003, 0.007, 0.009, 0.004, 0.006]
        for r in returns:
            tracker.record_daily_return(r)
        sharpe = tracker.compute_sharpe()
        self.assertIsNotNone(sharpe)
        self.assertGreater(sharpe, 0)

    def test_sortino_ignores_upside_volatility(self) -> None:
        tracker = MetricsTracker()
        for r in [0.01, 0.02, 0.03, 0.04, -0.001]:
            tracker.record_daily_return(r)
        sortino = tracker.compute_sortino()
        self.assertIsNotNone(sortino)
        self.assertGreater(sortino, 0)

    def test_calmar_with_no_drawdown_is_none(self) -> None:
        tracker = MetricsTracker()
        for _ in range(5):
            tracker.record_daily_return(0.01)
        self.assertIsNone(tracker.compute_calmar(0.0))

    def test_calmar_positive_with_drawdown(self) -> None:
        tracker = MetricsTracker()
        for r in [0.01, -0.005, 0.008, 0.003]:
            tracker.record_daily_return(r)
        calmar = tracker.compute_calmar(0.01)
        self.assertIsNotNone(calmar)
        self.assertGreater(calmar, 0)

    def test_max_drawdown_from_returns(self) -> None:
        tracker = MetricsTracker()
        for r in [0.10, -0.05, -0.03, 0.02]:
            tracker.record_daily_return(r)
        dd = tracker.compute_max_drawdown()
        self.assertGreater(dd, 0.0)

    def test_compute_all_returns_snapshot(self) -> None:
        tracker = MetricsTracker()
        for r in [0.01, -0.002, 0.005, 0.003, -0.001]:
            tracker.record_daily_return(r)
        snap = tracker.compute_all()
        self.assertIsInstance(snap, MetricsSnapshot)
        self.assertEqual(snap.num_days, 5)
        self.assertGreater(snap.total_return, 0)

    def test_max_history_trims_old_returns(self) -> None:
        tracker = MetricsTracker(max_history=5)
        for i in range(10):
            tracker.record_daily_return(float(i) * 0.001)
        self.assertEqual(len(tracker.daily_returns), 5)
        self.assertAlmostEqual(tracker.daily_returns[0], 0.005)

"""Portfolio metric computation — Sharpe, Sortino, Calmar, drawdown, return."""

from __future__ import annotations

import math
from dataclasses import dataclass, field

def compute_drawdown(peak_value: float, current_value: float) -> float:
    """Return drawdown as a fraction of peak value."""
    if peak_value <= 0:
        return 0.0
    return max(0.0, (peak_value - current_value) / peak_value)


def compute_return(start_value: float, current_value: float) -> float:
    """Return cumulative return as a fraction of starting value."""
    if start_value <= 0:
        return 0.0
    return (current_value - start_value) / start_value


@dataclass(frozen=True, slots=True)
class MetricsSnapshot:
    """Point-in-time performance metrics."""

    total_return: float
    max_drawdown: float
    sharpe: float | None
    sortino: float | None
    calmar: float | None
    num_days: int


@dataclass(slots=True)
class MetricsTracker:
    """Accumulates daily returns and computes running risk-adjusted metrics.

    All ratio computations follow the formulas in Doc 06 Section 5:
    - Sharpe  = (mean_r / std_r) * sqrt(365)             [ddof=1]
    - Sortino = (mean_r / downside_deviation) * sqrt(365) [DD uses all periods]
    - Calmar  = annualized_return / |max_drawdown|
    """

    daily_returns: list[float] = field(default_factory=list)
    max_history: int = 365
    _annualization_factor: int = 365

    def record_daily_return(self, daily_return: float) -> None:
        """Append a single day's return (as a decimal fraction, e.g. 0.01 = 1%)."""
        self.daily_returns.append(daily_return)
        if len(self.daily_returns) > self.max_history:
            self.daily_returns = self.daily_returns[-self.max_history:]

    def compute_sharpe(self) -> float | None:
        """Annualized Sharpe ratio using sample std (ddof=1)."""
        if len(self.daily_returns) < 2:
            return None
        mean_r = sum(self.daily_returns) / len(self.daily_returns)
        variance = sum((r - mean_r) ** 2 for r in self.daily_returns) / (len(self.daily_returns) - 1)
        std_r = math.sqrt(variance)
        if std_r == 0.0:
            return None
        return (mean_r / std_r) * math.sqrt(self._annualization_factor)

    def compute_sortino(self) -> float | None:
        """Annualized Sortino ratio with downside deviation computed over all periods."""
        n = len(self.daily_returns)
        if n < 2:
            return None
        mean_r = sum(self.daily_returns) / n
        downside_sq_sum = sum(r ** 2 for r in self.daily_returns if r < 0.0)
        dd = math.sqrt(downside_sq_sum / n)
        if dd == 0.0:
            return None
        return (mean_r / dd) * math.sqrt(self._annualization_factor)

    def compute_calmar(self, max_drawdown: float) -> float | None:
        """Calmar ratio: annualized return divided by max drawdown."""
        if max_drawdown <= 0 or not self.daily_returns:
            return None
        mean_r = sum(self.daily_returns) / len(self.daily_returns)
        annualized_return = mean_r * self._annualization_factor
        return annualized_return / max_drawdown

    def compute_max_drawdown(self) -> float:
        """Compute max drawdown from the daily return series."""
        if not self.daily_returns:
            return 0.0
        peak = 1.0
        max_dd = 0.0
        equity = 1.0
        for r in self.daily_returns:
            equity *= (1.0 + r)
            if equity > peak:
                peak = equity
            dd = (peak - equity) / peak if peak > 0 else 0.0
            if dd > max_dd:
                max_dd = dd
        return max_dd

    def compute_all(self) -> MetricsSnapshot:
        """Return a full metrics snapshot."""
        n = len(self.daily_returns)
        total_ret = 1.0
        for r in self.daily_returns:
            total_ret *= (1.0 + r)
        total_ret -= 1.0

        max_dd = self.compute_max_drawdown()

        return MetricsSnapshot(
            total_return=total_ret,
            max_drawdown=max_dd,
            sharpe=self.compute_sharpe(),
            sortino=self.compute_sortino(),
            calmar=self.compute_calmar(max_dd),
            num_days=n,
        )

"""Portfolio metric helpers."""

from __future__ import annotations


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


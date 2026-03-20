"""Pairs rotation helpers — cointegration-based capital rotation."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping, Sequence

import numpy as np
import pandas as pd
from scipy import stats


def rank_pairs_by_spread(spreads: Mapping[str, float]) -> list[str]:
    """Return pairs ordered from the most negative spread upward."""
    return [pair for pair, _ in sorted(spreads.items(), key=lambda item: item[1])]


@dataclass(frozen=True, slots=True)
class PairSignal:
    """Cointegration-based pair trading signal."""

    asset_a: str
    asset_b: str
    z_score: float
    spread: float
    half_life: float
    hedge_ratio: float
    adf_pvalue: float


def _compute_hedge_ratio(series_a: pd.Series, series_b: pd.Series) -> float:
    """OLS hedge ratio: regress series_a on series_b."""
    b_vals = series_b.values.astype(float)
    a_vals = series_a.values.astype(float)
    if np.std(b_vals) == 0.0:
        return 0.0
    slope, _, _, _, _ = stats.linregress(b_vals, a_vals)
    return float(slope)


def _compute_spread(
    series_a: pd.Series, series_b: pd.Series, hedge_ratio: float
) -> pd.Series:
    """Compute the spread: A - hedge_ratio * B."""
    return series_a.astype(float) - hedge_ratio * series_b.astype(float)


def _estimate_half_life(spread: pd.Series) -> float:
    """Estimate mean-reversion half-life using an AR(1) model on the spread."""
    lagged = spread.shift(1).dropna()
    delta = spread.diff().dropna()
    common_idx = lagged.index.intersection(delta.index)
    if len(common_idx) < 3:
        return float("inf")
    lagged_vals = lagged.loc[common_idx].values.astype(float)
    delta_vals = delta.loc[common_idx].values.astype(float)
    slope, _, _, _, _ = stats.linregress(lagged_vals, delta_vals)
    if slope >= 0.0:
        return float("inf")
    return float(-np.log(2) / slope)


_MACKINNON_CV_C: list[tuple[int, float, float, float]] = [
    (25, -3.75, -3.00, -2.63),
    (50, -3.58, -2.93, -2.60),
    (100, -3.50, -2.89, -2.58),
    (250, -3.46, -2.87, -2.57),
    (500, -3.44, -2.86, -2.57),
    (10_000, -3.43, -2.86, -2.57),
]


def _interpolate_critical_value(n: int, level_idx: int) -> float:
    """Linearly interpolate MacKinnon critical values for the 'c' model."""
    table = _MACKINNON_CV_C
    if n <= table[0][0]:
        return table[0][level_idx + 1]
    if n >= table[-1][0]:
        return table[-1][level_idx + 1]
    for k in range(len(table) - 1):
        n_lo, n_hi = table[k][0], table[k + 1][0]
        if n_lo <= n <= n_hi:
            frac = (n - n_lo) / (n_hi - n_lo)
            return table[k][level_idx + 1] * (1 - frac) + table[k + 1][level_idx + 1] * frac
    return table[-1][level_idx + 1]


def _adf_test_pvalue(spread: pd.Series) -> float:
    """Augmented Dickey-Fuller unit root test using MacKinnon critical values.

    Computes the ADF t-statistic via OLS on delta(y) = phi * y_{t-1} + eps,
    then maps to an approximate p-value using the Dickey-Fuller distribution
    critical value table (constant, no trend).
    """
    spread_clean = spread.dropna()
    n = len(spread_clean)
    if n < 10:
        return 1.0
    lagged = spread_clean.shift(1).iloc[1:]
    delta = spread_clean.diff().iloc[1:]
    lagged_std = float(lagged.std())
    if lagged_std == 0.0:
        return 1.0
    slope, _, _, _, _ = stats.linregress(
        lagged.values.astype(float), delta.values.astype(float)
    )
    residuals = delta.values.astype(float) - (
        slope * lagged.values.astype(float)
        + float(np.mean(delta.values.astype(float) - slope * lagged.values.astype(float)))
    )
    se_slope = float(np.sqrt(np.sum(residuals ** 2) / max(n - 3, 1))) / (
        lagged_std * np.sqrt(max(n - 2, 1))
    )
    if se_slope == 0.0:
        return 1.0
    adf_stat = slope / se_slope

    cv_01 = _interpolate_critical_value(n, 0)
    cv_05 = _interpolate_critical_value(n, 1)
    cv_10 = _interpolate_critical_value(n, 2)

    if adf_stat <= cv_01:
        return 0.005
    if adf_stat <= cv_05:
        frac = (adf_stat - cv_01) / (cv_05 - cv_01) if cv_05 != cv_01 else 0.5
        return 0.01 + frac * 0.04
    if adf_stat <= cv_10:
        frac = (adf_stat - cv_05) / (cv_10 - cv_05) if cv_10 != cv_05 else 0.5
        return 0.05 + frac * 0.05
    return min(1.0, 0.10 + (adf_stat - cv_10) * 0.15)


def find_cointegrated_pairs(
    closes: pd.DataFrame,
    *,
    lookback: int = 60,
    adf_threshold: float = 0.05,
    min_half_life: float = 1.0,
    max_half_life: float = 30.0,
) -> list[PairSignal]:
    """Screen all unique symbol pairs for cointegration and return scored signals."""
    if closes.empty or len(closes) < lookback:
        return []

    window = closes.iloc[-lookback:]
    symbols = [col for col in window.columns if window[col].dropna().shape[0] >= lookback]
    signals: list[PairSignal] = []

    for i in range(len(symbols)):
        for j in range(i + 1, len(symbols)):
            sym_a, sym_b = symbols[i], symbols[j]
            series_a = window[sym_a].dropna()
            series_b = window[sym_b].dropna()
            common_idx = series_a.index.intersection(series_b.index)
            if len(common_idx) < lookback:
                continue

            series_a = series_a.loc[common_idx]
            series_b = series_b.loc[common_idx]

            hedge_ratio = _compute_hedge_ratio(series_a, series_b)
            spread = _compute_spread(series_a, series_b, hedge_ratio)
            p_value = _adf_test_pvalue(spread)
            if p_value > adf_threshold:
                continue

            half_life = _estimate_half_life(spread)
            if half_life < min_half_life or half_life > max_half_life:
                continue

            spread_mean = float(spread.mean())
            spread_std = float(spread.std())
            if spread_std == 0.0:
                continue
            z_score = (float(spread.iloc[-1]) - spread_mean) / spread_std

            signals.append(
                PairSignal(
                    asset_a=sym_a,
                    asset_b=sym_b,
                    z_score=z_score,
                    spread=float(spread.iloc[-1]),
                    half_life=half_life,
                    hedge_ratio=hedge_ratio,
                    adf_pvalue=p_value,
                )
            )

    return sorted(signals, key=lambda s: abs(s.z_score), reverse=True)


def pairs_rotation_weights(
    signals: Sequence[PairSignal],
    *,
    z_entry: float = 2.0,
    max_pairs: int = 3,
) -> dict[str, float]:
    """Convert cointegrated pair signals into target portfolio weight adjustments.

    When z_score < -z_entry: long asset_a, short asset_b (spread expected to rise).
    When z_score >  z_entry: short asset_a, long asset_b (spread expected to fall).
    """
    weights: dict[str, float] = {}
    selected = 0
    for signal in signals:
        if selected >= max_pairs:
            break
        strength = min(abs(signal.z_score) / z_entry, 2.0) if z_entry > 0 else 0.0
        if abs(signal.z_score) < z_entry:
            continue
        if signal.z_score < -z_entry:
            weights[signal.asset_a] = weights.get(signal.asset_a, 0.0) + strength
            weights[signal.asset_b] = weights.get(signal.asset_b, 0.0) - strength * 0.5
        elif signal.z_score > z_entry:
            weights[signal.asset_b] = weights.get(signal.asset_b, 0.0) + strength
            weights[signal.asset_a] = weights.get(signal.asset_a, 0.0) - strength * 0.5
        selected += 1
    return weights


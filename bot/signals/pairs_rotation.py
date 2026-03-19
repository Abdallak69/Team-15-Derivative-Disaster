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


def _adf_test_pvalue(spread: pd.Series) -> float:
    """Run an Augmented Dickey-Fuller style unit root test (simple ADF via OLS)."""
    spread_clean = spread.dropna()
    if len(spread_clean) < 10:
        return 1.0
    lagged = spread_clean.shift(1).iloc[1:]
    delta = spread_clean.diff().iloc[1:]
    if lagged.std() == 0.0:
        return 1.0
    slope, intercept, _, p_value, _ = stats.linregress(
        lagged.values.astype(float), delta.values.astype(float)
    )
    return float(p_value)


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


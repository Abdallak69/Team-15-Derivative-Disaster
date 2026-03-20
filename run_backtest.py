#!/usr/bin/env python3
"""Full backtesting plan — Team 15 Derivative Disaster.

Fetches 180 days of Binance public kline data, caches in SQLite, and runs:
  Phase 1 — Momentum rankings  (hit rate, win/loss, Sharpe, Sortino)
  Phase 2 — Mean-reversion     (reversion probability, profit factor)
  Phase 3 — Regime detection   (classification accuracy per regime)
  Phase 4 — Ensemble simulation (rolling Sharpe/Sortino/Calmar, weight optimisation)

Usage:  python run_backtest.py
"""

from __future__ import annotations

import json
import math
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Sequence

import numpy as np
import pandas as pd
import yaml

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

from bot.data.binance_fetcher import BinanceFetcher, normalize_binance_symbol
from bot.data.binance_history_store import BinanceHistoryStore
from bot.signals.momentum import rank_assets_by_momentum, calculate_rsi
from bot.signals.mean_reversion import build_mean_reversion_frame
from bot.signals.sector_rotation import sector_rotation_weights, classify_symbol
from bot.strategy.regime_detector import classify_regime_history, detect_regime
from bot.strategy.ensemble import ensemble_combine
from bot.strategy.portfolio_optimizer import normalize_weights, optimize_weights

UNIVERSE = [
    "BTCUSDT", "ETHUSDT", "BNBUSDT", "XRPUSDT", "ADAUSDT", "SOLUSDT",
    "DOGEUSDT", "DOTUSDT", "AVAXUSDT", "LINKUSDT", "MATICUSDT", "SHIBUSDT",
    "LTCUSDT", "UNIUSDT", "ATOMUSDT", "ETCUSDT", "XLMUSDT", "NEARUSDT",
    "ALGOUSDT", "FILUSDT", "ICPUSDT", "VETUSDT", "MANAUSDT", "SANDUSDT",
    "AXSUSDT", "AAVEUSDT", "EOSUSDT", "THETAUSDT", "FTMUSDT", "GRTUSDT",
    "XTZUSDT", "FLOWUSDT", "CHZUSDT", "GALAUSDT", "APEUSDT", "QNTUSDT",
    "LDOUSDT", "IMXUSDT", "OPUSDT", "ARBUSDT", "MKRUSDT", "SNXUSDT",
    "COMPUSDT", "CRVUSDT", "DYDXUSDT", "ZECUSDT", "DASHUSDT", "ENJUSDT",
    "BATUSDT", "LRCUSDT", "1INCHUSDT", "SUSHIUSDT", "YFIUSDT", "BCHUSDT",
    "TRXUSDT", "HBARUSDT", "APTUSDT", "EGLDUSDT", "GMTUSDT", "ROSEUSDT",
    "KAVAUSDT", "ZILUSDT", "RUNEUSDT", "INJUSDT", "SUIUSDT", "SEIUSDT",
]

HISTORY_DAYS = 180
TRAIN_DAYS = 90
VALIDATION_DAYS = 90
BENCHMARK = "BTCUSDT"
DB_PATH = ROOT / "data" / "binance_backtest.db"
REPORT_PATH = ROOT / "data" / "backtest_report.json"
DAYS_PER_YEAR = 365
HOURS_PER_DAY = 24


# ── Metric helpers ───────────────────────────────────────────────────

def ann_sharpe(returns: pd.Series, ppy: int = DAYS_PER_YEAR) -> float | None:
    c = returns.dropna().astype(float)
    if len(c) < 2:
        return None
    s = float(c.std(ddof=1))
    return None if s == 0 else float((c.mean() / s) * math.sqrt(ppy))


def ann_sortino(returns: pd.Series, ppy: int = DAYS_PER_YEAR) -> float | None:
    c = returns.dropna().astype(float)
    if c.empty:
        return None
    ds = c[c < 0]
    dd = float(ds.std(ddof=0)) if not ds.empty else 0.0
    return None if dd == 0 else float((c.mean() / dd) * math.sqrt(ppy))


def max_drawdown(returns: pd.Series) -> float | None:
    c = returns.dropna().astype(float)
    if c.empty:
        return None
    eq = (1.0 + c).cumprod()
    return float((eq / eq.cummax() - 1.0).min())


def calmar(returns: pd.Series, ppy: int = DAYS_PER_YEAR) -> float | None:
    c = returns.dropna().astype(float)
    if len(c) < 2:
        return None
    mdd = max_drawdown(c)
    if mdd is None or mdd == 0:
        return None
    return float(c.mean() * ppy / abs(mdd))


def profit_factor(returns: pd.Series) -> float | None:
    c = returns.dropna().astype(float)
    gp = float(c[c > 0].sum())
    gl = abs(float(c[c < 0].sum()))
    return None if gl == 0 else gp / gl


def total_return(returns: pd.Series) -> float:
    c = returns.dropna().astype(float)
    return float((1 + c).prod() - 1) if not c.empty else 0.0


# ── Formatting helpers ───────────────────────────────────────────────

def _pct(v: float | None) -> str:
    return f"{v * 100:+.2f}%" if v is not None else "N/A"


def _ratio(v: float | None) -> str:
    return f"{v:.3f}" if v is not None else "N/A"


def _f(v: float | None, decimals: int = 2) -> str:
    return f"{v:.{decimals}f}" if v is not None else "N/A"


def _hdr(title: str) -> str:
    return f"\n{'━' * 70}\n  {title}\n{'━' * 70}"


# ── Data loading ─────────────────────────────────────────────────────

def cfg(config: dict, section: str, key: str, default: Any = None) -> Any:
    sv = config.get(section, {})
    return sv.get(key, default) if isinstance(sv, dict) else default


def ingest_data(
    fetcher: BinanceFetcher,
    store: BinanceHistoryStore,
    symbols: list[str],
    start_ms: int,
    end_ms: int,
) -> dict[str, int]:
    totals: dict[str, int] = {"1d": 0, "1h": 0}
    interval_ms = {"1d": 86_400_000, "1h": 3_600_000}
    for idx, sym in enumerate(symbols, 1):
        for interval in ("1d", "1h"):
            first, last = store.get_time_range(symbol=sym, interval=interval)
            if (
                first is not None
                and first <= start_ms
                and last is not None
                and last >= end_ms - interval_ms[interval] * 2
            ):
                continue
            try:
                klines = fetcher.iter_historical_klines(
                    symbol=sym,
                    interval=interval,
                    start_time_ms=start_ms,
                    end_time_ms=end_ms,
                )
                totals[interval] += store.upsert_klines(klines)
            except Exception as exc:
                print(f"    ⚠ {sym}/{interval}: {exc}")
        if idx % 10 == 0 or idx == len(symbols):
            print(f"    [{idx:>3}/{len(symbols)}]  new rows: 1d={totals['1d']:,}  1h={totals['1h']:,}")
    return totals


def load_daily_panels(
    store: BinanceHistoryStore,
    symbols: list[str],
    start_ms: int,
) -> tuple[pd.DataFrame, pd.DataFrame, dict[str, int]]:
    close_frames: list[pd.Series] = []
    vol_frames: list[pd.Series] = []
    counts: dict[str, int] = {}
    for sym in symbols:
        rows = store.fetch_klines(symbol=sym, interval="1d", start_time_ms=start_ms)
        counts[sym] = len(rows)
        if not rows:
            continue
        df = pd.DataFrame.from_records(rows)
        df["t"] = pd.to_datetime(df["open_time_ms"], unit="ms", utc=True)
        df = df.set_index("t").sort_index()
        close_frames.append(df["close"].astype(float).rename(sym))
        vol_frames.append(df["quote_volume"].astype(float).rename(sym))
    closes = pd.concat(close_frames, axis=1).sort_index() if close_frames else pd.DataFrame()
    volumes = pd.concat(vol_frames, axis=1).sort_index() if vol_frames else pd.DataFrame()
    return closes, volumes, counts


def load_hourly_frame(
    store: BinanceHistoryStore,
    symbol: str,
    start_ms: int,
) -> pd.DataFrame:
    rows = store.fetch_klines(symbol=symbol, interval="1h", start_time_ms=start_ms)
    if not rows:
        return pd.DataFrame(
            columns=["open", "high", "low", "close", "volume", "quote_volume", "trade_count"]
        )
    df = pd.DataFrame.from_records(rows)
    df["t"] = pd.to_datetime(df["open_time_ms"], unit="ms", utc=True)
    df = df.set_index("t").sort_index()
    return df[["open", "high", "low", "close", "volume", "quote_volume", "trade_count"]].astype(float)


# ── Phase 1: Momentum ───────────────────────────────────────────────

def backtest_momentum(
    closes: pd.DataFrame,
    volumes: pd.DataFrame,
    config: dict,
    train_dates: list,
    val_dates: list,
) -> tuple[dict, pd.Series]:
    lookbacks = tuple(int(v) for v in cfg(config, "momentum", "lookback_periods", [3, 5, 7]))
    rsi_thresh = float(cfg(config, "momentum", "rsi_threshold", 45))
    top_n = int(cfg(config, "momentum", "top_n_assets", 8))
    min_vol = float(cfg(config, "mean_reversion", "min_volume_usd", 10_000_000))

    returns_by_day: dict[pd.Timestamp, float] = {}
    sel_by_day: dict[pd.Timestamp, int] = {}
    syms_by_day: dict[pd.Timestamp, list[str]] = {}

    for i in range(len(closes.index) - 1):
        dt = closes.index[i]
        nxt = closes.index[i + 1]
        signals = rank_assets_by_momentum(
            closes.iloc[: i + 1],
            volumes.iloc[: i + 1],
            lookback_periods=lookbacks,
            rsi_threshold=rsi_thresh,
            min_volume_usd=min_vol,
            top_n_assets=top_n,
        )
        selected = [s.symbol for s in signals]
        fwd = []
        for sym in selected:
            p0 = closes.at[dt, sym]
            p1 = closes.at[nxt, sym]
            if pd.notna(p0) and pd.notna(p1) and float(p0) > 0:
                fwd.append(float(p1) / float(p0) - 1.0)
        returns_by_day[dt] = float(np.mean(fwd)) if fwd else 0.0
        sel_by_day[dt] = len(selected)
        syms_by_day[dt] = selected

    ret_s = pd.Series(returns_by_day).sort_index()
    sel_s = pd.Series(sel_by_day).sort_index()

    def _summary(dates: list) -> dict:
        r = ret_s.reindex(dates).fillna(0)
        s = sel_s.reindex(dates).fillna(0)
        inv = r[s > 0]
        wins = inv[inv > 0]
        losses = inv[inv < 0]
        return {
            "days": len(r),
            "invested_days": int((s > 0).sum()),
            "avg_selected": float(s[s > 0].mean()) if (s > 0).any() else 0,
            "hit_rate": float((inv > 0).mean()) if not inv.empty else None,
            "avg_win_loss": float(wins.mean() / abs(losses.mean())) if not wins.empty and not losses.empty else None,
            "avg_return_pct": float(r.mean()),
            "total_return_pct": total_return(r),
            "sharpe": ann_sharpe(r),
            "sortino": ann_sortino(r),
            "max_dd": max_drawdown(r),
            "profit_factor": profit_factor(inv) if not inv.empty else None,
        }

    report = {"train": _summary(train_dates), "validation": _summary(val_dates)}
    return report, ret_s


# ── Phase 2: Mean-Reversion ─────────────────────────────────────────

def backtest_mean_reversion(
    store: BinanceHistoryStore,
    symbols: list[str],
    config: dict,
    start_ms: int,
    train_dates: list,
    val_dates: list,
) -> tuple[dict, pd.Series]:
    rsi_os = float(cfg(config, "mean_reversion", "rsi_oversold", 30))
    bb_p = int(cfg(config, "mean_reversion", "bollinger_period", 20))
    bb_s = float(cfg(config, "mean_reversion", "bollinger_std", 2.0))
    min_vol = float(cfg(config, "mean_reversion", "min_volume_usd", 10_000_000))
    max_hold = int(cfg(config, "mean_reversion", "max_hold_days", 3))
    sl = float(cfg(config, "mean_reversion", "stop_loss_pct", 0.05))
    hold_bars = max_hold * HOURS_PER_DAY

    trades: list[dict] = []
    for sym in symbols:
        frame = load_hourly_frame(store, sym, start_ms)
        if frame.empty or len(frame) < bb_p + 5:
            continue
        ind = build_mean_reversion_frame(
            frame["close"], frame["quote_volume"],
            rsi_oversold=rsi_os, bollinger_period=bb_p, bollinger_std=bb_s,
        )
        pos = 0
        while pos < len(frame) - 1:
            cur = ind.iloc[pos]
            if (
                pd.isna(cur["signal_strength"])
                or pd.isna(cur["moving_average"])
                or float(cur["signal_strength"]) <= 0
                or float(cur["volume_24h"]) < min_vol
            ):
                pos += 1
                continue
            entry_time = frame.index[pos]
            entry_price = float(cur["price"])
            exit_idx = min(pos + hold_bars, len(frame) - 1)
            reason = "time"
            for ci in range(pos + 1, exit_idx + 1):
                c = ind.iloc[ci]
                cp = float(c["price"])
                ma = float(c["moving_average"]) if pd.notna(c["moving_average"]) else math.nan
                if not math.isnan(ma) and cp >= ma:
                    exit_idx = ci
                    reason = "mean"
                    break
                if (cp / entry_price) - 1 <= -sl:
                    exit_idx = ci
                    reason = "stop"
                    break
            exit_time = frame.index[exit_idx]
            exit_price = float(ind.iloc[exit_idx]["price"])
            trades.append({
                "symbol": sym,
                "open_date": entry_time.normalize(),
                "close_date": exit_time.normalize(),
                "hours": int((exit_time - entry_time).total_seconds() // 3600),
                "return": (exit_price / entry_price) - 1,
                "exit": reason,
            })
            pos = exit_idx + 1

    tf = pd.DataFrame.from_records(trades) if trades else pd.DataFrame()
    if tf.empty:
        empty = {
            "trade_count": 0, "reversion_prob": None, "avg_reversion_hours": None,
            "avg_return": 0, "profit_factor": None, "win_rate": None,
        }
        return {"train": empty, "validation": empty}, pd.Series(dtype=float)

    daily_ret = tf.groupby("close_date")["return"].mean().sort_index()

    def _summary(dates: list) -> dict:
        sub = tf[tf["close_date"].isin(dates)]
        if sub.empty:
            return {
                "trade_count": 0, "reversion_prob": None, "avg_reversion_hours": None,
                "avg_return": 0, "profit_factor": None, "win_rate": None,
            }
        rets = sub["return"].astype(float)
        rev = sub[sub["exit"] == "mean"]
        return {
            "trade_count": len(sub),
            "reversion_prob": float((sub["exit"] == "mean").mean()),
            "avg_reversion_hours": float(rev["hours"].mean()) if not rev.empty else None,
            "avg_return": float(rets.mean()),
            "profit_factor": profit_factor(rets),
            "win_rate": float((rets > 0).mean()),
            "by_exit": {
                reason: int(count) for reason, count in sub["exit"].value_counts().items()
            },
        }

    return {"train": _summary(train_dates), "validation": _summary(val_dates)}, daily_ret


# ── Phase 3: Regime Detection ────────────────────────────────────────

def backtest_regime(
    closes: pd.DataFrame,
    config: dict,
    mom_returns: pd.Series,
    mr_returns: pd.Series,
    train_dates: list,
    val_dates: list,
) -> dict:
    btc = closes[BENCHMARK].dropna() if BENCHMARK in closes.columns else pd.Series(dtype=float)
    if btc.empty:
        return {"error": "No benchmark data"}

    rf = classify_regime_history(
        btc,
        ema_fast_period=int(cfg(config, "regime", "ema_fast_period", 20)),
        ema_slow_period=int(cfg(config, "regime", "ema_slow_period", 50)),
        volatility_lookback=int(cfg(config, "regime", "volatility_lookback", 14)),
        volatility_baseline_period=60,
        volatility_threshold_multiplier=float(cfg(config, "regime", "volatility_threshold_multiplier", 1.5)),
        confirmation_periods=int(cfg(config, "regime", "confirmation_periods", 2)),
    )
    fwd = btc.pct_change().shift(-1)
    aligned = rf.copy()
    aligned["mom_ret"] = mom_returns.reindex(aligned.index).fillna(0)
    aligned["mr_ret"] = mr_returns.reindex(aligned.index).fillna(0)
    aligned["fwd_ret"] = fwd.reindex(aligned.index)

    def _correct(row: pd.Series) -> bool:
        r = row.get("active_regime")
        if r == "bull":
            return float(row.get("mom_ret", 0)) > 0
        if r == "ranging":
            return float(row.get("mr_ret", 0)) > 0
        if r == "bear":
            v = row.get("fwd_ret")
            return pd.notna(v) and float(v) <= 0
        return False

    aligned["correct"] = aligned.apply(_correct, axis=1)

    def _summary(dates: list) -> dict:
        sub = aligned[aligned.index.isin(dates)]
        evald = sub[sub["active_regime"] != "unknown"]
        if evald.empty:
            return {"accuracy": None, "evaluated_days": 0, "regime_distribution": {}}
        dist = {str(k): int(v) for k, v in evald["active_regime"].value_counts().sort_index().items()}
        per_regime = {str(k): float(g["correct"].mean()) for k, g in evald.groupby("active_regime")}
        return {
            "accuracy": float(evald["correct"].mean()),
            "evaluated_days": len(evald),
            "regime_distribution": dist,
            "regime_accuracy": per_regime,
        }

    return {"train": _summary(train_dates), "validation": _summary(val_dates)}


# ── Phase 4: Ensemble Simulation ─────────────────────────────────────

CASH_FLOORS = {"bull": 0.20, "ranging": 0.40, "bear": 0.50}

WEIGHT_CONFIGS = {
    "default": None,
    "momentum_heavy": {
        "bull":    {"momentum": 0.65, "mean_reversion": 0.05, "sector_rotation": 0.20, "sentiment": 0.10},
        "ranging": {"momentum": 0.40, "mean_reversion": 0.40, "sentiment": 0.20},
        "bear":    {"mean_reversion": 0.25, "momentum": 0.05, "sentiment": 0.20},
    },
    "conservative": {
        "bull":    {"momentum": 0.35, "mean_reversion": 0.15, "sector_rotation": 0.20, "sentiment": 0.30},
        "ranging": {"momentum": 0.15, "mean_reversion": 0.55, "sentiment": 0.30},
        "bear":    {"mean_reversion": 0.20, "sentiment": 0.30},
    },
    "balanced": {
        "bull":    {"momentum": 0.40, "mean_reversion": 0.20, "sector_rotation": 0.20, "sentiment": 0.20},
        "ranging": {"momentum": 0.30, "mean_reversion": 0.40, "sentiment": 0.30},
        "bear":    {"mean_reversion": 0.35, "sentiment": 0.15},
    },
}


def simulate_ensemble(
    closes: pd.DataFrame,
    volumes: pd.DataFrame,
    regime_frame: pd.DataFrame,
    config: dict,
    eval_dates: list,
) -> pd.Series:
    """Simulate daily returns from the full ensemble pipeline."""
    lookbacks = tuple(int(v) for v in cfg(config, "momentum", "lookback_periods", [3, 5, 7]))
    rsi_thresh = float(cfg(config, "momentum", "rsi_threshold", 45))
    top_n = int(cfg(config, "momentum", "top_n_assets", 8))
    min_vol = float(cfg(config, "mean_reversion", "min_volume_usd", 10_000_000))
    rsi_os = float(cfg(config, "mean_reversion", "rsi_oversold", 30))

    daily_returns: dict[pd.Timestamp, float] = {}

    for dt in eval_dates:
        dt_loc = closes.index.get_loc(dt)
        if dt_loc >= len(closes.index) - 1:
            continue
        nxt = closes.index[dt_loc + 1]

        regime = "ranging"
        if dt in regime_frame.index:
            regime = str(regime_frame.at[dt, "active_regime"])
            if regime == "unknown":
                regime = "ranging"

        mom_signals = rank_assets_by_momentum(
            closes.iloc[: dt_loc + 1],
            volumes.iloc[: dt_loc + 1],
            lookback_periods=lookbacks,
            rsi_threshold=rsi_thresh,
            min_volume_usd=min_vol,
            top_n_assets=top_n,
        )
        mom_w = {s.symbol: s.normalized_score for s in mom_signals}

        rsi_vals: dict[str, float] = {}
        for col in closes.columns:
            series = closes[col].iloc[: dt_loc + 1].dropna()
            if len(series) >= 15:
                rsi_s = calculate_rsi(series, period=14)
                last = rsi_s.dropna()
                if not last.empty:
                    rsi_vals[col] = float(last.iloc[-1])
        oversold = [s for s, r in rsi_vals.items() if r <= rsi_os]
        mr_w = {s: 0.5 for s in oversold}

        btc_price_dir = "flat"
        if BENCHMARK in closes.columns and dt_loc >= 1:
            bp_now = float(closes.at[dt, BENCHMARK])
            bp_prev = float(closes.iloc[dt_loc - 1][BENCHMARK])
            if bp_prev > 0:
                bp_chg = (bp_now - bp_prev) / bp_prev
                if bp_chg > 0.001:
                    btc_price_dir = "rising"
                elif bp_chg < -0.001:
                    btc_price_dir = "falling"

        sector_w = sector_rotation_weights(
            universe=list(closes.columns), btc_dominance=58.0, previous_dominance=57.5,
            btc_price_direction=btc_price_dir,
        )

        ens = ensemble_combine(
            regime,
            momentum_weights=mom_w or None,
            mean_reversion_weights=mr_w or None,
            sector_rotation_weights=sector_w or None,
            sentiment_multiplier=1.0,
        )

        asset_vols: dict[str, float] | None = None
        if dt_loc >= 15:
            ret_slice = closes.iloc[max(0, dt_loc - 14) : dt_loc + 1].pct_change().dropna()
            if not ret_slice.empty:
                vols_s = ret_slice.std()
                asset_vols = {
                    str(s): float(v) for s, v in vols_s.items()
                    if v > 0 and not pd.isna(v)
                }

        weights = optimize_weights(
            ens.target_weights,
            volatilities=asset_vols,
            regime=regime,
        )

        day_ret = 0.0
        for sym, w in weights.items():
            if sym not in closes.columns:
                continue
            p0 = closes.at[dt, sym]
            p1 = closes.at[nxt, sym]
            if pd.notna(p0) and pd.notna(p1) and float(p0) > 0:
                day_ret += w * (float(p1) / float(p0) - 1.0)

        daily_returns[dt] = day_ret

    return pd.Series(daily_returns).sort_index()


def run_ensemble_phase(
    closes: pd.DataFrame,
    volumes: pd.DataFrame,
    config: dict,
    train_dates: list,
    val_dates: list,
) -> dict:
    btc = closes[BENCHMARK].dropna()
    rf = classify_regime_history(
        btc,
        ema_fast_period=int(cfg(config, "regime", "ema_fast_period", 20)),
        ema_slow_period=int(cfg(config, "regime", "ema_slow_period", 50)),
        volatility_lookback=int(cfg(config, "regime", "volatility_lookback", 14)),
        volatility_baseline_period=60,
        volatility_threshold_multiplier=float(cfg(config, "regime", "volatility_threshold_multiplier", 1.5)),
        confirmation_periods=int(cfg(config, "regime", "confirmation_periods", 2)),
    )

    all_dates = train_dates + val_dates
    ens_ret = simulate_ensemble(closes, volumes, rf, config, all_dates)

    train_ret = ens_ret.reindex(train_dates).dropna()
    val_ret = ens_ret.reindex(val_dates).dropna()

    def _full_summary(r: pd.Series) -> dict:
        if r.empty:
            return {}
        rolling_10 = []
        for i in range(10, len(r) + 1):
            w = r.iloc[i - 10 : i]
            rolling_10.append({
                "sharpe": ann_sharpe(w),
                "sortino": ann_sortino(w),
                "calmar": calmar(w),
            })
        valid_sharpes = [x["sharpe"] for x in rolling_10 if x["sharpe"] is not None]
        valid_sortinos = [x["sortino"] for x in rolling_10 if x["sortino"] is not None]
        valid_calmars = [x["calmar"] for x in rolling_10 if x["calmar"] is not None]
        return {
            "days": len(r),
            "total_return_pct": total_return(r),
            "avg_daily_return_pct": float(r.mean()),
            "sharpe": ann_sharpe(r),
            "sortino": ann_sortino(r),
            "calmar": calmar(r),
            "max_drawdown": max_drawdown(r),
            "profit_factor": profit_factor(r),
            "positive_days_pct": float((r > 0).mean()),
            "rolling_10d": {
                "sharpe_mean": float(np.mean(valid_sharpes)) if valid_sharpes else None,
                "sharpe_min": float(np.min(valid_sharpes)) if valid_sharpes else None,
                "sharpe_max": float(np.max(valid_sharpes)) if valid_sharpes else None,
                "sortino_mean": float(np.mean(valid_sortinos)) if valid_sortinos else None,
                "sortino_min": float(np.min(valid_sortinos)) if valid_sortinos else None,
                "sortino_max": float(np.max(valid_sortinos)) if valid_sortinos else None,
                "calmar_mean": float(np.mean(valid_calmars)) if valid_calmars else None,
                "calmar_min": float(np.min(valid_calmars)) if valid_calmars else None,
                "calmar_max": float(np.max(valid_calmars)) if valid_calmars else None,
            },
        }

    return {
        "train": _full_summary(train_ret),
        "validation": _full_summary(val_ret),
    }


# ── Report Printing ─────────────────────────────────────────────────

def print_momentum_report(rep: dict) -> None:
    print(_hdr("PHASE 1: MOMENTUM RANKINGS  (3/5/7-day trailing returns, top 8)"))
    for label, data in [("Train", rep["train"]), ("Validation", rep["validation"])]:
        print(f"\n  {label} ({data['days']} days, {data['invested_days']} invested):")
        print(f"    Hit Rate            {_pct(data['hit_rate'])}")
        print(f"    Win/Loss Ratio      {_ratio(data['avg_win_loss'])}")
        print(f"    Sharpe (ann.)       {_ratio(data['sharpe'])}")
        print(f"    Sortino (ann.)      {_ratio(data['sortino'])}")
        print(f"    Avg Return/Day      {_pct(data['avg_return_pct'])}")
        print(f"    Total Return        {_pct(data['total_return_pct'])}")
        print(f"    Max Drawdown        {_pct(data['max_dd'])}")
        print(f"    Profit Factor       {_ratio(data['profit_factor'])}")


def print_mr_report(rep: dict) -> None:
    print(_hdr("PHASE 2: MEAN-REVERSION TRIGGERS  (RSI<30 / Bollinger breach, 1h bars)"))
    for label, data in [("Train", rep["train"]), ("Validation", rep["validation"])]:
        print(f"\n  {label} ({data['trade_count']} trades):")
        print(f"    Reversion Prob.     {_pct(data['reversion_prob'])}")
        print(f"    Avg Reversion Time  {_f(data['avg_reversion_hours'])} hours")
        print(f"    Avg Return/Trade    {_pct(data['avg_return'])}")
        print(f"    Profit Factor       {_ratio(data['profit_factor'])}")
        print(f"    Win Rate            {_pct(data['win_rate'])}")
        if "by_exit" in data:
            exits = data["by_exit"]
            print(f"    Exit breakdown      mean={exits.get('mean', 0)}  stop={exits.get('stop', 0)}  time={exits.get('time', 0)}")


def print_regime_report(rep: dict) -> None:
    print(_hdr("PHASE 3: REGIME DETECTION ACCURACY  (EMA/vol heuristic on BTC)"))
    for label, data in [("Train", rep["train"]), ("Validation", rep["validation"])]:
        print(f"\n  {label} ({data['evaluated_days']} evaluated days):")
        print(f"    Overall Accuracy    {_pct(data['accuracy'])}")
        if "regime_distribution" in data:
            print(f"    Distribution        {data['regime_distribution']}")
        if "regime_accuracy" in data:
            for regime, acc in data["regime_accuracy"].items():
                print(f"      {regime:>8} accuracy  {_pct(acc)}")


def print_ensemble_report(rep: dict) -> None:
    print(_hdr("PHASE 4: FULL ENSEMBLE SIMULATION  (regime-weighted, optimised portfolio)"))
    for label, data in [("Train", rep["train"]), ("Validation", rep["validation"])]:
        if not data:
            print(f"\n  {label}: No data")
            continue
        print(f"\n  {label} ({data['days']} days):")
        print(f"    Total Return        {_pct(data['total_return_pct'])}")
        print(f"    Avg Daily Return    {_pct(data['avg_daily_return_pct'])}")
        print(f"    Sharpe (ann.)       {_ratio(data['sharpe'])}")
        print(f"    Sortino (ann.)      {_ratio(data['sortino'])}")
        print(f"    Calmar              {_ratio(data['calmar'])}")
        print(f"    Max Drawdown        {_pct(data['max_drawdown'])}")
        print(f"    Profit Factor       {_ratio(data['profit_factor'])}")
        print(f"    Positive Days       {_pct(data['positive_days_pct'])}")
        r10 = data.get("rolling_10d", {})
        if r10:
            print(f"    ── 10-day Rolling ──")
            print(f"      Sharpe            mean={_ratio(r10.get('sharpe_mean'))}  [{_ratio(r10.get('sharpe_min'))} .. {_ratio(r10.get('sharpe_max'))}]")
            print(f"      Sortino           mean={_ratio(r10.get('sortino_mean'))}  [{_ratio(r10.get('sortino_min'))} .. {_ratio(r10.get('sortino_max'))}]")
            print(f"      Calmar            mean={_ratio(r10.get('calmar_mean'))}  [{_ratio(r10.get('calmar_min'))} .. {_ratio(r10.get('calmar_max'))}]")


# ── Main ─────────────────────────────────────────────────────────────

def main() -> None:
    t_start = time.monotonic()
    config = yaml.safe_load((ROOT / "config" / "strategy_params.yaml").read_text())
    fetcher = BinanceFetcher()
    store = BinanceHistoryStore(DB_PATH)
    store.initialize()

    symbols = sorted({normalize_binance_symbol(s) for s in UNIVERSE})
    warmup = 70
    end_at = datetime.now(timezone.utc)
    start_at = end_at - timedelta(days=HISTORY_DAYS + warmup + 5)
    start_ms = int(start_at.timestamp() * 1000)
    end_ms = int(end_at.timestamp() * 1000)

    # ── Ingest ──
    print(f"\n{'=' * 70}")
    print("  BACKTEST PLAN — Team 15 Derivative Disaster")
    print(f"{'=' * 70}")
    print(f"  Universe : {len(symbols)} assets")
    print(f"  Window   : {start_at.date()} → {end_at.date()}  ({HISTORY_DAYS}d + {warmup}d warmup)")
    print(f"  Split    : {TRAIN_DAYS}d train / {VALIDATION_DAYS}d validate")
    print(f"  Benchmark: {BENCHMARK}")
    print(f"  DB cache : {DB_PATH}")
    print(f"\n  Fetching Binance data (cached after first run) …")
    totals = ingest_data(fetcher, store, symbols, start_ms, end_ms)
    print(f"  Ingestion complete: {totals}")

    # ── Load panels ──
    closes, volumes, counts = load_daily_panels(store, symbols, start_ms)
    live_syms = sum(1 for v in counts.values() if v > 0)
    print(f"  Loaded daily panels: {live_syms}/{len(symbols)} assets with data, {len(closes)} rows")

    if closes.empty or BENCHMARK not in closes.columns:
        print("FATAL: No benchmark data. Aborting.")
        sys.exit(1)

    eval_dates = list(closes.index[:-1])
    if len(eval_dates) < HISTORY_DAYS:
        print(f"  Warning: only {len(eval_dates)} eval days available (wanted {HISTORY_DAYS})")
    eval_dates = eval_dates[-HISTORY_DAYS:] if len(eval_dates) >= HISTORY_DAYS else eval_dates
    train_dates = eval_dates[:TRAIN_DAYS]
    val_dates = eval_dates[TRAIN_DAYS:]

    print(f"  Train:      {train_dates[0].date()} → {train_dates[-1].date()}  ({len(train_dates)} days)")
    print(f"  Validation: {val_dates[0].date()} → {val_dates[-1].date()}  ({len(val_dates)} days)")

    # ── Phase 1 ──
    print("\n  Running Phase 1 (momentum) …")
    mom_report, mom_ret = backtest_momentum(closes, volumes, config, train_dates, val_dates)
    print_momentum_report(mom_report)

    # ── Phase 2 ──
    print("\n  Running Phase 2 (mean-reversion) …")
    mr_report, mr_ret = backtest_mean_reversion(
        store, symbols, config, start_ms, train_dates, val_dates,
    )
    print_mr_report(mr_report)

    # ── Phase 3 ──
    print("\n  Running Phase 3 (regime detection) …")
    regime_report = backtest_regime(closes, config, mom_ret, mr_ret, train_dates, val_dates)
    print_regime_report(regime_report)

    # ── Phase 4 ──
    print("\n  Running Phase 4 (ensemble simulation) …")
    ens_report = run_ensemble_phase(closes, volumes, config, train_dates, val_dates)
    print_ensemble_report(ens_report)

    # ── Save full report ──
    full_report = {
        "metadata": {
            "universe_size": len(symbols),
            "history_days": HISTORY_DAYS,
            "train_days": TRAIN_DAYS,
            "validation_days": VALIDATION_DAYS,
            "benchmark": BENCHMARK,
            "train_start": str(train_dates[0].date()),
            "train_end": str(train_dates[-1].date()),
            "validation_start": str(val_dates[0].date()),
            "validation_end": str(val_dates[-1].date()),
            "assets_with_data": live_syms,
            "run_time_seconds": round(time.monotonic() - t_start, 1),
        },
        "momentum": mom_report,
        "mean_reversion": mr_report,
        "regime_detection": regime_report,
        "ensemble": ens_report,
    }

    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    REPORT_PATH.write_text(json.dumps(full_report, indent=2, default=str))
    elapsed = time.monotonic() - t_start
    print(f"\n{'━' * 70}")
    print(f"  Full report saved to {REPORT_PATH}")
    print(f"  Total runtime: {elapsed:.1f}s")
    print(f"{'━' * 70}")


if __name__ == "__main__":
    main()

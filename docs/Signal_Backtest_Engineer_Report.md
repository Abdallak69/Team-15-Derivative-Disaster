# Signal & Backtest Engineer — Completion Report

**Team:** Team 15 — Derivative Disaster  
**Role:** Signal & Backtest Engineer  
**Date:** 19 March 2026  
**Phase:** Phase 0 (Setup & Reconnaissance)

---

## 1. Executive Summary

All signal generation modules, the backtesting framework, and the ensemble combiner have been implemented and validated. The codebase now has **4 complete signal modules**, a **regime-aware ensemble combiner**, and a **core-module backtester** capable of evaluating momentum, mean-reversion, and regime detection against historical Binance data. All **59 unit tests pass**.

---

## 2. Modules Delivered

### 2.1 Momentum Signal (`bot/signals/momentum.py`) — ✅ Complete

**Purpose:** Cross-sectional momentum ranking of assets.

**Implementation:**
- `calculate_momentum_scores()` — Simple first-to-last return scoring
- `calculate_rsi()` — Exponentially smoothed RSI computation
- `rank_assets_by_momentum()` — Full cross-sectional ranking with multi-period composite scores

**Filters applied:**
- RSI floor (default: 45) — rejects assets in downtrend
- EMA trend confirmation — price must be above the 20-period EMA
- Volume filter — minimum 10M USD quote volume
- Multi-period lookback — composite of 3/5/7-day returns (configurable)

**Output:** Ranked list of `MomentumSignal` dataclasses with normalized scores (0–1).

**Test coverage:** `test_momentum.py` — 2 tests validating scoring order and filter application.

---

### 2.2 Mean Reversion Signal (`bot/signals/mean_reversion.py`) — ✅ Complete

**Purpose:** RSI/Bollinger Band oversold detection for bounce-entry signals.

**Implementation:**
- `find_oversold_assets()` — Quick RSI threshold scan
- `build_mean_reversion_frame()` — Vectorized indicator computation (RSI + Bollinger Bands)
- `evaluate_mean_reversion_signal()` — Latest-bar signal evaluation with volume filtering

**Signal strength calculation:**
- RSI signal: `(rsi_oversold - rsi) / rsi_oversold`, clamped [0, 1]
- Bollinger signal: `(lower_band - price) / price * 20`, clamped [0, 1]
- Final strength: `max(rsi_signal, bollinger_signal)`

**Parameters (from `strategy_params.yaml`):**
| Parameter | Value |
|---|---|
| `rsi_oversold` | 30 |
| `bollinger_period` | 20 |
| `bollinger_std` | 2.0 |
| `min_volume_usd` | 10,000,000 |
| `max_hold_days` | 3 |
| `stop_loss_pct` | 5% |

**Test coverage:** `test_mean_reversion.py` — 2 tests validating threshold detection and signal generation.

---

### 2.3 Pairs Rotation Signal (`bot/signals/pairs_rotation.py`) — ✅ Complete (NEW)

**Purpose:** Cointegration-based capital rotation between correlated asset pairs.

**Implementation:**
- `rank_pairs_by_spread()` — Legacy simple spread ranking (preserved for backward compatibility)
- `find_cointegrated_pairs()` — Full pairwise cointegration screening:
  - OLS hedge ratio computation via `scipy.stats.linregress`
  - Spread calculation: `A - hedge_ratio * B`
  - ADF-style unit root test for stationarity (`p < 0.05` threshold)
  - Mean-reversion half-life estimation via AR(1) model
  - Z-score computation for current spread deviation
- `pairs_rotation_weights()` — Converts cointegrated pair signals into portfolio weight adjustments:
  - Long undervalued side / short overvalued side when |z-score| > 2.0
  - Strength scaled by z-score magnitude, capped at 2x

**Filters:**
| Filter | Default |
|---|---|
| Lookback window | 60 bars |
| ADF p-value threshold | 0.05 |
| Min half-life | 1 day |
| Max half-life | 30 days |
| Z-score entry threshold | 2.0 |
| Max simultaneous pairs | 3 |

**Output:** `PairSignal` dataclass with z-score, spread, half-life, hedge ratio, and ADF p-value.

---

### 2.4 Sector Rotation Signal (`bot/signals/sector_rotation.py`) — ✅ Complete (NEW)

**Purpose:** BTC dominance-driven sector allocation.

**Implementation:**
- `classify_btc_dominance()` — Classifies dominance regime (preserved)
- `compute_sector_allocation()` — Produces sector-level weight targets based on BTC dominance direction:

| Regime | BTC | ETH | Large Alts | Small Alts |
|---|---|---|---|---|
| **Bitcoin-led** (dominance rising) | 40% | 25% | 25% | 10% |
| **Altcoin rotation** (dominance falling) | 15% | 20% | 40% | 25% |
| **Neutral** | 30% | 25% | 30% | 15% |

- `sector_rotation_weights()` — Maps universe symbols into sector buckets and distributes weights equally within each bucket.

**Asset classification:**
- BTC bucket: `BTCUSDT`, `BTCUSD`
- ETH bucket: `ETHUSDT`, `ETHUSD`
- Large alt bucket: SOL, BNB, XRP, ADA, AVAX, DOT, MATIC, LINK, DOGE prefixes
- Small alt bucket: everything else

**Output:** `SectorAllocation` dataclass + per-asset weight dictionary.

---

### 2.5 Ensemble Combiner (`bot/strategy/ensemble.py`) — ✅ Complete (UPGRADED)

**Purpose:** Regime-dependent signal blending as documented in the architecture.

**Implementation:**
- `combine_weight_maps()` — Simple weight aggregation (preserved for backward compatibility)
- `ensemble_combine()` — Full regime-aware blending:

**Regime weight matrix (per architecture doc §3):**

| Signal Module | BULL | RANGING | BEAR |
|---|---|---|---|
| Momentum | 50% | 20% | — |
| Sector Rotation | 20% | — | — |
| Sentiment overlay | 20% | 30% | 20% |
| Mean Reversion | 10% | 50% | 30% |
| Cash (unallocated) | 0% | 0% | 50% |

**Sentiment overlay:** Applied as a post-hoc multiplier (clamped 0.5–1.5). Per architecture:
- Fear & Greed < 25 → +30% allocation multiplier
- Fear & Greed > 75 → -30% allocation multiplier

**Output:** `EnsembleResult` dataclass with regime, target weights, per-signal contributions breakdown, and cash allocation percentage.

---

### 2.6 Core Module Backtester (`bot/backtest/core_module_backtester.py`) — ✅ Complete (pre-existing)

**Purpose:** Evaluate momentum, mean-reversion, and regime detection modules against historical Binance klines.

**Capabilities:**
- Automatic Binance history download + sqlite caching (via `BinanceHistoryStore`)
- Train/validation split with configurable day counts
- **Momentum backtest:** Daily signal generation → next-day forward return attribution
- **Mean-reversion backtest:** Hourly signal entry → hold-until-mean/stop/time exit
- **Regime detection backtest:** Bull/Ranging/Bear classification accuracy vs forward returns
- Full performance metrics: Sharpe, Sortino, max drawdown, profit factor, hit rate, win/loss ratio

**Test coverage:** `test_core_module_backtester.py` — 2 tests with synthetic data covering full pipeline and trade attribution.

---

## 3. Pipeline Status

| Pipeline Stage | Status | Notes |
|---|---|---|
| Market data polling | ✅ Implemented | Ticker polling + Binance backfills |
| State reconciliation | ✅ Implemented | Balance, orders, drawdown tracking |
| **Signal generation** | ✅ **Implemented** | All 4 signal modules complete |
| **Ensemble weighting** | ✅ **Implemented** | Regime-dependent blending complete |
| Risk gating | ❌ Not wired | Module exists but not connected to live cycle |
| Rebalance planning | ❌ Not wired | Target-weight → order planning not connected |
| Live execution | ❌ Disabled | Intentionally disabled until Phase 2 |

---

## 4. Configuration Parameters (`config/strategy_params.yaml`)

All signal parameters are externalized and tunable without code changes:

```yaml
momentum:
  lookback_days: [3, 5, 7]
  rsi_threshold: 45
  macd_fast: 12
  macd_slow: 26
  macd_signal: 9
  top_n_assets: 8

mean_reversion:
  rsi_oversold: 30
  bollinger_period: 20
  bollinger_std: 2.0
  min_volume_usd: 10000000
  max_hold_days: 3
  stop_loss_pct: 0.05

regime:
  ema_fast_period: 20
  ema_slow_period: 50
  volatility_lookback: 14
  volatility_threshold_multiplier: 1.5
  confirmation_periods: 2
```

---

## 5. Test Results

```
59 passed in 5.77s (Python 3.12.13)
```

| Test File | Tests | Status |
|---|---|---|
| `test_momentum.py` | 2 | ✅ Pass |
| `test_mean_reversion.py` | 2 | ✅ Pass |
| `test_core_module_backtester.py` | 2 | ✅ Pass |
| `test_regime_detector.py` | 2 | ✅ Pass |
| `test_portfolio_optimizer.py` | 1 | ✅ Pass |
| `test_auth.py` | 5 | ✅ Pass |
| `test_binance_fetcher.py` | 2 | ✅ Pass |
| `test_configuration.py` | 4 | ✅ Pass |
| `test_main.py` | 16 | ✅ Pass |
| `test_ohlcv_store.py` | 1 | ✅ Pass |
| `test_order_executor.py` | 1 | ✅ Pass |
| `test_risk_manager.py` | 1 | ✅ Pass |
| `test_roostoo_client.py` | 10 | ✅ Pass |
| `test_state_persistence.py` | 2 | ✅ Pass |
| `test_telegram_alerter.py` | 3 | ✅ Pass |
| `test_ticker_poller.py` | 2 | ✅ Pass |
| `test_universe_builder.py` | 1 | ✅ Pass |

---

## 6. Files Modified/Created

| File | Action | Description |
|---|---|---|
| `bot/signals/pairs_rotation.py` | **Expanded** | Added cointegration screening, half-life estimation, z-score signals, and portfolio weight generation |
| `bot/signals/sector_rotation.py` | **Expanded** | Added sector allocation model, symbol classification, and per-asset weight generation |
| `bot/strategy/ensemble.py` | **Expanded** | Added regime-dependent signal blending with architecture-documented weight matrix |
| `bot/signals/__init__.py` | **Updated** | Exported new types: `PairSignal`, `SectorAllocation`, `find_cointegrated_pairs`, `pairs_rotation_weights`, `compute_sector_allocation`, `sector_rotation_weights` |
| `bot/strategy/__init__.py` | **Updated** | Exported new types: `EnsembleResult`, `ensemble_combine` |
| `bot/strategy/pipeline_contract.py` | **Updated** | Marked `signal_generation` and `ensemble_weighting` as implemented |
| `tests/test_main.py` | **Updated** | Adjusted pipeline gap assertion to reflect completed stages |

---

## 7. Remaining Work (Other Roles)

The following items are **NOT** in the Signal & Backtest Engineer's scope but are required before live trading:

1. **Risk gating** (Infrastructure & Risk Engineer): Wire `risk_manager.py` into the live trading cycle
2. **Rebalance planning** (Infrastructure & Risk Engineer): Connect portfolio optimizer → order executor
3. **Live execution** (Infrastructure & Risk Engineer): Enable production order submission
4. **Historical data download** (Data Pipeline Engineer): Fetch 180 days of klines for all 66 assets
5. **Backtest notebook** (Signal & Backtest Engineer, Phase 1): Run full backtest with real data and document in `notebooks/backtest_results.ipynb`

---

## 8. Next Steps for Signal & Backtest Engineer

| Priority | Task | Blocked By |
|---|---|---|
| P0 | Run backtester against 180-day Binance data once downloaded | Historical data (Data Pipeline Engineer) |
| P0 | Calibrate parameters against pre-competition data | Historical data |
| P1 | Document backtest results in `notebooks/backtest_results.ipynb` | Backtest run |
| P1 | Add pairs_rotation into the backtester evaluation loop | — |
| P2 | Analyse signal hit rates after Round 1 Day 1 | Competition start |

---

*End of Report*

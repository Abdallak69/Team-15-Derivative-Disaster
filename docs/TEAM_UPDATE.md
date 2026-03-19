# Team Update

This is the single team update file for the repo. I use it to state what is actually implemented, what changed recently, what technical details matter right now, and where we are against the project plan.

The files in `Technicals/` describe the intended end product.
`docs/03_operations_runbook.md` is the current operational source of truth for code and deployment behavior.

## What is implemented right now

We have completed the repo scaffold and a guarded runtime slice that combines the market-data pipeline with the operational bootstrap, reconciliation, and monitoring paths the current runbook depends on.

Implemented files:

- `bot/api/auth.py`
- `bot/api/roostoo_client.py`
- `bot/data/ohlcv_store.py`
- `bot/data/ticker_poller.py`
- `bot/data/universe_builder.py`
- `bot/main.py`
- `bot/signals/momentum.py`
- `bot/signals/mean_reversion.py`
- `bot/signals/pairs_rotation.py`
- `bot/signals/sector_rotation.py`
- `bot/strategy/ensemble.py`
- `bot/strategy/regime_detector.py`
- `bot/strategy/portfolio_optimizer.py`
- `bot/backtest/core_module_backtester.py`
- `bot/data/binance_fetcher.py`
- `bot/data/binance_history_store.py`

Supporting files also exist:

- `.gitignore`
- `.env.example`
- `config/strategy_params.yaml`
- `config/logging_config.yaml`
- `requirements.txt`
- `README.md`
- `docs/03_operations_runbook.md`
- `deploy/setup.sh`
- `deploy/deploy.sh`
- `deploy/tradingbot.service`
- baseline tests in `tests/`

## What this implementation does

### 1. Roostoo auth and timestamp handling

I implemented:

- environment-backed API credentials
- millisecond timestamp generation
- alphabetically sorted parameter signing for HMAC endpoints
- header construction for signed requests

### 2. Roostoo client for the current slice

I implemented working client support for:

- `/v3/serverTime`
- `/v3/exchangeInfo`
- `/v3/ticker`
- signed wrappers for `/v3/balance`, `/v3/pending_count`, `/v3/place_order`, `/v3/query_order`, `/v3/cancel_order`

The client currently:

- normalizes wrapped API payloads
- retries transient failures
- stores a clock offset after syncing against `serverTime`
- adds the required `timestamp` param for ticker polling

### 3. Exchange universe loading

I implemented `universe_builder.py` so the bot can:

- parse `exchangeInfo`
- extract pair or symbol
- read trading status
- read precision fields
- read minimum order size
- build the active tradeable universe dynamically

This matters because the planning docs explicitly say we should not hardcode the 66 assets.

### 4. Local sqlite market database

I implemented `ohlcv_store.py` so the bot writes ticker-derived one-minute candles into sqlite.

The current table stores:

- `pair`
- `candle_ts`
- `open`
- `high`
- `low`
- `close`
- `max_bid`
- `min_ask`
- `change_pct`
- `coin_trade_value_24h`
- `unit_trade_value_24h`
- `sample_count`
- `first_polled_at`
- `last_polled_at`

Writes are minute-bucketed upserts. Multiple polls in the same minute update `high`, `low`, `close`, and increment `sample_count`.

### 5. Ticker polling loop

I implemented `ticker_poller.py` so the bot can:

- fetch the full ticker set
- normalize rows into internal snapshots
- filter to the tracked universe
- persist the snapshots into sqlite

### 6. Bot bootstrap, reconciliation, and scheduler

I implemented `bot/main.py` so the bot can:

- load `.env`
- validate YAML config
- apply logging config
- build the client and data modules
- sync server time
- load `exchangeInfo`
- set the universe
- reconcile persisted state against signed balance and pending-order endpoints
- send startup and heartbeat Telegram alerts when Telegram secrets are configured
- run the polling, reconciliation, heartbeat, and clock-sync loops on a schedule

Current commands:

- `python -c "from bot.main import TradingBot"`
- `python -m bot.main --status`
- `python -m bot.main --startup-check`
- `python -m bot.main --poll-once`
- `python -m bot.main`

`--startup-check` is important because it runs the real bootstrap path once and exits. I use it for local and first-host bootstrap checks before the one-shot poll smoke test.
`--poll-once` is the one-shot smoke test for the real polling path without `systemd` or Telegram side effects.
I only expect it to pass when `.env` contains real testing or competition keys rather than the placeholder values from `.env.example`.

### 7. Signal generation modules

All four signal modules are now implemented and validated.

**Momentum (`bot/signals/momentum.py`):** Cross-sectional momentum ranking. Composite score from 3/5/7-day returns. Filters: RSI ≥ 45, price above 20-EMA, quote volume ≥ 10M USD. Returns top-N `MomentumSignal` dataclasses with normalized scores.

**Mean reversion (`bot/signals/mean_reversion.py`):** RSI/Bollinger Band oversold detection. Signal strength = max(RSI signal, Bollinger signal). Triggers when RSI < 30 or price below lower band. Filters by volume. Returns `MeanReversionSignal` with strength, price, MA, and RSI fields.

**Pairs rotation (`bot/signals/pairs_rotation.py`):** Cointegration-based capital rotation. Screens all symbol pairs for cointegration using OLS hedge ratios, ADF stationarity tests (p < 0.05), and half-life estimation via AR(1). Generates z-score-based weight adjustments when |z| > 2.0. Filters: lookback 60 bars, half-life 1–30 days, max 3 simultaneous pairs.

**Sector rotation (`bot/signals/sector_rotation.py`):** BTC dominance-driven sector allocation. Three regimes based on dominance direction:

| Regime | BTC | ETH | Large Alts | Small Alts |
|---|---|---|---|---|
| Bitcoin-led (rising) | 40% | 25% | 25% | 10% |
| Altcoin rotation (falling) | 15% | 20% | 40% | 25% |
| Neutral | 30% | 25% | 30% | 15% |

Distributes sector weight equally among assets in each bucket.

### 8. Ensemble combiner

The ensemble combiner (`bot/strategy/ensemble.py`) is now fully implemented with regime-dependent signal blending:

| Signal | BULL | RANGING | BEAR |
|---|---|---|---|
| Momentum | 50% | 20% | — |
| Sector rotation | 20% | — | — |
| Sentiment overlay | 20% | 30% | 20% |
| Mean reversion | 10% | 50% | 30% |
| Cash (unallocated) | — | — | 50% |

Sentiment is a post-hoc multiplier (clamped 0.5–1.5): F&G < 25 → ×1.3, F&G > 75 → ×0.7. Returns an `EnsembleResult` with target weights, per-signal contributions, and cash allocation.

### 9. Core module backtester

`bot/backtest/core_module_backtester.py` evaluates momentum, mean-reversion, and regime detection against historical Binance klines. Fetches and caches 1d/1h klines via `BinanceFetcher` + `BinanceHistoryStore` (sqlite). Supports train/validation splits. Computes Sharpe, Sortino, max drawdown, profit factor, hit rate, and win/loss ratio per module. Run via `python -m bot.main --backtest`.

## Critical technical details the team needs to know

- Roostoo does not provide historical candles or a history endpoint. Our own polling database is the foundation for the rest of the bot.
- The current candles are derived from repeated `LastPrice` polling. They are not exchange-native candles.
- `CoinTradeValue` and `UnitTradeValue` from the ticker are 24-hour rolling snapshot values. They are not true one-minute candle volume.
- Clock sync is not optional. The API rejects requests if local time drifts too far from server time.
- The running bot now uses the signed balance and pending-order paths for operational reconciliation, but it still does not place or cancel live orders from the runtime loop.
- The target architecture and target deployment flow are documented in `Technicals/05_Architecture_Overview.md` and `Technicals/07_Deployment_Runbook.md`.
- The current operational contract for new code is `docs/03_operations_runbook.md`.
- The current service and deploy flow now use a one-shot bootstrap plus poll smoke test before `systemd` restart.
- `deploy/setup.sh` now provisions swap, enables NTP, and synchronizes the current checkout into `/opt/trading-bot` before creating the venv.
- The rebalance helper now correctly generates flattening sells for positions that disappear from the target portfolio.
- `python -m bot.main --startup-check` now exercises the real signed reconciliation path as part of bootstrap.

## Tests and verification status

Current checks passing:

- `python -c "from bot.main import TradingBot"`
- `pytest tests -q`
- `python -m py_compile $(rg --files -g '*.py')`

There are currently 59 passing unit tests covering:

- auth helpers
- Binance historical pagination and caching paths
- Roostoo client behavior
- sqlite candle persistence
- ticker polling
- universe building
- startup/bootstrap behavior
- state persistence
- reconciliation and heartbeat behavior
- rebalance flattening behavior
- staged core-module backtests (momentum, mean-reversion, regime)
- regime classification confirmation behavior
- momentum signal ranking and filter logic
- mean-reversion signal threshold and strength logic
- portfolio optimizer cash floor normalization
- Telegram alert delivery helpers
- configuration validation

## What is not implemented yet

These planned modules are still incomplete, placeholder-level, or not production-ready:

- sentiment ingestion (`bot/data/sentiment_fetcher.py` exists but not wired into the trading cycle)
- real risk enforcement (risk manager module exists but not connected to live cycle)
- rebalance planning (target-weight → order-planning flow not wired)
- live execution path (intentionally disabled)
- backtest notebook (`notebooks/backtest_results.ipynb` pending real historical data)

We should not treat the repo as competition-ready for actual trading yet.

The signal pipeline (all 4 signal modules + ensemble combiner) is fully implemented and tested. The remaining gap before a live trading cycle is risk gating and order execution — both owned by the Infrastructure & Risk Engineer.

## Where we are on the project roadmap

Against the planning docs:

### Phase 0

Done:

- repo structure
- import milestone
- first Roostoo client slice
- first HMAC/auth slice
- first ticker polling and local DB slice
- all 4 signal modules (momentum, mean-reversion, pairs rotation, sector rotation)
- ensemble combiner with regime-dependent weight matrix
- core-module backtester (momentum, mean-reversion, regime detection)
- Binance historical fetch + sqlite caching

Still remaining from Phase 0:

- remaining live-trading endpoint integration
- risk manager wired into trading cycle
- backtest notebook (blocked on real historical data download)

### Phase 1

Not started in a meaningful end-to-end way yet.

We have prepared the base needed for Phase 1 by building:

- startup clock sync
- dynamic universe loading
- continuous ticker polling
- local sqlite persistence
- signed operational reconciliation
- startup and heartbeat alert plumbing

But we still need the actual test-environment endpoint verification and paper-trading style integration path.

## What I think the next step should be

The next highest-value step is to keep building from the operational slice into the actual trading loop. In practice that means:

1. wire the signed private-endpoint wrappers into real order execution flows
2. harden the sqlite/data validation path
3. add the remaining ensemble and risk layers on top of the now-runnable historical backtest slice
4. move the calibrated signal, regime, and risk helpers into a real trading cycle

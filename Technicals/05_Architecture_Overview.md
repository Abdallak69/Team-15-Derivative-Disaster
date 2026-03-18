# Architecture Overview
## SG vs HK University Web3 Quant Trading Hackathon

**Team:** TBC (Lead), TBC, TBC, TBC
**Date Prepared:** 18 March 2026

---

## 1. Repository Structure

```
roostoo-quant-bot/
│
├── bot/                           # Core application code
│   ├── __init__.py
│   ├── main.py                    # Entry point — initialises all modules, runs main loop
│   │
│   ├── api/                       # Roostoo API interface (Owner: TBC)
│   │   ├── __init__.py
│   │   ├── auth.py                # HMAC SHA256 signature generation, timestamp management
│   │   └── roostoo_client.py      # Wrapper for all 8 API endpoints with retry logic
│   │
│   ├── data/                      # Data ingestion and storage (Owner: TBC)
│   │   ├── __init__.py
│   │   ├── ohlcv_store.py         # sqlite interface: insert, query, prune old data
│   │   ├── ticker_poller.py       # Polls /v3/ticker every 60s, writes to ohlcv_store
│   │   ├── binance_fetcher.py     # Fetches historical klines from Binance public API
│   │   ├── sentiment_fetcher.py   # Fetches Fear & Greed Index, Binance funding rates
│   │   └── universe_builder.py    # Calls /v3/exchangeInfo, builds tradeable asset list
│   │
│   ├── signals/                   # Signal generation modules (Owner: TBC)
│   │   ├── __init__.py
│   │   ├── momentum.py            # Cross-sectional momentum ranking
│   │   ├── mean_reversion.py      # RSI/Bollinger Band oversold detection
│   │   ├── pairs_rotation.py      # Cointegration-based capital rotation
│   │   └── sector_rotation.py     # BTC dominance-driven sector allocation
│   │
│   ├── strategy/                  # Strategy orchestration (Owner: TBC)
│   │   ├── __init__.py
│   │   ├── regime_detector.py     # Bull/Ranging/Bear classification
│   │   ├── ensemble.py            # Combines signals with regime-dependent weights
│   │   └── portfolio_optimizer.py # Inverse-vol weighting, Kelly constraint, cash floor
│   │
│   ├── risk/                      # Risk management (Owner: TBC)
│   │   ├── __init__.py
│   │   ├── risk_manager.py        # Per-position stop-losses, daily loss limits
│   │   └── circuit_breaker.py     # Portfolio-level drawdown circuit breakers
│   │
│   ├── execution/                 # Order execution (Owner: TBC)
│   │   ├── __init__.py
│   │   └── order_executor.py      # Translates target weights → API orders (limit preferred)
│   │
│   └── monitoring/                # Alerting and metrics (Owner: TBC)
│       ├── __init__.py
│       ├── telegram_alerter.py    # Push notifications via Telegram Bot API
│       └── metrics_tracker.py     # Real-time Sharpe, Sortino, Calmar computation
│
├── config/                        # Configuration files
│   ├── strategy_params.yaml       # All tuneable strategy parameters
│   └── logging_config.yaml        # Log levels, rotation settings, file paths
│
├── data/                          # Runtime data (gitignored except schema)
│   ├── .gitkeep
│   ├── historical_klines.db       # Pre-competition Binance data (gitignored)
│   ├── live_ohlcv.db              # Live ticker data (gitignored)
│   └── bot_state.json             # Persisted state for crash recovery (gitignored)
│
├── deploy/                        # Deployment scripts and configs
│   ├── setup.sh                   # EC2 initial setup (packages, swap, Python)
│   ├── tradingbot.service         # systemd service file
│   └── deploy.sh                  # Pull + install + restart procedure
│
├── tests/                         # Unit and integration tests
│   ├── test_auth.py
│   ├── test_roostoo_client.py
│   ├── test_momentum.py
│   ├── test_mean_reversion.py
│   ├── test_risk_manager.py
│   ├── test_portfolio_optimizer.py
│   └── test_state_persistence.py
│
├── notebooks/                     # Analysis notebooks (for presentation prep)
│   ├── backtest_results.ipynb
│   ├── round1_analysis.ipynb
│   └── round2_analysis.ipynb
│
├── .env.example                   # Template showing required env vars (no real values)
├── .gitignore
├── requirements.txt
├── README.md
└── LICENSE
```

---

## 2. Main Loop Architecture

The bot's `main.py` runs a single-threaded event loop using `APScheduler`. This avoids concurrency bugs, race conditions, and the complexity of multi-threading on a 2-vCPU instance.

```
┌─────────────────────────────────────────────────┐
│                  STARTUP SEQUENCE                │
│                                                  │
│  1. Load config from YAML                        │
│  2. Load .env (API keys)                         │
│  3. Sync clock with /v3/serverTime               │
│  4. Call /v3/exchangeInfo → build universe        │
│  5. Load persisted state from bot_state.json      │
│  6. Initialise all modules                        │
│  7. Start scheduler                               │
│  8. Send Telegram "Bot started" alert             │
└────────────────────┬────────────────────────────┘
                     │
                     ▼
┌─────────────────────────────────────────────────┐
│              SCHEDULED JOBS                      │
│                                                  │
│  Every 60 seconds:                               │
│    → ticker_poller.poll()     [fetch all tickers]│
│    → ohlcv_store.insert()     [store in sqlite]  │
│                                                  │
│  Every 5 minutes:                                │
│    → MAIN TRADING CYCLE (see below)              │
│                                                  │
│  Every 1 hour:                                   │
│    → metrics_tracker.compute_all()               │
│    → telegram_alerter.send_heartbeat()           │
│    → sync clock with /v3/serverTime              │
│                                                  │
│  Every 4 hours:                                  │
│    → regime_detector.update()                    │
│    → sentiment_fetcher.update()                  │
│                                                  │
│  Every 24 hours:                                 │
│    → ohlcv_store.prune(max_days=30)              │
│    → gc.collect()                                │
└────────────────────┬────────────────────────────┘
                     │
                     ▼
┌─────────────────────────────────────────────────┐
│           MAIN TRADING CYCLE (every 5 min)       │
│                                                  │
│  1. Check if bot is paused (circuit breaker)     │
│     └─ If paused: skip to step 8                 │
│                                                  │
│  2. Fetch current ticker (all pairs)             │
│     └─ Validate data; reject if invalid          │
│                                                  │
│  3. Fetch current balance                        │
│     └─ Compute portfolio value + drawdown        │
│     └─ Update peak value tracker                 │
│                                                  │
│  4. Run risk checks                              │
│     ├─ Check per-position stop-losses            │
│     ├─ Check portfolio circuit breakers          │
│     └─ Check daily loss limit                    │
│     └─ If any triggered: execute sells, skip     │
│        to step 8                                 │
│                                                  │
│  5. Generate signals                             │
│     ├─ momentum.score_all(prices, universe)      │
│     ├─ mean_reversion.scan(prices, universe)     │
│     ├─ sector_rotation.classify(btc_dominance)   │
│     └─ sentiment overlay (if fresh data)         │
│                                                  │
│  6. Compute target portfolio                     │
│     ├─ regime_detector.current_regime            │
│     ├─ ensemble.combine(signals, regime)         │
│     └─ portfolio_optimizer.optimize(targets)     │
│        ├─ Apply inverse-vol weighting            │
│        ├─ Apply Kelly constraint                 │
│        ├─ Enforce position limits (10% max)      │
│        └─ Enforce cash floor                     │
│                                                  │
│  7. Execute rebalancing                          │
│     ├─ Compare current vs target weights         │
│     ├─ If any drift > 15%: generate orders       │
│     ├─ Sells first, then buys (maintain cash)    │
│     ├─ Use limit orders (5 bps vs 10 bps)       │
│     └─ Respect rate limits (65s spacing)         │
│                                                  │
│  8. Persist state to bot_state.json              │
│     └─ Atomic write (temp file → rename)         │
│                                                  │
│  9. Log cycle summary                            │
│     └─ Portfolio value, positions, signals,      │
│        regime, orders placed                     │
└─────────────────────────────────────────────────┘
```

---

## 3. Strategy Signal Flow

```
                    ┌──────────────────────────────┐
                    │     EXTERNAL DATA SOURCES     │
                    │                               │
                    │  Binance Klines (historical)  │
                    │  Fear & Greed Index (daily)   │
                    │  Funding Rates (8-hourly)     │
                    │  BTC Dominance (hourly)       │
                    └───────────┬──────────────────┘
                                │
                    ┌───────────▼──────────────────┐
                    │       DATA LAYER              │
                    │                               │
                    │  Roostoo Ticker (60s poll)    │
                    │       ↓                       │
                    │  OHLCV Store (sqlite)         │
                    │  ┌─────────────────────────┐  │
                    │  │ 1-min candles (live)     │  │
                    │  │ 1-hour candles (Binance) │  │
                    │  │ 1-day candles (Binance)  │  │
                    │  └─────────────────────────┘  │
                    └───────────┬──────────────────┘
                                │
           ┌────────────────────┼────────────────────┐
           │                    │                     │
           ▼                    ▼                     ▼
   ┌───────────────┐  ┌────────────────┐  ┌──────────────────┐
   │  REGIME        │  │  SIGNAL        │  │  SENTIMENT       │
   │  DETECTOR      │  │  MODULES       │  │  OVERLAY         │
   │                │  │                │  │                  │
   │  BTC vs EMAs   │  │  Momentum      │  │  F&G Index       │
   │  Volatility    │  │  (3/5/7-day    │  │  (< 25: +30%     │
   │  regime        │  │  composite     │  │   > 75: -30%)    │
   │                │  │  ranking)      │  │                  │
   │  Output:       │  │                │  │  Funding Rates   │
   │  BULL /        │  │  Mean-Rev      │  │  (deeply neg:    │
   │  RANGING /     │  │  (RSI<30,      │  │   +2% bonus)     │
   │  BEAR          │  │  Bollinger)    │  │                  │
   │                │  │                │  │  Output:         │
   │                │  │  Sector        │  │  allocation      │
   │                │  │  Rotation      │  │  multiplier      │
   │                │  │  (BTC dom.)    │  │                  │
   │                │  │                │  │                  │
   │                │  │  Output:       │  │                  │
   │                │  │  {pair: score} │  │                  │
   └───────┬───────┘  └───────┬────────┘  └────────┬─────────┘
           │                  │                     │
           └──────────────────┼─────────────────────┘
                              │
                    ┌─────────▼─────────────────────┐
                    │       ENSEMBLE COMBINER        │
                    │                                │
                    │  Regime → selects sub-strategy  │
                    │  weights:                       │
                    │                                │
                    │  BULL:   Mom 50%, Sect 20%,     │
                    │          Sent 20%, MR 10%       │
                    │  RANGE:  MR 50%, Sent 30%,      │
                    │          Mom 20%                 │
                    │  BEAR:   Cash 50%, MR 30%,      │
                    │          Sent 20%                │
                    │                                │
                    │  Output: {pair: target_weight}   │
                    └─────────┬─────────────────────┘
                              │
                    ┌─────────▼─────────────────────┐
                    │    PORTFOLIO OPTIMIZER          │
                    │                                │
                    │  1. Inverse-vol weighting       │
                    │  2. Half-Kelly upper bound      │
                    │  3. Max 10% per position        │
                    │  4. Max 30% per sector          │
                    │  5. Cash floor (regime-dep.)    │
                    │  6. Sentiment multiplier        │
                    │                                │
                    │  Output: {pair: final_weight}    │
                    └─────────┬─────────────────────┘
                              │
                    ┌─────────▼─────────────────────┐
                    │      RISK MANAGER              │
                    │                                │
                    │  Pre-trade checks:              │
                    │  - Daily loss limit OK?         │
                    │  - Circuit breaker active?      │
                    │  - Position limit respected?    │
                    │                                │
                    │  Post-trade monitoring:          │
                    │  - Per-position stop-loss       │
                    │  - Peak/drawdown tracking       │
                    │  - Portfolio circuit breaker    │
                    │                                │
                    │  Output: approved/rejected      │
                    └─────────┬─────────────────────┘
                              │
                    ┌─────────▼─────────────────────┐
                    │     EXECUTION ENGINE            │
                    │                                │
                    │  1. Compare current vs target   │
                    │  2. If drift > 15%: rebalance   │
                    │  3. Sells first (free up cash)  │
                    │  4. Then buys                   │
                    │  5. Limit orders at LastPrice    │
                    │     ± 0.01%                     │
                    │  6. 65-second spacing between    │
                    │     orders                      │
                    │  7. Respect precision rules      │
                    │     from exchangeInfo            │
                    │                                │
                    │  Output: placed orders          │
                    └─────────┬─────────────────────┘
                              │
                    ┌─────────▼─────────────────────┐
                    │     STATE PERSISTENCE           │
                    │                                │
                    │  Save to bot_state.json:        │
                    │  - Current positions            │
                    │  - Pending order IDs            │
                    │  - Current regime               │
                    │  - Peak portfolio value          │
                    │  - Max drawdown                  │
                    │  - Running metrics               │
                    │  - Last cycle timestamp          │
                    └─────────────────────────────────┘
```

---

## 4. Data Flow Timing

```
TIME ──────────────────────────────────────────────────────────►

Every 60s:  ┌─POLL─┐     ┌─POLL─┐     ┌─POLL─┐     ┌─POLL─┐
            │ticker│     │ticker│     │ticker│     │ticker│
            └──┬───┘     └──┬───┘     └──┬───┘     └──┬───┘
               │            │            │            │
               ▼            ▼            ▼            ▼
            ┌─────────────────────────────────────────────┐
            │           OHLCV sqlite DB                    │
            │  (accumulates 1-min resolution candles)      │
            └──────────────────┬──────────────────────────┘
                               │
Every 5min:                    ▼
            ┌──────────────────────────────────────────┐
            │         MAIN TRADING CYCLE                │
            │  signals → ensemble → optimizer → execute │
            └──────────────────────────────────────────┘

Every 1hr:  ┌──────────┐
            │ HEARTBEAT │ → Telegram: portfolio value, P&L, drawdown
            │ + metrics │ → Compute running Sharpe, Sortino, Calmar
            │ + clock   │ → Sync timestamp with Roostoo server
            └──────────┘

Every 4hr:  ┌──────────┐
            │  REGIME   │ → Re-evaluate Bull/Ranging/Bear
            │ + SENTMT  │ → Fetch Fear & Greed, funding rates
            └──────────┘
```

---

## 5. Module Dependency Map

```
roostoo_client.py ◄──── auth.py
        │
        ├──► ticker_poller.py ──► ohlcv_store.py
        ├──► universe_builder.py
        │
        │    binance_fetcher.py ──► ohlcv_store.py
        │    sentiment_fetcher.py
        │
        │         ohlcv_store.py
        │              │
        │    ┌─────────┼─────────────────┐
        │    │         │                 │
        │    ▼         ▼                 ▼
        │ momentum.py  mean_reversion.py  sector_rotation.py
        │    │         │                 │
        │    └─────────┼─────────────────┘
        │              │
        │              ▼
        │      regime_detector.py
        │              │
        │              ▼
        │        ensemble.py
        │              │
        │              ▼
        │    portfolio_optimizer.py
        │              │
        │              ▼
        │       risk_manager.py ◄──── circuit_breaker.py
        │              │
        │              ▼
        └────► order_executor.py
                       │
                       ▼
               metrics_tracker.py ──► telegram_alerter.py
```

**Key design principle:** Each module depends only on the modules above it in this hierarchy. No circular dependencies. Every module has a clean interface (function calls with typed parameters and return values). No shared mutable global state — all state is passed explicitly or held in the `TradingBot` orchestrator class in `main.py`.

---

## 6. Failure Recovery Flow

```
           ┌──────────────────────┐
           │   Bot process dies    │
           │   (crash, OOM, bug)   │
           └──────────┬───────────┘
                      │
                      ▼
           ┌──────────────────────┐
           │   systemd detects     │
           │   non-zero exit       │
           └──────────┬───────────┘
                      │
                      ▼ (wait 30 seconds)
           ┌──────────────────────┐
           │   systemd restarts    │
           │   bot process         │
           └──────────┬───────────┘
                      │
                      ▼
           ┌──────────────────────┐
           │   STARTUP SEQUENCE    │
           │                       │
           │   1. Load config      │
           │   2. Load .env        │
           │   3. Sync clock       │
           │   4. Load exchangeInfo│
           │   5. *** LOAD STATE ***│◄─── bot_state.json
           │      - positions      │     (written atomically
           │      - peak value     │      every cycle)
           │      - pending orders │
           │      - regime         │
           │   6. Verify state     │
           │      against /balance │
           │   7. Resume trading   │
           └──────────┬───────────┘
                      │
                      ▼
           ┌──────────────────────┐
           │   Send Telegram alert │
           │   "Bot restarted.     │
           │    Positions verified."│
           └──────────────────────┘
```

**State verification on restart:** After loading `bot_state.json`, the bot calls `/v3/balance` and `/v3/query_order` (pending_only=TRUE) to reconcile its internal state with the exchange's actual state. Any discrepancies are logged and resolved (e.g., if a limit order filled during downtime, the position is updated accordingly).

---

## 7. Security Boundaries

```
┌─────────────────────────────────────────────────────────┐
│                     AWS EC2 INSTANCE                     │
│                                                          │
│  ┌──────────────────────────────────────────────────┐    │
│  │              /opt/trading-bot/                    │    │
│  │                                                   │    │
│  │  .env (chmod 600) ─── API keys, secrets           │    │
│  │       │                                           │    │
│  │       └──► bot/main.py (reads at startup only)    │    │
│  │                                                   │    │
│  │  data/bot_state.json ─── portfolio state           │    │
│  │  data/live_ohlcv.db ──── price history             │    │
│  │  logs/ ────────────────── operational logs         │    │
│  │                                                   │    │
│  └──────────────────────────────────────────────────┘    │
│                                                          │
│  OUTBOUND CONNECTIONS ONLY:                              │
│  → https://mock-api.roostoo.com  (trading)               │
│  → https://api.binance.com       (historical data)       │
│  → https://api.alternative.me    (sentiment)             │
│  → https://api.telegram.org      (monitoring)            │
│                                                          │
│  NO INBOUND CONNECTIONS (Session Manager only)           │
└─────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────┐
│                    GITHUB REPOSITORY                     │
│                                                          │
│  PUBLIC (after submission):                              │
│  - All Python source code                                │
│  - Config templates (no real values)                     │
│  - Tests                                                 │
│  - README, requirements.txt                              │
│                                                          │
│  NEVER IN REPO:                                          │
│  - .env files                                            │
│  - API keys or secrets                                   │
│  - sqlite databases                                      │
│  - Log files                                             │
│  - bot_state.json                                        │
└─────────────────────────────────────────────────────────┘
```

---

*End of Document 5*

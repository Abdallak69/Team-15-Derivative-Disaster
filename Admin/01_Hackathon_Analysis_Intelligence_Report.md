# Hackathon Analysis & Intelligence Report
## SG vs HK University Web3 Quant Trading Hackathon — Roostoo

**Team:** TBC (Lead), TBC, TBC, TBC
**Date Prepared:** 18 March 2026
**Classification:** Internal — Do Not Share

---

## 1. Competition Overview

The hackathon requires each team to build and deploy a **fully autonomous crypto trading bot** that competes on the Roostoo Mock Exchange platform. The bot must interface with the Roostoo REST API to fetch market data, manage portfolio positions, and execute trades — all without manual intervention.

The platform sources **real-time price data directly from Binance** across **66 crypto assets paired with USDT** (displayed as `/USD` in the API). Each team starts with a **$1,000,000 virtual USD portfolio**.

---

## 2. Hard Rules and Constraints

### 2.1 Trading Constraints

| Constraint | Detail | Source |
|---|---|---|
| Trading type | **Spot only** — no perpetuals, no futures, no options | Intro session, 20:00–20:10 |
| Shorting | **Forbidden** — platform has no short-sell functionality | Intro session, 20:10 |
| Leverage | **None available** | Intro session, 20:10 |
| Arbitrage | **Not possible** — single-platform competition, no cross-exchange execution | Q&A session, 41:01 |
| Market making | Technically not forbidden, but the organisers describe the competition as "directional or discretionary strategy-based" | Intro session, 19:59–20:06 |
| Manual trading | **Strictly forbidden** — every API call must originate from bot code. Manual calls result in disqualification from finalist selection | Q&A session, 54:13–54:29 |
| Minimum activity | Bot must run actively for **at least 8 out of 10 days** making trades | Intro session, 20:39 |

### 2.2 Commission Structure

| Order Type | Commission Rate | Cost per $100K round-trip |
|---|---|---|
| Market (Taker) | **0.1% (10 bps)** | $200 |
| Limit (Maker) | **0.05% (5 bps)** | $100 |

**Critical note:** The API documentation examples show lower rates (0.012% taker, 0.008% maker) — these are default Roostoo app rates, **not the hackathon rates**. The hackathon-specific rates of 0.1%/0.05% were stated explicitly by Edward at timestamp 21:07–21:13 and confirmed in the Q&A at 47:39–47:54. **Trust the hackathon rates.**

**Commission impact modelling over 10 days:**

| Trading frequency | Est. daily turnover | 10-day commission (market) | 10-day commission (limit) |
|---|---|---|---|
| Conservative (1 rebalance/day) | $200K | $20,000 (2.0%) | $10,000 (1.0%) |
| Moderate (3 rebalances/day) | $600K | $60,000 (6.0%) | $30,000 (3.0%) |
| Aggressive (10+ trades/day) | $2M+ | $200,000+ (20%+) | $100,000+ (10%+) |

The commission structure makes high-frequency trading economically suicidal. A bot executing 50 market-order round-trips per day would haemorrhage roughly $100K in fees over 10 days — wiping out any conceivable alpha from a spot-only strategy. **Limit orders at 5 bps are non-negotiable.**

### 2.3 API Rate Limits

The intro session (timestamp 40:51) mentions **30–60 calls per minute**. The HK edition FAQ enforced a stricter **1 trade per minute** hard cap on order placement. The actual limit for the SG vs HK edition should be confirmed once keys are received, but design for the conservative case: **max 1 order placement per minute, max 30 data-fetch calls per minute**.

### 2.4 Order Execution Mechanics

| Property | Detail |
|---|---|
| Slippage | **Zero** — the simulator fills at the stated price |
| Market impact | **Zero** — order size does not move the price |
| Order matching | Roostoo's internal engine acts as market maker; all orders fill |
| Market orders | Filled immediately at `LastPrice` |
| Limit orders | Filled when the real Binance price crosses the limit price |
| Minimum order size | `price × quantity > MiniOrder` (typically $1.00 per pair) |

**Implication:** Zero slippage + zero market impact means large position sizes in small-cap altcoins are feasible without the execution costs that would destroy such trades in real markets. This is a structural advantage worth exploiting.

---

## 3. API Reference Summary

Base URL: `https://mock-api.roostoo.com`

### 3.1 Authentication

All signed endpoints require:
- Header `RST-API-KEY`: your API key
- Header `MSG-SIGNATURE`: HMAC SHA256 of alphabetically-sorted, `&`-joined `key=value` parameters using your secret key
- Parameter `timestamp`: 13-digit millisecond timestamp (server rejects if `|serverTime - timestamp| > 60,000ms`)
- POST requests: header `Content-Type: application/x-www-form-urlencoded`

### 3.2 Complete Endpoint Reference

| # | Endpoint | Method | Auth | Purpose |
|---|---|---|---|---|
| 1 | `/v3/serverTime` | GET | None | Returns server time; use to calibrate clock offset |
| 2 | `/v3/exchangeInfo` | GET | None | Returns all tradeable pairs with precision rules and min order size |
| 3 | `/v3/ticker` | GET | Timestamp only | Returns current ticker for one or all pairs (MaxBid, MinAsk, LastPrice, 24h Change, Volume) |
| 4 | `/v3/balance` | GET | Full HMAC | Returns wallet balances (Free + Locked per asset) |
| 5 | `/v3/pending_count` | GET | Full HMAC | Returns count of pending limit orders per pair |
| 6 | `/v3/place_order` | POST | Full HMAC | Places BUY/SELL, MARKET/LIMIT orders |
| 7 | `/v3/query_order` | POST | Full HMAC | Queries order history; filter by order_id, pair, pending_only |
| 8 | `/v3/cancel_order` | POST | Full HMAC | Cancels pending orders by order_id, pair, or all |

### 3.3 Key API Limitations

The API has **no** candlestick/kline endpoint, **no** orderbook depth endpoint, **no** WebSocket streaming, and **no** historical data endpoint. The ticker endpoint returns only a snapshot of the current state. **Teams must build their own historical price database by polling the ticker endpoint at regular intervals.** This is the single most important pre-competition preparation task.

### 3.4 Ticker Response Fields

| Field | Description | Use Case |
|---|---|---|
| `MaxBid` | Highest bid price | Spread calculation |
| `MinAsk` | Lowest ask price | Spread calculation |
| `LastPrice` | Most recent trade price | Signal generation, OHLCV construction |
| `Change` | 24-hour price change as decimal (e.g., -0.0132 = -1.32%) | Momentum screening |
| `CoinTradeValue` | 24-hour volume in base currency | Liquidity filtering |
| `UnitTradeValue` | 24-hour volume in USD | Liquidity filtering, universe selection |

---

## 4. Tournament Structure

### 4.1 Timeline

| Date | Event |
|---|---|
| 13 March 2026 | Intro session (completed) |
| 16 March 2026 (Sunday) | Resource packs, API keys, AWS credentials distributed |
| 17 March 2026 (Monday) | **Round 1 starts** — City qualifier |
| ~27 March 2026 | Round 1 ends (10 trading days) |
| 28 March 2026 | **Repo submission deadline** (must submit GitHub link to be eligible) |
| 2 April 2026 | Finalist announcement — top 8 from each city |
| 4 April 2026 | **Round 2 starts** — Head-to-head SG vs HK (16 teams) |
| ~14 April 2026 | Round 2 ends (10 trading days) |
| 17 April 2026 | **Presentation deck submission deadline** |
| 17–21 April 2026 | **Physical finals** — 8-minute presentation + 4-minute Q&A |

### 4.2 Competition Format

**Round 1 (City Qualifier):** All registered teams compete within their city. Top 8 from HK and top 8 from SG advance to Round 2. Selection is based on portfolio returns, risk-adjusted metrics, and code/strategy review.

**Round 2 (Head-to-Head):** 16 finalists compete individually, but aggregate city performance also matters — the average return across each city's 8 teams determines the "Winning City" award.

**Physical Finals:** Each finalist team presents (max 12 slides, 8 minutes + 4-minute Q&A). Judges are sponsors: Flow Traders (gold), Jane Street (silver), and other institutional partners.

### 4.3 Evaluation Criteria

**Three award categories, 22 prize slots:**

**Category 1: Best Finalist Presentation (6 awards)**
Judged qualitatively by sponsor panel on: strategy narrative, technical depth, risk management framework, backtest rigour, code quality, and presentation clarity.

**Category 2: Performance Reward (8 awards across both rounds)**
Sub-categories:
- **Highest Return** — pure portfolio return ranking
- **Best Composite Score** — weighted risk-adjusted metric:

| Metric | Weight | Formula |
|---|---|---|
| Sortino Ratio | **40%** | (Return - Target) / Downside Deviation |
| Sharpe Ratio | **30%** | (Return - Risk-free) / Total Std Dev |
| Calmar Ratio | **30%** | Annualised Return / Max Drawdown |

**Category 3: Winning City Award (8 awards)**
Aggregate average return of each city's 8 finalist teams.

**Total prize pool:** HK$62,000 / S$10,000 + career opportunities (assessment slots at sponsors, networking dinners, company visits).

---

## 5. AWS Infrastructure

| Specification | Detail |
|---|---|
| Instance type | **T3.medium** |
| vCPUs | 2 (burstable, 20% baseline per vCPU) |
| RAM | **4 GiB** |
| CPU credits | 24 earned/hour, 576 max balance |
| Region | **ap-southeast-1 (Singapore)** |
| Connection | **Session Manager only** (no SSH, no key pair) |
| Limit | **1 instance per team** (additional instances auto-terminated) |
| Template | Pre-configured launch template provided |

**Burstable CPU means:** At steady state, the bot can use up to 20% of each vCPU (40% total) continuously. A typical Python trading bot uses 2–8% CPU, well within baseline. CPU credits accumulate for burst periods (data processing, ML inference).

---

## 6. Non-Obvious Insights and Competitive Edges

### 6.1 Pre-Competition Data Collection (Critical)
The testing API keys work **before** the competition starts. The ticker endpoint requires only a timestamp (no full auth). **Start polling ticker data immediately upon receiving testing keys** — by competition day 1, a team could have 3–7 days of 1-minute OHLCV data already stored, enabling proper indicator calibration and backtesting. Most teams will not think to do this.

### 6.2 The Limit Order Discount is Massive
At 5 bps vs 10 bps, limit orders save 50% on every trade. Over 10 days of active trading, this compounds to thousands of dollars. In a zero-slippage simulator, a limit order placed at `LastPrice` will fill immediately (or very quickly) since the simulated exchange matches when real Binance price crosses the limit. There is no practical disadvantage to using limit orders in this environment — it's free money.

### 6.3 Zero Market Impact Opens Up Small-Cap Allocation
In real markets, buying $200K of a low-liquidity altcoin would cause 1–5% slippage. Here, it costs nothing beyond the flat commission rate. This means the team can allocate meaningful capital to high-momentum small-caps without the execution penalty that would exist in production. **Small-cap momentum is over-rewarded in this simulation.**

### 6.4 The Leaderboard Delay Prevents Copy-Trading but Enables Self-Monitoring
While you cannot see competitors' positions in real time, you can compute your own Sharpe/Sortino/Calmar in real time. A live metrics dashboard allows dynamic risk adjustment: if current Calmar is at risk (drawdown approaching 3%), the bot can automatically de-risk. **Build real-time metric computation into the bot itself.**

### 6.5 Commission Rates in API Responses vs Hackathon Rates
The API response example shows `CommissionPercent: 0.00012` (1.2 bps) for taker orders. The hackathon rates are 10 bps (taker) and 5 bps (maker). This discrepancy may mean either: (a) the hackathon platform is configured differently from the default API, or (b) the API response reflects the actual rate applied. **Log every trade's `CommissionChargeValue` and `CommissionPercent` from day 1 to determine the actual rate being applied.** If the real rate turns out to be 1.2 bps rather than 10 bps, the entire commission-minimisation strategy becomes less critical and higher-frequency trading becomes viable.

### 6.6 The Presentation is a Separate Win Condition
Teams can win "Best Finalist Presentation" independently of raw returns. The judges are from Flow Traders and Jane Street — firms that value: statistical rigour, clean code architecture, honest acknowledgement of limitations, clear risk framework, and evidence of iterative improvement. A team with average returns but an exceptional presentation (git history showing disciplined iteration, proper backtest methodology, honest drawdown analysis) can win this category.

### 6.7 Strategy Iteration is Permitted and Documented via Git
The competition explicitly allows strategy updates during the 10-day period. Each commit to the repo must clearly describe the change. This means **the strategy does not need to be perfect on day 1** — in fact, demonstrating intelligent iteration (e.g., "Day 3: added regime detection after observing ranging market") is a positive signal to judges.

### 6.8 External Data Sources are Explicitly Allowed
The organisers confirmed (Q&A, 54:32–54:41) that teams may use external APIs including news sentiment, Yahoo Finance, and AI models. Most teams will rely solely on the Roostoo ticker data. **Teams that integrate Fear & Greed Index, Binance funding rates, or on-chain exchange flows will have a significant information advantage.**

### 6.9 The `/v3/exchangeInfo` Response Reveals the Full Universe
Rather than guessing which 66 assets are available, call `exchangeInfo` at startup and dynamically build the tradeable universe. This response also contains `PricePrecision`, `AmountPrecision`, and `MiniOrder` per pair — failure to respect these results in rejected orders.

### 6.10 Clock Synchronisation is a Failure Point
The server rejects requests where `|serverTime - timestamp| > 60,000ms`. AWS instances can drift. **Call `/v3/serverTime` at startup and every hour to compute and apply a clock offset.** Failure to do this is one of the most common causes of authentication errors in production trading bots.

---

## 7. Risk Register

| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| Bot crash during off-hours | Medium | High — missed trading days | systemd with auto-restart; Telegram heartbeat alerts |
| AWS instance terminated | Low | Critical — total downtime | State persistence to disk; documented restart procedure |
| API rate limit exceeded | Medium | Medium — rejected requests | Exponential backoff; request spacing logic |
| Clock drift causing auth failures | Medium | High — all requests fail | Hourly time sync against `/v3/serverTime` |
| Large drawdown on Day 1 | Medium | Critical — Calmar permanently damaged | Conservative Day 1 allocation (max 30% deployed) |
| Competition keys used during testing | Low | Critical — disqualification | Separate config files for test vs competition; code review before go-live |
| External data source goes down | Medium | Low — fallback to price-only signals | Graceful degradation; cache last-known values |
| Memory leak over 10 days | Medium | High — OOM crash | Fixed-size buffers; periodic gc.collect(); memory monitoring |

---

*End of Document 1*

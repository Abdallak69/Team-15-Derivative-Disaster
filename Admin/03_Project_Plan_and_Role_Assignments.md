# Project Plan & Role Assignments
## SG vs HK University Web3 Quant Trading Hackathon

**Team:** TBC, TBC, TBC, TBC
**Date Prepared:** 18 March 2026

---

## 1. Tech Stack

| Layer | Technology | Rationale |
|---|---|---|
| **Language** | Python 3.11+ | Team familiarity; richest quant library ecosystem |
| **HTTP Client** | `requests` + `tenacity` (retry logic) | Simple, reliable, retry-on-failure built in |
| **Data Storage** | `sqlite3` (local DB on EC2) | Zero-dependency, file-based, survives crashes. Stores OHLCV history, trade log, state. |
| **Data Processing** | `pandas`, `numpy` | Standard quant stack; efficient for time-series |
| **Technical Indicators** | `ta` (Technical Analysis library) | Pre-built RSI, MACD, Bollinger Bands, ATR; well-tested |
| **Statistics** | `scipy.stats` | ADF test for cointegration, Z-scores |
| **Scheduling** | `APScheduler` (Advanced Python Scheduler) | Cron-like job scheduling within a single process; avoids crontab complexity |
| **Secrets** | `python-dotenv` + `.env` file | API keys never in code; .env excluded from git |
| **Logging** | `logging` with `RotatingFileHandler` | Size-capped log rotation; prevents disk fill over 10 days |
| **Monitoring** | Telegram Bot API (`requests` to `api.telegram.org`) | Push alerts for heartbeats, errors, circuit breaker triggers |
| **Process Management** | `systemd` service on EC2 | Auto-restart on crash; survives Session Manager disconnect |
| **Version Control** | Git (GitHub private repo → made public for submission) | Commit history is a judging criterion |
| **External Data** | Binance public API, Alternative.me Fear & Greed API | Klines for historical data, sentiment for overlay |

**Deliberately excluded:**
- No Docker (overhead on 4GB RAM; unnecessary for a single Python process)
- No Redis/PostgreSQL (overkill; sqlite3 handles all persistence needs)
- No ML frameworks (no GPU; sklearn only if needed for simple classification)
- No WebSockets (Roostoo API is REST-only)

---

## 2. Project Phases

### PHASE 0: Setup & Reconnaissance (18–20 March)
**Duration:** 3 days (before competition keys arrive)
**Objective:** Infrastructure ready, backtesting complete, bot skeleton deployed.

| Task | Owner | Deliverable | Done When |
|---|---|---|---|
| Create GitHub private repo with branch protection | TBC | Repo URL shared with team | Repo exists, all 4 members have push access |
| Set up project structure (see Architecture doc) | TBC | Directory tree committed to `main` | `python -c "from bot.main import TradingBot"` succeeds |
| Write Roostoo API client wrapper | TBC | `bot/api/roostoo_client.py` | All 8 endpoints callable; unit tests pass with mock responses |
| Write HMAC authentication module | TBC | `bot/api/auth.py` | Signature matches the documented example exactly |
| Write Binance historical kline fetcher | TBC | `bot/data/binance_fetcher.py` | 90 days of 1h klines for 66 assets stored in sqlite |
| Download & store 180 days of historical data | TBC | `data/historical_klines.db` (sqlite) | Data integrity checks pass; no gaps |
| Implement momentum signal module | TBC | `bot/signals/momentum.py` | Backtest on historical data shows positive Sharpe |
| Implement mean-reversion signal module | TBC | `bot/signals/mean_reversion.py` | Backtest identifies valid entry/exit points |
| Implement regime detection module | TBC | `bot/strategy/regime_detector.py` | Classifies 90 days of history into Bull/Ranging/Bear with >60% accuracy |
| Implement ensemble combiner | TBC | `bot/strategy/ensemble.py` | Takes regime + signals, outputs target portfolio weights |
| Implement risk manager | TBC | `bot/risk/risk_manager.py` | Stop-loss, circuit breaker, position limits all enforced in tests |
| Set up AWS EC2 instance | TBC | Instance running, Session Manager connected | `sudo systemctl status tradingbot` shows service configured |
| Configure systemd service file | TBC | `/etc/systemd/system/tradingbot.service` | Bot auto-restarts within 30s of `kill -9` |
| Set up Telegram monitoring bot | TBC | `bot/monitoring/telegram_alerter.py` | Team receives test heartbeat message |
| Backtest full ensemble strategy | TBC | `notebooks/backtest_results.ipynb` | 10-day rolling Sharpe > 1.0, Sortino > 1.5, max DD < 5% |
| Write Fear & Greed Index fetcher | TBC | `bot/data/sentiment_fetcher.py` | Stores daily FGI values; graceful fallback on API failure |

### PHASE 1: Testing & Calibration (20–22 March)
**Duration:** 2 days (using testing API keys)
**Objective:** Bot runs end-to-end on the Roostoo test environment. All API calls verified. Parameters calibrated.

| Task | Owner | Deliverable | Done When |
|---|---|---|---|
| Test all 8 Roostoo API endpoints with testing keys | TBC | Test log showing successful responses for every endpoint | All endpoints return `Success: true` |
| Verify commission rates (check actual `CommissionPercent` in responses) | TBC | Documented actual rates | Rate confirmed and hardcoded in config |
| Call `exchangeInfo` and build dynamic asset universe | TBC | `bot/data/universe_builder.py` | Full list of 66 pairs stored and validated |
| Start ticker polling every 60 seconds (build OHLCV DB) | TBC | Continuous data collection running on EC2 | sqlite DB growing; 1-minute candles accumulating |
| Run bot in "paper mode" (signals generated, no orders placed) | TBC | Log file showing signal outputs and would-be trades | Signals are sensible; no obvious bugs |
| Calibrate indicator parameters (EMA periods, RSI thresholds) against pre-competition data | TBC | Updated `config/strategy_params.yaml` | Parameters justified by backtest results |
| Load-test the bot: simulate 24h of continuous operation | TBC | Uptime log | No crashes, memory stable, no disk fill |
| Dry-run deployment procedure: git pull → restart → verify | TBC | Documented deployment checklist | Procedure takes < 5 minutes end-to-end |
| Create competition `.env` file (DO NOT deploy yet) | TBC | `.env.competition` file (encrypted/secured) | File exists, gitignored, ready to swap |

### PHASE 2: Round 1 Competition (17–27 March, 10 trading days)
**Objective:** Achieve top-8 city ranking on both raw return and composite score.

| Day | Focus | Allocated Capital | Key Actions |
|---|---|---|---|
| Day 1 | **Conservative entry** | Max 30% deployed | Swap to competition keys. Deploy only BTC/ETH positions. Tight -2% stops. Monitor for 6h before scaling. |
| Day 2 | **Gradual scale-up** | 40–50% deployed | Regime detector has 24h+ of data. Begin adding altcoin positions per momentum signals. |
| Day 3 | **Full deployment** | 60–80% deployed | All modules active. First strategy checkpoint: log all metrics. |
| Day 4–5 | **Monitor & tune** | Per regime | Review P&L, commission drag, signal accuracy. First potential git commit to adjust parameters. |
| Day 6–7 | **Mid-competition review** | Per regime | If behind: consider increasing risk budget by 10%. If ahead: tighten stops to protect lead. |
| Day 8–9 | **Stability focus** | Per regime | No major strategy changes. Focus on reliability. Reduce position sizes slightly to lock in gains. |
| Day 10 | **Wind-down** | Reduce to 50% | Sell volatile positions to reduce end-of-period drawdown risk. Lock profits. |

**Ongoing daily tasks during Round 1:**

| Task | Owner | Frequency |
|---|---|---|
| Monitor Telegram alerts; respond to any anomalies | TBC | Continuous |
| Review daily P&L and metrics (Sharpe/Sortino/Calmar) | TBC | Once daily, morning |
| Check data pipeline health (ticker polling, sentiment API) | TBC | Once daily |
| Analyse signal performance; identify weak signals | TBC | Once daily |
| Git commit any parameter changes with descriptive messages | Whoever makes the change | As needed |

### PHASE 3: Repo Submission (28 March)
**Objective:** Clean, documented repo submitted before deadline.

| Task | Owner | Deliverable | Done When |
|---|---|---|---|
| Clean up code: remove debug prints, add docstrings | All | Clean codebase | Passes `pylint` with score > 8/10 |
| Write README.md with setup instructions, strategy overview | TBC | `README.md` | A stranger could understand and run the bot from the README |
| Add `requirements.txt` with pinned versions | TBC | `requirements.txt` | `pip install -r requirements.txt` succeeds on fresh venv |
| Ensure `.env` and API keys are NOT in repo | TBC | `.gitignore` verified | No secrets in git history |
| Make repo public (or share link as instructed) | TBC | Submission link | Confirmed accessible by organisers |

### PHASE 4: Round 2 Preparation (2–4 April)
**Objective:** Iterate strategy based on Round 1 learnings.

| Task | Owner | Deliverable |
|---|---|---|
| Post-mortem: analyse Round 1 performance day-by-day | TBC | Written analysis of what worked and what didn't |
| Identify parameter adjustments or module additions | TBC | Updated `config/strategy_params.yaml` |
| Strengthen weakest-performing module | TBC | Improved code + backtest validation |
| Harden infrastructure based on any issues from Round 1 | TBC | Patched deployment |
| Pre-load historical data from Round 1 into the bot's DB | TBC | Richer data foundation for Round 2 signals |

### PHASE 5: Round 2 Competition (4–14 April)
Same operational cadence as Phase 2, incorporating Round 1 lessons.

### PHASE 6: Finals Presentation (14–17 April)
**Objective:** Win "Best Finalist Presentation" category.

| Task | Owner | Deliverable |
|---|---|---|
| Draft 12-slide presentation deck | TBC, all contribute | `finals_deck.pptx` |
| Slide 1: Team intro + one-sentence strategy summary | TBC | Completed slide |
| Slides 2–3: Market thesis + strategy architecture diagram | TBC | Completed slides |
| Slides 4–5: Signal generation (momentum, mean-reversion, sentiment) with backtest evidence | TBC | Completed slides with charts |
| Slide 6: Risk management framework (stop-losses, circuit breakers, Calmar protection) | TBC | Completed slide |
| Slide 7: Technical architecture + AWS deployment diagram | TBC | Completed slide |
| Slides 8–9: Round 1 and Round 2 results (equity curves, metric values, commission analysis) | TBC | Completed slides with data visualisations |
| Slide 10: Strategy iteration story (git commit timeline showing evolution) | TBC | Completed slide |
| Slide 11: Lessons learned + what would be done differently with more time | All | Completed slide |
| Slide 12: Conclusion + key metrics summary | TBC | Completed slide |
| Rehearse presentation (8 minutes max, timed) | All | 3+ practice runs completed |
| Prepare Q&A responses for anticipated questions | All | Written FAQ document for internal use |

---

## 3. Role Assignments — Detailed Ownership

### TBC (Team Lead)
**Primary:** Strategy architecture, ensemble logic, regime detection, final decisions, presentation lead.
**Owns these files:**
- `bot/strategy/regime_detector.py`
- `bot/strategy/ensemble.py`
- `bot/strategy/portfolio_optimizer.py`
- `config/strategy_params.yaml`
- `README.md`
- Presentation slides 1–3, 12

**Day-to-day during competition:**
- Morning review of overnight metrics (Sharpe, Sortino, Calmar, P&L)
- Decision authority on any strategy parameter changes
- Backup monitoring if TBC is unavailable
- Final approval on any git commit that changes strategy logic

### TBC (Data Pipeline Engineer)
**Primary:** All data ingestion — Roostoo API client, Binance fetcher, sentiment feeds, OHLCV database.
**Owns these files:**
- `bot/api/roostoo_client.py`
- `bot/api/auth.py`
- `bot/data/binance_fetcher.py`
- `bot/data/sentiment_fetcher.py`
- `bot/data/universe_builder.py`
- `bot/data/ohlcv_store.py` (sqlite interface)
- Presentation slides 8–9

**Day-to-day during competition:**
- Monitor data pipeline health (ticker polling continuity, external API availability)
- Ensure sqlite DB integrity (no gaps, no corruption)
- Handle any API-related bugs or authentication issues
- Produce equity curves and performance charts for the presentation

### TBC (Signal & Backtest Engineer)
**Primary:** All trading signal modules, backtesting framework, parameter tuning.
**Owns these files:**
- `bot/signals/momentum.py`
- `bot/signals/mean_reversion.py`
- `bot/signals/pairs_rotation.py`
- `bot/signals/sector_rotation.py`
- `bot/backtest/backtester.py`
- `notebooks/backtest_results.ipynb`
- Presentation slides 4–5, 10

**Day-to-day during competition:**
- Analyse signal hit rates and P&L contribution per module
- Identify underperforming signals and propose parameter adjustments
- Maintain backtest notebooks with updated results
- Document signal rationale in git commit messages

### TBC (Infrastructure & Risk Engineer)
**Primary:** AWS, deployment, monitoring, risk management, crash recovery.
**Owns these files:**
- `bot/risk/risk_manager.py`
- `bot/risk/circuit_breaker.py`
- `bot/execution/order_executor.py`
- `bot/monitoring/telegram_alerter.py`
- `bot/monitoring/metrics_dashboard.py`
- `deploy/tradingbot.service` (systemd config)
- `deploy/setup.sh` (EC2 setup script)
- `.gitignore`, `requirements.txt`
- Presentation slides 6–7

**Day-to-day during competition:**
- Primary on-call for bot health (Telegram alerts)
- Handle any EC2 issues (instance restart, disk space, memory)
- Monitor risk metrics in real time (drawdown, position concentration)
- Execute deployment procedure for any code updates

---

## 4. Communication Protocol

| Channel | Purpose | Cadence |
|---|---|---|
| WhatsApp group (team) | Quick updates, decisions, alerts | Continuous |
| Telegram bot (automated) | Heartbeat, error alerts, daily P&L | Every hour (heartbeat); instant (errors) |
| GitHub Pull Requests | Code changes during competition | As needed; require 1 approval |
| Daily standup (5 min call or async message) | Status update: what worked yesterday, what's planned today, blockers | Every morning, 09:00 HKT |

---

## 5. Key Deliverables Checklist

| # | Deliverable | Format | Deadline | Owner |
|---|---|---|---|---|
| D1 | Working trading bot, deployed on EC2 | Python codebase | Day 1 of Round 1 | All |
| D2 | OHLCV historical database (pre-competition + live) | sqlite3 file | Before Round 1 | TBC |
| D3 | Backtest report with metrics | Jupyter notebook | Before Round 1 | TBC |
| D4 | Git repository with clean commit history | GitHub repo | 28 March (submission) | All |
| D5 | README.md with setup and strategy documentation | Markdown | 28 March | TBC |
| D6 | Round 1 performance analysis | Internal document | 2 April | TBC |
| D7 | Finals presentation deck (max 12 slides) | PowerPoint/PDF | 17 April | All |
| D8 | Rehearsed presentation (8 min + Q&A prep) | Live | Before finals date | All |

---

*End of Document 3*

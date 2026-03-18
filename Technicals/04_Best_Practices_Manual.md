# Best Practices Manual
## SG vs HK University Web3 Quant Trading Hackathon

**Team:** Abdalla (Lead), Sami, Oscar, Wilson
**Date Prepared:** 18 March 2026
**Status:** MANDATORY — all team members must read and follow every item below.

---

## 1. Git & Version Control

### 1.1 Branch Strategy

Use **trunk-based development** with short-lived feature branches:

- `main` — always deployable. This is what runs on EC2.
- `feature/<name>` — e.g., `feature/add-sentiment-overlay`. Branched from `main`, merged back via PR within 24 hours.
- `hotfix/<name>` — emergency fixes during competition. Can be merged directly to `main` with post-merge review.

**Never push directly to `main` during the competition.** All changes go through a PR with at least 1 approval, except hotfixes where the deploying person tags the reviewer in WhatsApp.

### 1.2 Commit Messages

Every commit message must follow this format:

```
[MODULE] Short description of change

- Specific detail of what changed and why
- Reference to metric impact if applicable
```

Examples:
```
[MOMENTUM] Reduce lookback from 7d to 5d based on backtest

- 5-day lookback improved hit rate from 52% to 58% on validation set
- Sharpe improvement: 0.82 → 1.04 on 90-day backtest

[RISK] Lower circuit breaker from -5% to -3%

- Day 3 drawdown reached -4.2%, triggering concern about Calmar
- Tighter threshold reduces max potential drawdown at cost of more frequent pauses

[INFRA] Add swap space and memory monitoring

- T3.medium OOMed during overnight data processing
- Added 4GB swap + gc.collect() calls in main loop
```

### 1.3 Git Tags for Deployments

Every time a new version is deployed to EC2, tag it:

```bash
git tag -a v1.0-baseline -m "Initial competition deployment: momentum + mean-reversion"
git tag -a v1.1-add-sentiment -m "Added Fear/Greed overlay per Day 3 analysis"
git tag -a v1.2-tighten-stops -m "Reduced per-position stop from 5% to 3%"
```

This commit/tag history becomes part of the presentation narrative. Judges at Flow Traders and Jane Street will review it.

### 1.4 .gitignore (Non-Negotiable)

The following must **never** appear in the repository:

```
.env
.env.*
*.key
*secret*
data/*.db
data/*.sqlite
__pycache__/
*.pyc
.venv/
logs/
*.log
```

**Before making the repo public:** Run `git log --all --full-history -- "*.env" "*.key"` to verify no secrets exist in history. If they do, use `git filter-branch` or BFG Repo Cleaner to purge them.

---

## 2. Code Quality

### 2.1 File Naming & Structure

- All Python files: `snake_case.py`
- All class names: `PascalCase`
- All function/variable names: `snake_case`
- All config keys: `UPPER_SNAKE_CASE` in `.env`, `lower_snake_case` in YAML
- Maximum file length: 300 lines. If a file exceeds this, split it.

### 2.2 Type Hints

Use type hints on every function signature. This is not optional — it catches bugs before runtime that could crash the bot at hour 100.

```python
def calculate_momentum_score(
    prices: pd.DataFrame,
    lookback_days: int = 5,
    min_volume_usd: float = 10_000_000.0
) -> dict[str, float]:
    """Return {pair: score} for all pairs exceeding volume threshold."""
```

### 2.3 Error Handling

**Every API call must be wrapped in try/except with retry logic.** The bot runs for 240 hours unattended — a single unhandled exception kills it.

Pattern for all API calls:

```python
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type

@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=2, max=30),
    retry=retry_if_exception_type((requests.ConnectionError, requests.Timeout)),
    before_sleep=lambda retry_state: logger.warning(
        f"API retry #{retry_state.attempt_number}: {retry_state.outcome.exception()}"
    )
)
def get_ticker(self, pair: str | None = None) -> dict:
    """Fetch ticker data with automatic retry on transient failures."""
    ...
```

**Never use bare `except:`.** Always catch specific exception types. If genuinely unsure, use `except Exception as e:` with full traceback logging.

### 2.4 Logging Standards

Three log streams, each with a `RotatingFileHandler` (10MB max, 5 backups):

| Log File | Content | Format |
|---|---|---|
| `logs/trades.jsonl` | Every order placed/filled/cancelled | JSON lines (machine-parseable for analysis) |
| `logs/signals.log` | Signal generation outputs, regime changes | Timestamped text |
| `logs/system.log` | Errors, warnings, startup/shutdown, heartbeats | Timestamped text with log level |

**Trade log format (one JSON object per line):**
```json
{"ts": "2026-03-17T08:00:00Z", "action": "BUY", "pair": "BTC/USD", "type": "LIMIT", "qty": 0.15, "price": 85000.00, "order_id": 123, "status": "FILLED", "commission": 6.375, "portfolio_value": 1003250.00, "drawdown_pct": 0.0}
```

**Every log entry must include a UTC timestamp.** Never use local time.

### 2.5 Configuration Management

All tuneable parameters live in `config/strategy_params.yaml`, not hardcoded in Python:

```yaml
regime:
  ema_fast_period: 20
  ema_slow_period: 50
  volatility_lookback: 14
  volatility_threshold_multiplier: 1.5
  confirmation_periods: 2

momentum:
  lookback_days: [3, 5, 7]  # equally weighted composite
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

risk:
  max_position_pct: 0.10
  cash_floor_bull: 0.20
  cash_floor_ranging: 0.40
  cash_floor_bear: 0.50
  stop_loss_pct: 0.03
  circuit_breaker_l1: 0.03
  circuit_breaker_l2: 0.05
  daily_loss_limit: 0.02

execution:
  prefer_limit_orders: true
  limit_offset_pct: 0.0001  # place limit at LastPrice ± 0.01%
  min_rebalance_drift: 0.15  # rebalance when position drifts >15% from target
  order_spacing_seconds: 65  # minimum seconds between order placements
```

**Changing a parameter requires:** (1) update YAML, (2) git commit with rationale, (3) deploy to EC2, (4) verify bot loaded new config via log output.

---

## 3. API Key Security

### 3.1 Storage

- API keys and secrets stored **only** in `.env` file on the EC2 instance
- `.env` is in `.gitignore` — never committed
- The `.env` file has `chmod 600` permissions (owner read/write only)
- No API keys in Python code, YAML config, Jupyter notebooks, or commit messages

### 3.2 Two Key Sets

| Key Set | Purpose | When to Use | Stored As |
|---|---|---|---|
| Testing keys | Pre-competition testing | Phase 0 and Phase 1 only | `.env.testing` |
| Competition keys | Live competition | Phase 2 onwards | `.env.competition` |

**Switching keys:** `cp .env.competition .env && sudo systemctl restart tradingbot`

**Pre-flight check before Round 1:** Verify the `.env` file contains competition keys, not testing keys. Abdalla and Wilson both independently verify.

### 3.3 Key Rotation Emergency

If keys are accidentally exposed (pushed to git, shared in chat):
1. Immediately contact Roostoo support on WhatsApp
2. Stop the bot (`sudo systemctl stop tradingbot`)
3. Remove the exposed commit (`git revert` or `git filter-branch`)
4. Wait for new keys before resuming

---

## 4. AWS EC2 Operations

### 4.1 Initial Setup Script

Run once after instance launch:

```bash
#!/bin/bash
# deploy/setup.sh — run as root or with sudo

# System updates
apt-get update && apt-get upgrade -y

# Python setup
apt-get install -y python3.11 python3.11-venv python3-pip git sqlite3

# Swap space (critical for 4GB instance)
fallocate -l 4G /swapfile
chmod 600 /swapfile
mkswap /swapfile
swapon /swapfile
echo '/swapfile none swap sw 0 0' >> /etc/fstab
sysctl vm.swappiness=10
echo 'vm.swappiness=10' >> /etc/sysctl.conf

# NTP time sync (critical for API timestamp validation)
timedatectl set-ntp true

# Create bot user directory
mkdir -p /opt/trading-bot
cd /opt/trading-bot

# Clone repo
git clone https://github.com/<team-repo>.git .
python3.11 -m venv venv
source venv/bin/activate
pip install -r requirements.txt

# Create log directory
mkdir -p logs data

# Copy .env file (manually — never in this script)
echo "REMINDER: Manually create /opt/trading-bot/.env with API keys"
```

### 4.2 systemd Service File

```ini
# /etc/systemd/system/tradingbot.service
[Unit]
Description=Roostoo Trading Bot
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=ssm-user
WorkingDirectory=/opt/trading-bot
EnvironmentFile=/opt/trading-bot/.env
ExecStart=/opt/trading-bot/venv/bin/python -u bot/main.py
Restart=on-failure
RestartSec=30
StartLimitBurst=5
StartLimitIntervalSec=300
StandardOutput=append:/opt/trading-bot/logs/system.log
StandardError=append:/opt/trading-bot/logs/system.log

[Install]
WantedBy=multi-user.target
```

Key settings explained:
- `Restart=on-failure` — auto-restart if the process exits with non-zero code
- `RestartSec=30` — wait 30 seconds before restarting (avoids rapid restart loops)
- `StartLimitBurst=5` within `StartLimitIntervalSec=300` — if it crashes 5 times in 5 minutes, stop trying (something is fundamentally broken; investigate manually)
- `-u` flag on Python — unbuffered output so logs appear immediately

### 4.3 Deployment Procedure (During Competition)

```bash
# 1. Connect via Session Manager
# 2. Navigate to bot directory
cd /opt/trading-bot
source venv/bin/activate

# 3. Pull latest code
git pull origin main

# 4. Install any new dependencies
pip install -r requirements.txt --quiet

# 5. Sanity check (does the code import without errors?)
python -c "from bot.main import TradingBot; print('OK')"

# 6. Restart the service
sudo systemctl restart tradingbot.service

# 7. Verify it started successfully
sleep 10
sudo systemctl status tradingbot.service
tail -20 logs/system.log

# 8. Tag the deployment
git tag -a v1.X-description -m "Description of changes"
git push --tags
```

**Never deploy during active trading hours without Abdalla's approval** (unless it's an emergency hotfix for a crashed bot).

### 4.4 Health Monitoring Commands

```bash
# Check bot status
sudo systemctl status tradingbot.service

# View live logs
tail -f logs/system.log

# Check memory usage
free -h

# Check disk usage
df -h

# Check CPU credits (important for T3 burstable)
# Must check in AWS Console → EC2 → Monitoring → CPUCreditBalance

# Check if bot process is running
ps aux | grep python

# Check last N trades
tail -20 logs/trades.jsonl | python -m json.tool
```

---

## 5. Data Integrity

### 5.1 OHLCV Database

The ticker polling process stores data in sqlite. Schema:

```sql
CREATE TABLE IF NOT EXISTS ohlcv (
    pair TEXT NOT NULL,
    timestamp INTEGER NOT NULL,  -- Unix ms
    open REAL,
    high REAL,
    low REAL,
    close REAL,
    volume_coin REAL,
    volume_usd REAL,
    PRIMARY KEY (pair, timestamp)
);

CREATE INDEX IF NOT EXISTS idx_ohlcv_pair_ts ON ohlcv(pair, timestamp);
```

### 5.2 State Persistence

The bot must survive crashes without losing portfolio awareness. After every trading cycle, save state:

```python
import json, os, tempfile

def save_state(state: dict, path: str = "data/bot_state.json"):
    """Atomic write: write to temp file, then rename. Prevents corruption on crash."""
    fd, tmp_path = tempfile.mkstemp(dir=os.path.dirname(path))
    try:
        with os.fdopen(fd, 'w') as f:
            json.dump(state, f, indent=2, default=str)
        os.replace(tmp_path, path)  # atomic on POSIX
    except:
        os.unlink(tmp_path)
        raise
```

State must include: current positions, pending order IDs, last known regime, running P&L metrics, last ticker timestamp, and any active stop-loss levels.

### 5.3 Data Validation

Every piece of data from an external source must be validated before use:

```python
def validate_ticker(data: dict) -> bool:
    """Reject obviously invalid ticker data."""
    if not data.get("Success"):
        return False
    for pair, tick in data.get("Data", {}).items():
        if tick["LastPrice"] <= 0:
            return False
        if tick["MinAsk"] < tick["MaxBid"]:  # inverted spread
            logger.warning(f"Inverted spread on {pair}: ask={tick['MinAsk']} < bid={tick['MaxBid']}")
            return False
    return True
```

---

## 6. Risk Management Implementation

### 6.1 Stop-Loss Execution

Stop-losses are checked every trading cycle (every 60 seconds). They are **not** limit orders on the exchange — they are logic in the bot that triggers a market sell when conditions are met.

```python
def check_stop_losses(self, current_prices: dict):
    for pair, position in self.positions.items():
        if pair not in current_prices:
            continue
        current_price = current_prices[pair]["LastPrice"]
        pnl_pct = (current_price - position["entry_price"]) / position["entry_price"]
        if pnl_pct <= -self.config["risk"]["stop_loss_pct"]:
            logger.warning(f"STOP-LOSS triggered for {pair}: entry={position['entry_price']}, current={current_price}, loss={pnl_pct:.2%}")
            self.execute_sell(pair, position["quantity"], order_type="MARKET")
```

### 6.2 Circuit Breaker

```python
def check_circuit_breaker(self):
    current_value = self.get_portfolio_value()
    drawdown = (self.peak_value - current_value) / self.peak_value

    if drawdown >= self.config["risk"]["circuit_breaker_l2"]:
        logger.critical(f"CIRCUIT BREAKER L2: drawdown={drawdown:.2%}. Liquidating ALL positions.")
        self.sell_all_positions()
        self.paused_until = time.time() + 86400  # 24-hour pause
        self.send_telegram_alert(f"🚨 CIRCUIT BREAKER L2 TRIGGERED. Drawdown: {drawdown:.2%}. Bot paused for 24h.")

    elif drawdown >= self.config["risk"]["circuit_breaker_l1"]:
        logger.warning(f"CIRCUIT BREAKER L1: drawdown={drawdown:.2%}. Reducing positions by 50%.")
        self.reduce_all_positions(0.5)
        self.send_telegram_alert(f"⚠️ CIRCUIT BREAKER L1 TRIGGERED. Drawdown: {drawdown:.2%}. Positions halved.")
```

### 6.3 Peak Tracking for Calmar

```python
def update_peak(self):
    current_value = self.get_portfolio_value()
    if current_value > self.peak_value:
        self.peak_value = current_value
    self.max_drawdown = max(
        self.max_drawdown,
        (self.peak_value - current_value) / self.peak_value
    )
```

This must run **every cycle** — missing an update means the max drawdown calculation could be wrong, which would misrepresent the bot's actual Calmar ratio.

---

## 7. Operational Discipline

### 7.1 Pre-Competition Checklist (Run Before Day 1)

- [ ] `.env` file contains **competition** keys (not testing keys)
- [ ] Two team members independently verify the API key matches the competition key email
- [ ] Bot is running on EC2 and last heartbeat Telegram message received < 5 minutes ago
- [ ] `exchangeInfo` has been called and 66 pairs are loaded
- [ ] Ticker polling is active and data is accumulating in sqlite
- [ ] All risk parameters loaded from YAML (verify in log output)
- [ ] Stop-losses and circuit breakers tested with simulated data
- [ ] Telegram alerts working (send a test alert)
- [ ] Git repo is clean — no uncommitted changes on EC2
- [ ] Disk space > 5GB free
- [ ] Memory usage < 2GB (with 4GB swap configured)
- [ ] Clock offset < 1 second from Roostoo server time

### 7.2 Daily Operations Checklist (Every Morning)

- [ ] Check Telegram: any overnight alerts?
- [ ] Review `system.log` last 100 lines: any errors or warnings?
- [ ] Review `trades.jsonl`: are trades being executed? Commission rates correct?
- [ ] Calculate current portfolio value, Sharpe, Sortino, Calmar
- [ ] Check disk space and memory usage on EC2
- [ ] Check data pipeline: any gaps in OHLCV data?
- [ ] Post update to team WhatsApp: "Day N: Portfolio $X, Return Y%, Max DD Z%"

### 7.3 Emergency Procedures

**Bot crash (detected via missing Telegram heartbeat):**
1. Wilson connects to EC2 via Session Manager
2. Check status: `sudo systemctl status tradingbot.service`
3. If failed: check logs `tail -50 logs/system.log`
4. If OOM: check memory `free -h`; consider reducing data buffer sizes
5. Restart: `sudo systemctl restart tradingbot.service`
6. Verify: wait 2 minutes, check Telegram for heartbeat
7. Post update to team WhatsApp

**AWS instance terminated:**
1. Go to AWS Console → EC2 → Launch Templates
2. Launch new instance from the provided template
3. Re-run `deploy/setup.sh`
4. Restore `.env` file (team lead has a secure backup)
5. Clone repo and restore state from latest `data/bot_state.json` backup
6. Start the service

**Large unexpected drawdown (>3%):**
1. Check if circuit breaker L1 triggered automatically
2. If not, investigate: was it a legitimate market move or a bot bug?
3. If bug: stop bot, fix, redeploy
4. If market move: evaluate whether to override circuit breaker timing
5. Abdalla makes final call on whether to resume or stay in cash

---

## 8. Testing Standards

### 8.1 Unit Tests

Every signal module, every risk check, and every API interaction must have at least one unit test. Use `pytest`.

```
tests/
├── test_roostoo_client.py      # Mock API responses; verify parsing
├── test_auth.py                # Verify HMAC signature matches documented example
├── test_momentum.py            # Verify ranking logic with known inputs
├── test_mean_reversion.py      # Verify entry/exit signals with known inputs
├── test_risk_manager.py        # Verify stop-loss and circuit breaker triggers
├── test_portfolio_optimizer.py # Verify weight calculation and position limits
└── test_state_persistence.py   # Verify save/load cycle preserves data
```

Run all tests before every deployment: `pytest tests/ -v`

### 8.2 The HMAC Signature Test

This is the single most important unit test. If the signature is wrong, every authenticated API call fails.

```python
def test_hmac_signature():
    """Verify our signature matches the documented example exactly."""
    secret = "S1XP1e3UZj6A7H5fATj0jNhqPxxdSJYdInClVN65XAbvqqMKjVHjA7PZj4W12oep"
    params = "pair=BNB/USD&quantity=2000&side=BUY&timestamp=1580774512000&type=MARKET"
    expected = "20b7fd5550b67b3bf0c1684ed0f04885261db8fdabd38611e9e6af23c19b7fff"

    computed = hmac.new(secret.encode(), params.encode(), hashlib.sha256).hexdigest()
    assert computed == expected, f"Signature mismatch: {computed} != {expected}"
```

---

## 9. Communication Rules

### 9.1 Decision Authority

| Decision Type | Who Decides | Who is Informed |
|---|---|---|
| Strategy parameter change | Oscar proposes → Abdalla approves | All |
| Emergency stop/restart | Wilson acts → informs Abdalla within 15 min | All |
| New module addition | Abdalla decides after team discussion | All |
| Budget/risk limit change | Abdalla only | All |
| Git merge to `main` | Any 1 reviewer approves | All |
| Deployment to EC2 | Wilson executes, Abdalla authorises | All |

### 9.2 Escalation Protocol

If anything seems wrong and the primary owner is unreachable for **30+ minutes** during competition hours:
1. The next person in the chain of command acts: Abdalla → Wilson → Sami → Oscar
2. The acting person makes the conservative choice (reduce risk, not increase it)
3. Document the decision and reasoning in WhatsApp

---

*End of Document 4*

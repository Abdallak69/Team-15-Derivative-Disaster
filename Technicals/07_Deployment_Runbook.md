# Deployment Runbook & Go-Live Checklist
## SG vs HK University Web3 Quant Trading Hackathon

**Team:** Abdalla (Lead), Sami, Oscar, Wilson
**Date Prepared:** 18 March 2026
**Primary Deployer:** Wilson
**Authoriser:** Abdalla

---

## SECTION A: One-Time EC2 Setup (Do Once, Before Competition)

**Estimated time: 30 minutes**
**When:** Immediately after receiving AWS credentials (expected 16 March)

### A1. Access the Instance

```
1. Open browser → https://aws.amazon.com
2. Navigate to AWS Access Portal (link from the email)
3. Click "Hackathon Permission Set"
4. Region: ap-southeast-1 (Singapore) ← VERIFY THIS
5. EC2 → Launch Templates → select the provided template
6. Click "Launch instance from template"
7. Do NOT create a key pair (Session Manager only)
8. Click "Launch Instance"
9. Wait 2-3 minutes for instance to initialise
10. EC2 → Instances → select your instance → Connect → Session Manager → Connect
```

**Checkpoint:** You should see a bash terminal in your browser.

### A2. Initial System Setup

Copy-paste this entire block (run as ssm-user, then sudo where needed):

```bash
# Update system packages
sudo apt-get update && sudo apt-get upgrade -y

# Install required system packages
sudo apt-get install -y python3.11 python3.11-venv python3-pip git sqlite3 curl

# Configure swap (CRITICAL for 4GB instance)
sudo fallocate -l 4G /swapfile
sudo chmod 600 /swapfile
sudo mkswap /swapfile
sudo swapon /swapfile
echo '/swapfile none swap sw 0 0' | sudo tee -a /etc/fstab
sudo sysctl vm.swappiness=10
echo 'vm.swappiness=10' | sudo tee -a /etc/sysctl.conf

# Enable NTP time sync (CRITICAL for API timestamp validation)
sudo timedatectl set-ntp true

# Verify swap is active
free -h
# Expected: Swap line shows ~4.0G

# Verify time sync
timedatectl status
# Expected: "NTP service: active"
```

**Checkpoint:** `free -h` shows 4G swap. `timedatectl` shows NTP active.

### A3. Clone Repository and Set Up Python

```bash
# Create working directory
sudo mkdir -p /opt/trading-bot
sudo chown ssm-user:ssm-user /opt/trading-bot
cd /opt/trading-bot

# Clone the repo (replace with actual URL)
git clone https://github.com/<TEAM_ORG>/roostoo-quant-bot.git .

# Create Python virtual environment
python3.11 -m venv venv
source venv/bin/activate

# Install dependencies
pip install --upgrade pip
pip install -r requirements.txt

# Create runtime directories
mkdir -p logs data
```

**Checkpoint:** `python -c "from bot.main import TradingBot; print('OK')"` prints `OK`.

### A4. Create the .env File

```bash
# Create .env with testing keys FIRST
cat > /opt/trading-bot/.env << 'EOF'
# Roostoo API Keys — TESTING
ROOSTOO_API_KEY=<PASTE_TESTING_API_KEY_HERE>
ROOSTOO_SECRET_KEY=<PASTE_TESTING_SECRET_HERE>

# Telegram Bot
TELEGRAM_BOT_TOKEN=<PASTE_BOT_TOKEN_HERE>
TELEGRAM_CHAT_ID=<PASTE_CHAT_ID_HERE>

# Environment flag
ENVIRONMENT=testing
EOF

# Lock down permissions
chmod 600 /opt/trading-bot/.env
```

**⚠️ ALSO create the competition .env (DO NOT USE YET):**

```bash
cat > /opt/trading-bot/.env.competition << 'EOF'
# Roostoo API Keys — COMPETITION (DO NOT USE BEFORE GO-LIVE)
ROOSTOO_API_KEY=<PASTE_COMPETITION_API_KEY_HERE>
ROOSTOO_SECRET_KEY=<PASTE_COMPETITION_SECRET_HERE>

# Telegram Bot (same)
TELEGRAM_BOT_TOKEN=<PASTE_BOT_TOKEN_HERE>
TELEGRAM_CHAT_ID=<PASTE_CHAT_ID_HERE>

# Environment flag
ENVIRONMENT=competition
EOF

chmod 600 /opt/trading-bot/.env.competition
```

**Checkpoint:** `cat /opt/trading-bot/.env` shows testing keys. `.env.competition` exists separately.

### A5. Install systemd Service

```bash
sudo cat > /etc/systemd/system/tradingbot.service << 'EOF'
[Unit]
Description=Roostoo Quant Trading Bot
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
EOF

sudo systemctl daemon-reload
sudo systemctl enable tradingbot.service
```

**Checkpoint:** `sudo systemctl status tradingbot` shows "loaded" (not yet active).

### A6. Start Data Collection (Testing Phase)

```bash
# Start the bot in testing mode — it will begin polling ticker data
sudo systemctl start tradingbot.service
sleep 10
sudo systemctl status tradingbot.service
tail -20 logs/system.log
```

**Checkpoint:** Logs show ticker polling activity. Telegram sends startup message.

---

## SECTION B: Pre-Competition Verification (Day Before Go-Live)

**Estimated time: 20 minutes**
**When:** Evening before Round 1 starts (16 March evening)
**Who:** Wilson (executes) + Abdalla (verifies independently)

### B1. System Health Check

```bash
cd /opt/trading-bot
source venv/bin/activate

# Check the bot is running
sudo systemctl status tradingbot.service

# Check memory
free -h
# PASS if: Used < 3G, Swap used < 1G

# Check disk
df -h /
# PASS if: Available > 5G

# Check data collection
sqlite3 data/live_ohlcv.db "SELECT COUNT(*), MIN(timestamp), MAX(timestamp) FROM ohlcv;"
# PASS if: count > 0, timestamps span multiple days

# Check clock sync
python -c "
from api.roostoo_client import RoostooClient
import os, time
c = RoostooClient(os.getenv('ROOSTOO_API_KEY'), os.getenv('ROOSTOO_SECRET_KEY'))
offset = c.sync_clock()
print(f'Clock offset: {offset}ms')
assert abs(offset) < 5000, f'Clock offset too large: {offset}ms'
print('PASS')
"

# Check Telegram
python -c "
from monitoring.dashboard import TelegramAlerter
import os
t = TelegramAlerter(os.getenv('TELEGRAM_BOT_TOKEN'), os.getenv('TELEGRAM_CHAT_ID'))
t.send_message('✅ Pre-flight check: Telegram working')
print('Check your phone. PASS if message received.')
"
```

### B2. Test All API Endpoints with Testing Keys

```bash
python -c "
from api.roostoo_client import RoostooClient
import os

c = RoostooClient(os.getenv('ROOSTOO_API_KEY'), os.getenv('ROOSTOO_SECRET_KEY'))
c.sync_clock()

print('1. Server time:', c.get_server_time())

info = c.get_exchange_info()
print(f'2. Exchange info: {len(info)} pairs')

tickers = c.get_ticker()
print(f'3. Ticker: {len(tickers)} pairs, BTC={tickers.get(\"BTC/USD\", \"N/A\")}')

balance = c.get_balance()
print(f'4. Balance: USD free={balance.get(\"USD\", \"N/A\")}')

pending = c.get_pending_count()
print(f'5. Pending orders: {pending}')

print()
print('ALL ENDPOINTS VERIFIED')
"
```

**Checkpoint:** All 5 endpoints return valid data. No authentication errors.

### B3. Verify Competition Keys Exist (But Do NOT Use Them)

```bash
# Verify the competition .env file exists and has content
wc -l /opt/trading-bot/.env.competition
# PASS if: shows 7+ lines (the file has content)

# Verify it has different keys from testing
diff <(grep ROOSTOO_API_KEY .env) <(grep ROOSTOO_API_KEY .env.competition)
# PASS if: shows a difference (keys are not the same)
```

### B4. Git Status Check

```bash
cd /opt/trading-bot
git status
# PASS if: "nothing to commit, working tree clean"

git log --oneline -5
# PASS if: shows recent meaningful commits

git tag -l
# PASS if: shows at least one version tag (e.g., v1.0-baseline)
```

---

## SECTION C: GO-LIVE (Competition Day 1)

**⚡ THIS IS THE CRITICAL SECTION ⚡**
**Estimated time: 10 minutes**
**When:** Competition start time (as announced by organisers)
**Who:** Wilson (executes), Abdalla (verifies over screen share)

### C1. Stop the Bot

```bash
sudo systemctl stop tradingbot.service
sleep 5
sudo systemctl status tradingbot.service
# Must show "inactive (dead)"
```

### C2. Swap API Keys

```bash
cd /opt/trading-bot

# Backup testing .env
cp .env .env.testing.bak

# Deploy competition keys
cp .env.competition .env

# VERIFY — read the first line of the API key
head -3 .env
# Abdalla: confirm this matches the competition key from the email
```

**⚠️ DUAL VERIFICATION:** Both Wilson and Abdalla must independently confirm the API key in `.env` matches the competition API key from the organiser's email. Do not proceed until both confirm.

### C3. Start the Bot

```bash
sudo systemctl start tradingbot.service
sleep 15
sudo systemctl status tradingbot.service
# Must show "active (running)"

# Verify it's using competition keys
tail -30 logs/system.log
# Look for: "Clock synced" (confirms API connectivity)
# Look for: "Bot Started" (confirms initialisation)
# Look for: "Exchange info: 66 pairs" (confirms data access)
```

### C4. Verify First Heartbeat

```
Wait 5 minutes. Check Telegram for the startup message.
Wait until the first hourly heartbeat arrives.
Verify:
  - Portfolio value = $1,000,000 (or very close)
  - Positions = 0 (no trades yet — bot starts conservatively)
  - Regime = detected correctly
```

### C5. Git Tag the Go-Live

```bash
cd /opt/trading-bot
git tag -a v1.0-golive -m "Competition go-live: Round 1 started"
git push --tags
```

### C6. Post to Team WhatsApp

```
"🟢 BOT IS LIVE. Competition keys active. Portfolio: $1,000,000.
First heartbeat received. Regime: [X]. No trades yet (conservative start).
Monitoring active. Next check: 1 hour."
```

---

## SECTION D: Mid-Competition Code Update Procedure

**When:** Any time a strategy change is needed during the 10-day competition
**Estimated time: 10 minutes**
**Who:** Wilson (executes), Abdalla (authorises)

### D1. Pre-Deployment

```bash
# 1. Abdalla approves the change (WhatsApp confirmation)
# 2. Code is merged to main via PR (or direct push for hotfix)
# 3. Wilson connects to EC2 via Session Manager

cd /opt/trading-bot
source venv/bin/activate

# 4. Pull the latest code
git pull origin main

# 5. Install any new dependencies
pip install -r requirements.txt --quiet

# 6. Sanity check — does the code import?
python -c "from bot.main import TradingBot; print('Import OK')"
# MUST print "Import OK" before proceeding

# 7. Run unit tests (if available and fast)
python -m pytest tests/ -x -q 2>/dev/null && echo "Tests PASS" || echo "Tests FAIL — investigate"
```

### D2. Deploy

```bash
# 8. Restart the service
sudo systemctl restart tradingbot.service
sleep 15

# 9. Verify restart
sudo systemctl status tradingbot.service
tail -30 logs/system.log
# Look for: "Bot Started" message
# Look for: no errors or exceptions
```

### D3. Post-Deployment

```bash
# 10. Tag the deployment
git tag -a v1.X-description -m "Brief description of change"
git push --tags

# 11. Wait for next heartbeat and verify metrics are sane
# 12. Post to WhatsApp: "Deployed vX.X: [description]. Bot running normally."
```

---

## SECTION E: Emergency Procedures

### E1. Bot Crashed and Won't Restart

**Symptoms:** `systemctl status` shows "failed", or Telegram heartbeats stop arriving.

```bash
# Check what happened
sudo systemctl status tradingbot.service
tail -100 logs/system.log

# Common causes:
# - OOM kill: check `dmesg | grep -i oom`
# - Python exception: check the last traceback in system.log
# - Disk full: check `df -h`

# If OOM: restart and check memory
sudo systemctl restart tradingbot.service
free -h

# If disk full: clear old logs
ls -lh logs/
rm logs/system.log.5 logs/system.log.4  # remove oldest rotated logs
sudo systemctl restart tradingbot.service

# If repeated crashes (5x in 5 minutes): systemd stops trying
# Reset the failure counter and try again:
sudo systemctl reset-failed tradingbot.service
sudo systemctl start tradingbot.service
```

### E2. Instance Terminated

**Symptoms:** Cannot connect via Session Manager. Instance shows "terminated" in EC2 console.

```
1. Go to AWS Console → EC2 → Launch Templates
2. Launch a new instance from the provided template
3. Wait 2-3 minutes
4. Connect via Session Manager
5. Re-run Section A (A2 through A5)
6. Clone repo, create .env with COMPETITION keys
7. Restore bot_state.json if you have a backup
8. Start the service
9. Notify team on WhatsApp
```

**Recovery time:** ~20 minutes if the procedure is practised.

### E3. Wrong API Keys Used

**Symptoms:** Orders being placed on the testing portfolio instead of competition portfolio.

```bash
# IMMEDIATELY stop the bot
sudo systemctl stop tradingbot.service

# Check which keys are loaded
head -3 .env

# If testing keys: swap to competition keys
cp .env.competition .env
head -3 .env  # verify

# Restart
sudo systemctl start tradingbot.service

# Notify organisers on WhatsApp if any trades were placed on wrong keys
```

### E4. Large Unexpected Drawdown

**Symptoms:** Telegram alert shows drawdown > 3%, or circuit breaker triggered.

```
1. DO NOT PANIC
2. Check if circuit breaker fired automatically (check logs)
3. If L1 fired: bot reduced positions by 50%. Monitor for recovery.
4. If L2 fired: bot sold everything and paused 24h. Consider:
   a. Wait for the 24h pause to expire (default)
   b. Manually override by restarting the bot (only if Abdalla approves)
5. Analyse: was this a market crash or a bot bug?
   - Market crash: circuit breaker working as designed. Wait.
   - Bot bug: stop, fix, redeploy (Section D).
6. Post update to WhatsApp with analysis.
```

### E5. API Rate Limit Exceeded

**Symptoms:** Repeated errors in logs mentioning "rate limit" or HTTP 429.

```bash
# Check how many API calls the bot is making
grep -c "GET\|POST" logs/system.log | tail -1

# Temporary fix: increase the order spacing
# Edit config/strategy_params.yaml:
#   execution.order_spacing_seconds: 120  (doubled from 65)

# Then redeploy (Section D)
```

---

## SECTION F: Daily Operations Checklist

Print this page. Check each item every morning.

```
DATE: ___________  CHECKED BY: ___________

[ ] 1. Telegram heartbeat received in the last hour
[ ] 2. No error alerts in Telegram
[ ] 3. system.log: no tracebacks in last 100 lines
       $ tail -100 /opt/trading-bot/logs/system.log | grep -i "error\|exception\|traceback"
[ ] 4. trades.jsonl: trades being executed
       $ tail -5 /opt/trading-bot/logs/trades.jsonl
[ ] 5. Memory OK (used < 3.5G including swap)
       $ free -h
[ ] 6. Disk OK (available > 3G)
       $ df -h /
[ ] 7. Portfolio value and metrics noted:
       PV: $________  Return: ______%  MaxDD: ______%
       Sharpe: ______  Sortino: ______  Calmar: ______
       Composite: ______
[ ] 8. Update posted to team WhatsApp
```

---

## SECTION G: Key Contacts and Resources

| Resource | Details |
|---|---|
| Roostoo WhatsApp support | [Join via QR code from intro session] |
| Roostoo API base URL | `https://mock-api.roostoo.com` |
| AWS region | ap-southeast-1 (Singapore) |
| EC2 instance type | T3.medium (2 vCPU, 4GB RAM) |
| GitHub repo | `https://github.com/<TEAM_ORG>/roostoo-quant-bot` |
| Telegram bot | @<BOT_NAME> |
| Abdalla (lead) | [phone number] |
| Wilson (infra) | [phone number] |
| Sami (data) | [phone number] |
| Oscar (signals) | [phone number] |

---

*End of Deployment Runbook*

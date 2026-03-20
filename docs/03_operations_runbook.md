# Operations Runbook
## Current Operational Source of Truth

This document is the operational anchor for the repository.

- The files in `Technicals/` describe the intended end product.
- This runbook describes the current implementation contract and the rules new code must follow while we build toward that target.
- `docs/TEAM_UPDATE.md` tracks what is actually implemented right now against the target architecture.

## Principles

Every new code path should align with the end-product documents while remaining runnable today.

- Follow `Technicals/04_Best_Practices_Manual.md` for secrets, YAML config, logging, retries, and tests.
- Treat `Technicals/05_Architecture_Overview.md` as the target system design.
- Treat `Technicals/07_Deployment_Runbook.md` as the target deployment/go-live procedure.
- If the current code cannot yet satisfy an end-product step, document the gap here and in `docs/TEAM_UPDATE.md`.

## Current Runnable Slice

What works today:

- environment-backed secret loading with `.env` permission enforcement
- YAML-backed runtime configuration and logging bootstrap
- Roostoo `serverTime`, `exchangeInfo`, `ticker`, and signed endpoint wrappers
- local sqlite persistence of ticker-derived 1-minute candles
- Binance public kline ingestion with sqlite caching for repeated backtests
- staged CLI backtests for momentum, mean-reversion, and regime detection
- a single-process polling, reconciliation, and heartbeat scheduler in `bot.main`
- startup reconciliation against signed balance and pending-order endpoints
- Telegram startup and heartbeat delivery when `TELEGRAM_BOT_TOKEN` and `TELEGRAM_CHAT_ID` are configured
- deploy scripts and systemd unit for `/opt/trading-bot`
- all 4 signal modules (momentum, mean-reversion, pairs rotation, sector rotation)
- ensemble combiner with regime-dependent weight blending and sentiment multiplier
- sentiment fetcher (Fear & Greed Index from Alternative.me with deployment multiplier)
- portfolio optimizer with inverse-vol weighting, Kelly cap, sector limits, regime cash floors
- order executor with weight-to-quantity conversion, limit order pricing, precision enforcement, sell-first ordering
- metrics tracker with running Sharpe, Sortino, and Calmar ratio computation
- full strategy cycle wired in `_run_strategy_cycle` for disabled, paper, and live modes
- risk manager and circuit breaker integrated into the strategy cycle

What is still on the path to the end product:

- backtest notebook with real historical data (`notebooks/backtest_results.ipynb`)
- live-environment endpoint integration testing against competition credentials

## Required Verification

Treat these commands as the hard local gate before EC2, systemd, or Telegram setup:

```bash
python3.11 -m venv .venv
source .venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt
python -c "from bot.main import TradingBot; print('IMPORT_OK')"
python -m bot.main --status
pytest tests -q
```

After `.env` contains real testing credentials with `chmod 600`, and before Telegram is configured:

```bash
python -m bot.main --startup-check
python -m bot.main --poll-once
```

`--startup-check` exercises the production bootstrap path, including clock sync, universe load, and signed-state reconciliation. `--poll-once` bootstraps and persists a single ticker poll without sending Telegram alerts, so it is the preferred smoke test before `systemd`.

On an EC2 host that is already running `tradingbot.service`, stop the service before running `python -m bot.main --poll-once` manually to avoid concurrent sqlite and state-file writes.

All pipeline stages (signal generation, ensemble weighting, risk gating, rebalance planning, and order execution) are now wired end to end. Set `runtime.strategy_mode` to `paper` for dry-run logging, or `live` for real order placement. Keep it at `disabled` during development to suppress the strategy cycle.

For pre-competition calibration and the first-three-module validation pass:

```bash
python -m bot.main --backtest-core-modules --symbols BTCUSD,ETHUSD,SOLUSD --history-days 180 --train-days 90 --validation-days 90
```

If local polling/bootstrap has already written `data/bot_state.json`, `--symbols` is optional and the backtest will reuse the discovered universe.

## Deployment Assumptions

- AWS region: `ap-southeast-2` (Sydney)
- app directory: `/opt/trading-bot`
- service file: `deploy/tradingbot.service`
- setup script: `deploy/setup.sh` (uses **Ubuntu/apt**; see below for **Amazon Linux 2023**)
- deployment script: `deploy/deploy.sh`

## EC2: Amazon Linux 2023 + Session Manager (Hackathon template)

Use this path when the instance comes from the Roostoo **Hackathon** launch template (Amazon Linux 2023, `t3.medium`, **Session Manager** only). The shell may show `sh-5.2$`; optional: run `bash` for a nicer prompt.

`deploy/setup.sh` assumes **apt** (Ubuntu). On Amazon Linux use **dnf** and the steps below instead.

### Starting point (canonical flow)

Use this order every time you set up or refresh the server:

1. **Region** `ap-southeast-2` → launch instance from the hackathon template → **Session Manager** to connect ([Roostoo AWS guide](https://roostoo.notion.site/Hackathon-Guide-How-to-Sign-In-AWS-and-Launch-Your-Bot-309ba22fed798071b4dde6d1e8666816)).
2. **System packages + swap** — Section **1** below (`dnf`, swap, NTP).
3. **Clone this repo** (public team fork):

   `git clone https://github.com/Abdallak69/Team-15-Derivative-Disaster.git /opt/trading-bot`  
   then `cd /opt/trading-bot`, `python3.11 -m venv venv`, `pip install -r requirements.txt`.

4. **Secrets** — `cp .env.example .env` **once**, `chmod 600 .env`, edit keys in `nano`. **Never run `cp .env.example .env` again** after real keys are saved (it overwrites `.env`).
5. **Smoke test** — `source venv/bin/activate`, then `--startup-check` and `--poll-once`.
6. **Live trading** — `config/strategy_params.yaml` sets `runtime.strategy_mode` (`live` = real API orders, `paper` = dry-run only). Adjust before long runs if you need paper mode. Restart the bot after any config change.
7. **Updates** — `git pull` in `/opt/trading-bot`, then **stop** the old process (`kill` / `systemctl stop`) and start again (tmux or systemd).
8. **Logs** — Operational logs go to **`logs/system.log`** and trades to **`logs/trades.jsonl`**; the process may print little to the console. Use `tail -f logs/system.log` in a second Session Manager tab to confirm activity.

### EC2 sections (detailed)

### 1. System prep (swap + time sync)

```bash
sudo dnf update -y
sudo dnf install -y git python3.11 python3.11-pip tmux sqlite wget

# 4G swap (recommended on 4 GiB RAM)
if [[ ! -f /swapfile ]]; then
  sudo fallocate -l 4G /swapfile
  sudo chmod 600 /swapfile
  sudo mkswap /swapfile
  sudo swapon /swapfile
  echo '/swapfile none swap sw 0 0' | sudo tee -a /etc/fstab
fi
sudo sysctl vm.swappiness=10
grep -q '^vm.swappiness=10' /etc/sysctl.conf || echo 'vm.swappiness=10' | sudo tee -a /etc/sysctl.conf

sudo timedatectl set-ntp true
timedatectl status   # expect NTP / synchronized
```

If `python3.11` is not in your repos, install whatever `python3` is 3.10+ (`python3 --version`) and use that for the venv below.

### 2. Code and virtualenv

```bash
sudo mkdir -p /opt/trading-bot
sudo chown "$(id -u):$(id -g)" /opt/trading-bot
cd /opt/trading-bot

# Public repo (HTTPS + token only if you use a private fork)
git clone https://github.com/Abdallak69/Team-15-Derivative-Disaster.git .

python3.11 -m venv venv
source venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt
mkdir -p data logs
```

### 3. Secrets

```bash
cp .env.example .env
chmod 600 .env
nano .env   # ROOSTOO_* testing keys first; optional Telegram after smoke tests
```

### 4. Smoke tests (same contract as local)

```bash
cd /opt/trading-bot && source venv/bin/activate
python -c "from bot.main import TradingBot; print('IMPORT_OK')"
python -m bot.main --status
pytest tests -q
python -m bot.main --startup-check
python -m bot.main --poll-once
```

### 5. Run continuously

**Option A — tmux** (matches the [Roostoo AWS guide](https://roostoo.notion.site/Hackathon-Guide-How-to-Sign-In-AWS-and-Launch-Your-Bot-309ba22fed798071b4dde6d1e8666816)):

```bash
tmux new -s bot
cd /opt/trading-bot && source venv/bin/activate && python -m bot.main
# Detach: Ctrl+B, then D. Reattach: tmux attach -t bot
```

**Option B — systemd** (survives disconnects; user is usually `ssm-user` on Session Manager):

```bash
sudo tee /etc/systemd/system/tradingbot.service >/dev/null <<EOF
[Unit]
Description=Roostoo Quant Trading Bot
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=$(whoami)
WorkingDirectory=/opt/trading-bot
EnvironmentFile=/opt/trading-bot/.env
ExecStart=/opt/trading-bot/venv/bin/python -m bot.main
Restart=on-failure
RestartSec=30

[Install]
WantedBy=multi-user.target
EOF

sudo systemctl daemon-reload
sudo systemctl enable --now tradingbot.service
sudo systemctl status tradingbot.service
```

Stop the bot: `sudo systemctl stop tradingbot.service` (or exit/kill the tmux session).

## Rules For New Code

When adding or modifying code:

- keep tuneable parameters in `config/strategy_params.yaml`
- keep secrets in `.env` only
- route operational logs through `config/logging_config.yaml`
- use UTC timestamps in persisted state and logs
- add tests for any new API, risk, signal, or execution behavior
- update this runbook whenever operational behavior, verification commands, or deployment steps change

## Relationship To The Target Docs

The correct reading order is:

1. `Technicals/02_Strategy_Research_and_Selection.md`
2. `Technicals/04_Best_Practices_Manual.md`
3. `Technicals/05_Architecture_Overview.md`
4. `Technicals/06_Strategy_Mathematics_Deep_Dive.md`
5. `Technicals/07_Deployment_Runbook.md`
6. `docs/03_operations_runbook.md`
7. `docs/TEAM_UPDATE.md`

That order preserves the intended end product while keeping daily coding and deployment decisions grounded in the code that actually exists today.

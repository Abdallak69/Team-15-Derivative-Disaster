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
- a single-process polling, reconciliation, and heartbeat scheduler in `bot.main`
- startup reconciliation against signed balance and pending-order endpoints
- Telegram startup and heartbeat delivery when `TELEGRAM_BOT_TOKEN` and `TELEGRAM_CHAT_ID` are configured
- deploy scripts and systemd unit for `/opt/trading-bot`

What is still on the path to the end product:

- full strategy orchestration in the runtime loop
- live order placement and cancel/query flows wired into execution modules
- historical Binance ingestion and sentiment refresh jobs

## Required Verification

Use these commands as the baseline checks for this repository:

```bash
python -c "from bot.main import TradingBot; print('IMPORT_OK')"
pytest tests -q
python -m bot.main --status
```

After `.env` contains real testing or competition credentials with `chmod 600`:

```bash
python -m bot.main --startup-check
```

`--startup-check` now exercises the production bootstrap path, including clock sync, universe load, and signed-state reconciliation. If Telegram secrets are configured, it also sends the startup alert.

## Deployment Assumptions

- AWS region: `ap-southeast-2` (Sydney)
- app directory: `/opt/trading-bot`
- service file: `deploy/tradingbot.service`
- setup script: `deploy/setup.sh`
- deployment script: `deploy/deploy.sh`

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

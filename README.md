# Roostoo Quant Bot

Repository for the SG vs HK University Web3 Quant Trading Hackathon trading bot.

The files in `Technicals/` describe the target end product.
The current operational source of truth lives at `docs/03_operations_runbook.md`.
The current implementation status lives at `docs/TEAM_UPDATE.md`.

## Current implementation

The current working slice is the market data and operations runtime:

- Roostoo request signing and clock-sync helpers
- `/v3/exchangeInfo` universe discovery
- `/v3/ticker` polling
- signed balance and pending-order reconciliation
- local sqlite persistence of ticker-derived 1-minute candles
- Binance historical kline fetching with local sqlite caching
- staged backtests for momentum, mean reversion, and regime detection
- a single-process scheduler in `bot.main` for polling, reconciliation, heartbeats, and clock sync

The initial import milestone is still satisfied:

```bash
python -c "from bot.main import TradingBot"
```

## Repository layout

- `bot/` core application packages and the `TradingBot` entrypoint
- `config/` YAML configuration templates
- `deploy/` EC2 bootstrap and deployment scripts
- `data/` runtime state and sqlite databases
- `tests/` unit tests for the scaffold and data-pipeline slice
- `notebooks/` analysis and backtesting notebooks

## Quick start

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt
python -c "from bot.main import TradingBot; print('IMPORT_OK')"
python -m bot.main --status
pytest tests -q
```

After I replace the Roostoo placeholders in `.env` with real testing keys and leave Telegram unset or placeholder, I run:

```bash
cp .env.example .env
chmod 600 .env
python -m bot.main --startup-check
python -m bot.main --poll-once
```

Only after those commands pass do I move on to `deploy/setup.sh`, `deploy/deploy.sh`, or the EC2/systemd/Telegram steps in `Technicals/07_Deployment_Runbook.md`.

For the first-three-module validation pass:

```bash
python -m bot.main --backtest-core-modules --symbols BTCUSD,ETHUSD,SOLUSD --history-days 30 --train-days 15 --validation-days 15
```

## Notes

- `Technicals/` documents the intended end-state bot, not just the currently implemented slice.
- `docs/03_operations_runbook.md` is the operational contract new code and deploy procedures should follow.
- `python -m bot.main --startup-check` exercises the production bootstrap path once, including clock sync, universe loading, and signed-state reconciliation, then exits.
- `python -m bot.main --poll-once` bootstraps and persists one ticker poll without sending Telegram alerts. Use it as the smoke test before `systemd`.
- `python -m bot.main --backtest-core-modules` fetches/caches Binance klines and evaluates only the first three modules from the strategy document. If local polling has already produced `data/bot_state.json`, omit `--symbols` to reuse that universe.
- `python -m bot.main` starts the long-running polling loop used by the systemd service.
- `runtime.strategy_mode` defaults to `disabled`. `paper` records strategy cycles in dry-run mode, and `live` sends real orders through the Roostoo API — ensure the full pipeline is verified in `paper` mode first.
- All signal, risk, and execution modules are implemented. See `docs/TEAM_UPDATE.md` for current status.

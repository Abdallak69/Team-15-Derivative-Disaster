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
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
cat docs/03_operations_runbook.md
cat docs/TEAM_UPDATE.md
python -m bot.main --status
pytest tests -q
```

After I replace the placeholder values in `.env` with real testing keys, I run:

```bash
python -m bot.main --startup-check
```

## Notes

- `Technicals/` documents the intended end-state bot, not just the currently implemented slice.
- `docs/03_operations_runbook.md` is the operational contract new code and deploy procedures should follow.
- `python -m bot.main --startup-check` exercises the real bootstrap path once, including clock sync, universe loading, and signed-state reconciliation, then exits.
- `python -m bot.main` starts the long-running polling loop used by the systemd service.
- Trading decision and execution modules are still lightweight placeholders and should not be treated as production-ready yet.

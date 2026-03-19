# Roostoo Quant Bot

Repository for the SG vs HK University Web3 Quant Trading Hackathon trading bot.

The single team update document lives at `docs/TEAM_UPDATE.md`.

## Current implementation

The first working vertical slice is the market data pipeline:

- Roostoo request signing and clock-sync helpers
- `/v3/exchangeInfo` universe discovery
- `/v3/ticker` polling
- local sqlite persistence of ticker-derived 1-minute candles
- a single-process scheduler in `bot.main`

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
cat docs/TEAM_UPDATE.md
python -m bot.main --status
python -m unittest discover
```

After I replace the placeholder values in `.env` with real testing keys, I run:

```bash
python -m bot.main --startup-check
```

## Notes

- `python -m bot.main --startup-check` exercises the real bootstrap path once, including clock sync and universe loading, then exits.
- `python -m bot.main` starts the long-running polling loop used by the systemd service.
- Trading logic modules outside the data pipeline are still lightweight placeholders and should not be treated as production-ready yet.

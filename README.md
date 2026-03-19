# Roostoo Quant Bot

Baseline repository scaffold for the SG vs HK University Web3 Quant Trading Hackathon bot.

## Current milestone

The first repo milestone is in place:

```bash
python -c "from bot.main import TradingBot"
```

## Repository layout

- `bot/` core application packages and the `TradingBot` entrypoint
- `config/` YAML configuration templates
- `deploy/` EC2 bootstrap and deployment scripts
- `data/` runtime state and sqlite databases
- `tests/` baseline unit tests for the scaffold
- `notebooks/` analysis and backtesting notebooks

## Quick start

```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
python -c "from bot.main import TradingBot; print(TradingBot().status())"
python -m unittest discover
```

## Status

This commit creates the documented project structure and import-safe base modules. Most domain modules are intentionally lightweight placeholders so the team can implement them incrementally without blocking the initial bootstrap milestone.


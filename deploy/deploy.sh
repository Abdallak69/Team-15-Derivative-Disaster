#!/usr/bin/env bash
set -euo pipefail

APP_DIR="${APP_DIR:-/opt/trading-bot}"

cd "${APP_DIR}"
git pull --ff-only
source venv/bin/activate
pip install -r requirements.txt
python -c "from bot.main import TradingBot; print(TradingBot().status())"
sudo systemctl restart tradingbot
sudo systemctl --no-pager --full status tradingbot


#!/usr/bin/env bash
set -euo pipefail

APP_DIR="${APP_DIR:-/opt/trading-bot}"

cd "${APP_DIR}"
git pull --ff-only
source venv/bin/activate
pip install -r requirements.txt
pytest tests -q
python -m bot.main --startup-check
sudo systemctl restart tradingbot
sudo systemctl --no-pager --full status tradingbot

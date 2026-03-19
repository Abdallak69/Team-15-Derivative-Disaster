#!/usr/bin/env bash
set -euo pipefail

APP_DIR="${APP_DIR:-/opt/trading-bot}"
PYTHON_BIN="${PYTHON_BIN:-python3.11}"

sudo apt-get update
sudo apt-get install -y python3.11 python3.11-venv python3-pip git sqlite3 curl

sudo mkdir -p "${APP_DIR}"
sudo chown "${USER}:${USER}" "${APP_DIR}"

cd "${APP_DIR}"
"${PYTHON_BIN}" -m venv venv
source venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt

mkdir -p data logs
python -c "from bot.main import TradingBot; print(TradingBot().status())"


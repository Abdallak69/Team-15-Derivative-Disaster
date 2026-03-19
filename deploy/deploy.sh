#!/usr/bin/env bash
set -euo pipefail

APP_DIR="${APP_DIR:-/opt/trading-bot}"
SERVICE_NAME="tradingbot.service"
service_needs_restart=0

ensure_service_running() {
  if [[ "${service_needs_restart}" -eq 1 ]]; then
    sudo systemctl start "${SERVICE_NAME}" >/dev/null 2>&1 || true
  fi
}

trap ensure_service_running EXIT

cd "${APP_DIR}"
git pull --ff-only
source venv/bin/activate
pip install -r requirements.txt
pytest tests -q
python -m bot.main --status

if sudo systemctl is-active --quiet "${SERVICE_NAME}"; then
  sudo systemctl stop "${SERVICE_NAME}"
  service_needs_restart=1
fi

python -m bot.main --poll-once
sudo systemctl start "${SERVICE_NAME}"
service_needs_restart=0
trap - EXIT
sudo systemctl --no-pager --full status tradingbot

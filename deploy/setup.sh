#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
APP_DIR="${APP_DIR:-/opt/trading-bot}"
PYTHON_BIN="${PYTHON_BIN:-python3.11}"
APP_USER="${APP_USER:-${USER}}"
SERVICE_PATH="/etc/systemd/system/tradingbot.service"

if [[ ! -f "${REPO_ROOT}/requirements.txt" || ! -d "${REPO_ROOT}/bot" ]]; then
  echo "This script must be run from the repository checkout." >&2
  exit 1
fi

sudo apt-get update
sudo apt-get install -y python3.11 python3.11-venv python3-pip git sqlite3 curl rsync

sudo mkdir -p "${APP_DIR}"
sudo chown "${APP_USER}:${APP_USER}" "${APP_DIR}"

if [[ "${REPO_ROOT}" != "${APP_DIR}" ]]; then
  rsync -a \
    --exclude ".git/" \
    --exclude ".env" \
    --exclude ".env.*" \
    --exclude "venv/" \
    --exclude "logs/" \
    --exclude "data/*.db" \
    --exclude "data/*.db-*" \
    --exclude "data/*.sqlite" \
    --exclude "data/*.sqlite-*" \
    --exclude "data/*.sqlite3" \
    --exclude "data/*.sqlite3-*" \
    --exclude "data/*.json" \
    --exclude "__pycache__/" \
    --exclude ".pytest_cache/" \
    "${REPO_ROOT}/" "${APP_DIR}/"
fi

sudo chown -R "${APP_USER}:${APP_USER}" "${APP_DIR}"

sed \
  -e "s|__APP_USER__|${APP_USER}|g" \
  -e "s|__APP_DIR__|${APP_DIR}|g" \
  "${REPO_ROOT}/deploy/tradingbot.service" | sudo tee "${SERVICE_PATH}" >/dev/null
sudo systemctl daemon-reload
sudo systemctl enable tradingbot.service >/dev/null

if [[ ! -f /swapfile ]]; then
  sudo fallocate -l 4G /swapfile
  sudo chmod 600 /swapfile
  sudo mkswap /swapfile
fi

if ! swapon --show=NAME --noheadings | grep -q '^/swapfile$'; then
  sudo swapon /swapfile
fi

if ! grep -q '^/swapfile none swap sw 0 0$' /etc/fstab; then
  echo '/swapfile none swap sw 0 0' | sudo tee -a /etc/fstab >/dev/null
fi

sudo sysctl vm.swappiness=10 >/dev/null
if ! grep -q '^vm.swappiness=10$' /etc/sysctl.conf; then
  echo 'vm.swappiness=10' | sudo tee -a /etc/sysctl.conf >/dev/null
fi

sudo timedatectl set-ntp true

cd "${APP_DIR}"
"${PYTHON_BIN}" -m venv venv
source venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt

mkdir -p data logs
pytest tests -q
python -m bot.main --status

if [[ -f .env ]]; then
  python -m bot.main --startup-check
else
  echo "Skipped startup check because .env does not exist yet."
  echo "Create .env with real testing keys, then rerun: python -m bot.main --startup-check"
fi

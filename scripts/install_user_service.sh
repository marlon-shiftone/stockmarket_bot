#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
POETRY_BIN="$(command -v poetry || true)"
SERVICE_NAME="stockmarket-bot.service"
SERVICE_DIR="${XDG_CONFIG_HOME:-$HOME/.config}/systemd/user"
SERVICE_PATH="$SERVICE_DIR/$SERVICE_NAME"

if [[ -z "$POETRY_BIN" ]]; then
  echo "Poetry not found in PATH."
  exit 1
fi

mkdir -p "$SERVICE_DIR"

cat >"$SERVICE_PATH" <<EOF
[Unit]
Description=StockMarket Bot API
After=network.target

[Service]
Type=simple
Environment=PYTHONUNBUFFERED=1
ExecStart=/bin/bash -lc "cd '$ROOT_DIR' && exec '$POETRY_BIN' run uvicorn api.app:app --app-dir src --host 127.0.0.1 --port 8000"
Restart=always
RestartSec=5

[Install]
WantedBy=default.target
EOF

systemctl --user daemon-reload
systemctl --user enable --now "$SERVICE_NAME"

echo "Service installed and started: $SERVICE_NAME"
echo "Status: systemctl --user status $SERVICE_NAME"
echo "Logs: journalctl --user -u $SERVICE_NAME -f"

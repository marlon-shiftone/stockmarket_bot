#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

if [[ ! -f .env ]]; then
  echo "Missing .env file. Copy .env.example to .env and fill your Alpaca keys."
  exit 1
fi

set -a
# shellcheck disable=SC1091
source .env
set +a

poetry run python scripts/validate_alpaca_backtest.py

#!/usr/bin/env bash
set -euo pipefail

poetry run uvicorn api.app:app --app-dir src --reload

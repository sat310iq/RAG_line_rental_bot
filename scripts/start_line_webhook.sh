#!/usr/bin/env bash
set -euo pipefail

HOST="${HOST:-0.0.0.0}"
PORT="${PORT:-8000}"

python3 -m uvicorn src.interfaces.line.main:app --host "$HOST" --port "$PORT"

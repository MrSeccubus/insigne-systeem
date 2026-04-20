#!/bin/bash
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

if [ ! -f venv/bin/uvicorn ]; then
    echo "Setting up virtual environment..."
    python3 -m venv venv
    venv/bin/pip install -r requirements.txt
fi

venv/bin/pip install -q -e lib/

if [ ! -f config.yml ]; then
    echo "ERROR: config.yml not found. See CLAUDE.md for setup instructions." >&2
    exit 1
fi

HOST="${INSIGNE_HOST:-127.0.0.1}"
PORT="${INSIGNE_PORT:-8000}"

exec venv/bin/uvicorn main:app \
    --app-dir api \
    --host "$HOST" \
    --port "$PORT" \
    --workers 1

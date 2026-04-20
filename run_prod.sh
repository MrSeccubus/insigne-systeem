#!/bin/bash
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

if [ ! -f venv/bin/uvicorn ]; then
    echo "Setting up virtual environment..."
    python3 -m venv venv
    venv/bin/pip install -r requirements.txt
fi

rm -rf lib/*.egg-info
venv/bin/pip uninstall -y insigne 2>/dev/null || true
venv/bin/pip install -q -e lib/

if [ ! -f config.yml ]; then
    echo "ERROR: config.yml not found. See CLAUDE.md for setup instructions." >&2
    exit 1
fi

# Read server settings from config.yml, allow env var overrides
HOST="${INSIGNE_HOST:-$(venv/bin/python -c "from insigne.config import config; print(config.server_host)")}"
PORT="${INSIGNE_PORT:-$(venv/bin/python -c "from insigne.config import config; print(config.server_port)")}"
KEEPALIVE="${INSIGNE_KEEPALIVE:-$(venv/bin/python -c "from insigne.config import config; print(config.server_keepalive)")}"

exec venv/bin/uvicorn main:app \
    --app-dir api \
    --host "$HOST" \
    --port "$PORT" \
    --workers 1 \
    --timeout-keep-alive "$KEEPALIVE"

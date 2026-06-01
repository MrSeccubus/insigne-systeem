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

echo "Running database migrations..."
venv/bin/python api/migrate.py

# Read server settings from config.yml, allow env var overrides
HOST="${INSIGNE_HOST:-$(venv/bin/python -c "from insigne.config import config; print(config.server_host)")}"
PORT="${INSIGNE_PORT:-$(venv/bin/python -c "from insigne.config import config; print(config.server_port)")}"
KEEPALIVE="${INSIGNE_KEEPALIVE:-$(venv/bin/python -c "from insigne.config import config; print(config.server_keepalive)")}"
FORWARDED_ALLOW_IPS="${INSIGNE_FORWARDED_ALLOW_IPS:-$(venv/bin/python -c "from insigne.config import config; print(config.server_forwarded_allow_ips)")}"

# When server.forwarded_allow_ips is set, ask uvicorn to parse
# X-Forwarded-For / X-Forwarded-Proto from the listed proxy IPs so the
# app sees the real client IP (used by the fail2ban login log).
# Empty value = no parsing, app sees the proxy's IP — safe default when
# not running behind a reverse proxy.
PROXY_FLAGS=()
if [ -n "$FORWARDED_ALLOW_IPS" ]; then
    PROXY_FLAGS=(--proxy-headers --forwarded-allow-ips "$FORWARDED_ALLOW_IPS")
fi

exec venv/bin/uvicorn main:app \
    --app-dir api \
    --host "$HOST" \
    --port "$PORT" \
    --workers 1 \
    --timeout-keep-alive "$KEEPALIVE" \
    "${PROXY_FLAGS[@]}"

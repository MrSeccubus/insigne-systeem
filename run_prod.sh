#!/bin/bash
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

if [ ! -f venv/bin/uvicorn ]; then
    echo "Setting up virtual environment..."
    python3 -m venv venv
fi

rm -rf lib/*.egg-info
venv/bin/pip uninstall -y insigne 2>/dev/null || true

# Install requirements only when requirements.txt actually changed, so an
# upgrade still pulls new deps but an unchanged restart skips the (network-
# hitting, multi-second) resolve. We stamp the installed file's hash in the
# venv (gitignored) and re-install only on a mismatch.
#
# Guarded so a transient PyPI/network failure can't abort startup: `set -e`
# ignores failures inside an `if` condition, and the stamp is written only on
# success, so a failed install simply retries next start. The service has
# Restart=on-failure, so an unguarded failure here would crash-loop.
_req_sha() { if command -v sha256sum >/dev/null 2>&1; then sha256sum "$1"; else shasum -a 256 "$1"; fi | awk '{print $1}'; }
REQ_STAMP="venv/.requirements.sha256"
REQ_HASH="$(_req_sha requirements.txt)"
if [ "$(cat "$REQ_STAMP" 2>/dev/null)" != "$REQ_HASH" ]; then
    if venv/bin/pip install -r requirements.txt; then
        echo "$REQ_HASH" > "$REQ_STAMP"
    else
        echo "pip install -r requirements.txt failed (network down?); starting with the existing venv" >&2
    fi
fi
# Always ensure the editable package itself is installed (no network needed),
# even when the requirements install above was skipped or failed.
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


# IMPORTANT: keep --workers 1. The rate limiter (api/ratelimit.py) and the
# ALTCHA single-use replay store (api/captcha.py) both hold state in-process
# memory. With >1 worker each limit is multiplied by the worker count and a
# captcha payload can be replayed once per worker. Raising the worker count
# requires moving both to a shared backend (e.g. Redis) first.
exec venv/bin/uvicorn main:app \
    --app-dir api \
    --host "$HOST" \
    --port "$PORT" \
    --workers 1 \
    --timeout-keep-alive "$KEEPALIVE" \
    "${PROXY_FLAGS[@]}"

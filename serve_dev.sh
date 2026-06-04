#!/bin/bash
set -e

# Optional flag: --external / --lan / -e — bind to 0.0.0.0 so phones on
# the same Wi-Fi can hit the dev server (handy for PWA install testing).
# Default is loopback-only.
HOST="127.0.0.1"
case "${1:-}" in
    --external|--lan|-e)
        HOST="0.0.0.0"
        ;;
    "")
        ;;
    *)
        echo "Usage: $0 [--external|--lan|-e]" >&2
        exit 2
        ;;
esac

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

if [ "$HOST" = "0.0.0.0" ]; then
    # macOS: ipconfig; Linux fallback: hostname -I.
    LAN_IP="$(ipconfig getifaddr en0 2>/dev/null \
              || ipconfig getifaddr en1 2>/dev/null \
              || hostname -I 2>/dev/null | awk '{print $1}')"
    echo "─────────────────────────────────────────────────────────────"
    echo "  Binding to 0.0.0.0:8000"
    if [ -n "$LAN_IP" ]; then
        echo "  On your phone (same Wi-Fi): http://${LAN_IP}:8000"
    fi
    echo
    echo "  Note: state-changing POSTs (login, sign-off, etc.) will 403"
    echo "  unless config.yml's base_url matches the URL you loaded from"
    echo "  — the CSRF middleware compares against base_url. For pure"
    echo "  GET / PWA-install testing it's fine as-is."
    echo "─────────────────────────────────────────────────────────────"
fi

venv/bin/python api/migrate.py
INSIGNE_DEV=1 venv/bin/uvicorn main:app --app-dir api --reload --host "$HOST"

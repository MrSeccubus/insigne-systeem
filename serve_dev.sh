#!/bin/bash
set -e

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

venv/bin/uvicorn main:app --app-dir api --reload

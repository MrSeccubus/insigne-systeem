#!/bin/bash
set -e

if [ ! -f venv/bin/uvicorn ]; then
    echo "Setting up virtual environment..."
    python3 -m venv venv
    venv/bin/pip install -r requirements.txt
fi

if [ -f .env ]; then
    set -a
    source .env
    set +a
fi

venv/bin/uvicorn main:app --app-dir api --reload

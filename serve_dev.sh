#!/bin/bash
set -e
venv/bin/uvicorn main:app --app-dir api --reload

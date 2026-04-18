# Insigne Systeem

## Python environment
- Always use `venv/bin/python` and `venv/bin/pip` — never system Python.
- Install dependencies: `venv/bin/pip install -r requirements.txt`

## Running the app
From the project root:
```
venv/bin/uvicorn main:app --app-dir api --reload
```
Then open http://localhost:8000.

## Structure
- `api/` — FastAPI application (`api/main.py` is the entry point)
- `frontend/templates/` — Jinja2 HTML templates
- `frontend/static/` — CSS and static assets
- `venv/` — Python 3.13 virtual environment (not committed)

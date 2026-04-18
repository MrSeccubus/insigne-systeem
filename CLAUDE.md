# Insigne Systeem

## Python environment
- Always use `venv/bin/python` and `venv/bin/pip` — never system Python.
- Install dependencies: `venv/bin/pip install -r requirements.txt`

## Environment variables
Create a `.env` file in the project root (never commit it):
```
JWT_SECRET_KEY=<any long random string>
```
`serve_dev.sh` loads this automatically.

## Running the app
From the project root:
```
./serve_dev.sh
```
Or manually:
```
venv/bin/uvicorn main:app --app-dir api --reload
```
Then open http://localhost:8000.

## Database
SQLite database is created automatically at `api/data/insigne.db` on first run.
Tables are created via `Base.metadata.create_all()` on startup.

## Structure
- `api/` — FastAPI application (`api/main.py` is the entry point)
- `frontend/templates/` — Jinja2 HTML templates
- `frontend/static/` — CSS and static assets
- `venv/` — Python 3.13 virtual environment (not committed)

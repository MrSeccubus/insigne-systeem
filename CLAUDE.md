# Insigne Systeem

## Python environment
- Always use `venv/bin/python` and `venv/bin/pip` — never system Python.
- Install dependencies: `venv/bin/pip install -r requirements.txt`

## Configuration
Create a `config.yml` file in the project root (never commit it — it is gitignored):
```yaml
database:
  url: sqlite:///api/data/insigne.db

jwt:
  secret_key: "<any long random string>"
  algorithm: HS256
  expire_days: 30
```
The app reads `config.yml` from the working directory on startup.
Override the path with the `INSIGNE_CONFIG` environment variable.

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

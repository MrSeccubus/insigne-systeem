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

server:
  host: 127.0.0.1   # bind address for run_prod.sh (default: 127.0.0.1)
  port: 8000        # bind port for run_prod.sh (default: 8000)
  keepalive: 2      # uvicorn --timeout-keep-alive in seconds (default: 2; set low behind a proxy)

base_url: "http://localhost:8000"  # public URL used in emails and links

# System administrators (by email address — config is the source of truth, not the DB)
admins:
  - admin@example.com

# Whether any authenticated user may create a group (false = only admins)
allow_any_user_to_create_groups: true
```
The app reads `config.yml` from the working directory on startup.
Override the path with the `INSIGNE_CONFIG` environment variable.

## Running the app

**Development** (auto-reload):
```
./serve_dev.sh
```
Or manually:
```
venv/bin/uvicorn main:app --app-dir api --reload
```

**Production** (single run, no reload):
```
./run_prod.sh
```
Binds to `127.0.0.1:8000` by default. Override with env vars:
```
INSIGNE_HOST=0.0.0.0 INSIGNE_PORT=9000 ./run_prod.sh
```

Then open http://localhost:8000.

## Running as a systemd user service

Install once (requires `config.yml` to exist first):
```
./systemd/install.sh
```
This writes `~/.config/systemd/user/insigne.service`, enables lingering so the
service starts at boot even without a login session, then enables and starts it.

Use the `./insigne-ctl` control script afterwards:
```
./insigne-ctl start
./insigne-ctl stop
./insigne-ctl restart
./insigne-ctl status
./insigne-ctl logs -f        # live log tail
./insigne-ctl logs -n 100    # last 100 lines
```

To remove the service:
```
./systemd/uninstall.sh
```

## Database
SQLite database is created automatically at `api/data/insigne.db` on first run.
Schema is managed by Alembic — `./serve_dev.sh` and `./run_prod.sh` run `alembic upgrade head` automatically.

## Structure
- `api/` — FastAPI application (`api/main.py` is the entry point)
- `lib/insigne/` — installable Python library containing all business logic
- `frontend/templates/` — Jinja2 HTML templates
- `frontend/static/` — CSS and static assets
- `tests/` — pytest unit tests (library) and API tests (via TestClient)
- `venv/` — Python 3.13 virtual environment (not committed)

## API specification

The full API spec lives at `api/spec.md`. **Keep it up to date** whenever you add, change, or remove endpoints — both the JSON API (`/api/…`) and the HTML layer.

## Releases and the `releases` branch

**Never push to the `releases` branch unless explicitly instructed by the user.**
The `releases` branch always points to the latest released version and is only
advanced when the user says to make a new release.

When a new release is made:
1. Tag the release commit (`git tag -a vX.Y.Z ...`)
2. Fast-forward `releases` to that tag commit
3. Create the GitHub release
4. Update `CHANGELOG.md`

## Keeping the JSON API in sync with the library

Every public function added to `lib/insigne/` must have a corresponding JSON API
endpoint in `api/routers/` and at least one API-layer test in `tests/test_api_*.py`.
The unit tests verify correctness of what exists but do not detect missing endpoints,
so this is enforced by convention in code review.

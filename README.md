# Insigne Systeem

A web application for scouts to track their progress through the [Scouting Nederland](https://www.scouting.nl) badge system.

## Features

- Browse the badge catalogue (gewone and buitengewone insignes)
- Log progress on individual badge steps across three difficulty levels
- Request sign-off from mentors by email — mentors are invited to register if they don't have an account yet
- Mentor dashboard for reviewing and confirming or rejecting sign-off requests
- HTMX-powered frontend served by the same FastAPI application

## Tech stack

- **Backend** — [FastAPI](https://fastapi.tiangolo.com) + SQLAlchemy 2.0 (SQLite)
- **Frontend** — [HTMX](https://htmx.org) + [Alpine.js](https://alpinejs.dev), Jinja2 templates
- **Badge data** — YAML files in `api/data/`
- **Library** — `lib/insigne/` — installable Python package containing all business logic

## Getting started

```bash
python3 -m venv venv
venv/bin/pip install -r requirements.txt
venv/bin/pip install -e lib/
```

Create a `config.yml` in the project root (never commit it):

```yaml
database:
  url: sqlite:///api/data/insigne.db

jwt:
  secret_key: "<any long random string>"

base_url: "http://localhost:8000"
```

Run the development server from the **project root**:

```bash
./serve_dev.sh
```

Or manually:

```bash
venv/bin/uvicorn main:app --app-dir api --reload
```

Then open [http://localhost:8000](http://localhost:8000).

## Production deployment

```bash
./run_prod.sh
```

Binds to `127.0.0.1:8000` by default. Override with env vars or `server:` config in `config.yml`. See [CLAUDE.md](CLAUDE.md) for full configuration options and the systemd service setup.

## Running tests

```bash
venv/bin/python -m pytest tests/
```

## Project structure

```
api/                    FastAPI application
  data/
    badges.yml          Badge index (gewoon / buitengewoon)
    badges/<slug>.yml   Badge detail (5 topics × 3 niveaus)
    images/             Badge images (<slug>.1.png, .2.png, .3.png)
  routers/              JSON API and HTML route handlers
  main.py               Application entry point
  spec.md               API specification
frontend/
  templates/            Jinja2 HTML templates
  static/               CSS, favicon, and static assets
lib/insigne/            Installable library — all business logic
  users.py              User registration, authentication, profile
  progress.py           Progress tracking and sign-off workflow
  email.py              Email sending (registration, sign-off notifications)
  badges.py             Badge catalogue loader
  models.py             SQLAlchemy ORM models
  config.py             Configuration loader (reads config.yml)
systemd/                systemd user service files and install/uninstall scripts
tests/                  pytest unit and integration tests
insigne-ctl             Service control script (start/stop/restart/status/logs)
run_prod.sh             Production server start script
serve_dev.sh            Development server start script (auto-reload)
```

## License

Apache 2.0 — see [LICENSE.md](LICENSE.md).

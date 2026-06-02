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

Create your `config.yml` from the documented example (the real file is
gitignored — never commit it):

```bash
cp config.example.yml config.yml
```

Then edit `config.yml`: set a long random `jwt.secret_key`, your `base_url`,
and the `email`/SMTP and `admins` settings. Every option is documented inline
in [`config.example.yml`](config.example.yml).

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

> **Behind a reverse proxy:** deploy at the **root of a (sub)domain**
> (e.g. `https://insigne.scouting.nl`), **not** under a sub-path like
> `https://scouting.nl/insigne/`. The app uses root-absolute URLs throughout
> (links, redirects, and the service-worker scope), so a path prefix is not
> supported. Also make sure `base_url` exactly matches the public origin and
> pick one canonical host (301-redirect `www` ↔ apex), or the CSRF check
> rejects form posts with a 403 — see [`config.example.yml`](config.example.yml).

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

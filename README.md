# Insigne Systeem

A web application for scouts to track their progress through the [Scouting Nederland](https://www.scouting.nl) badge system.

## Features

- Browse the badge catalogue (gewoon and buitengewoon insignes)
- Log progress on individual badge steps
- Request sign-off from mentors by email — mentors are invited to register if they don't have an account yet
- HTMX-powered frontend served by the same FastAPI application

## Tech stack

- **Backend** — [FastAPI](https://fastapi.tiangolo.com)
- **Frontend** — [HTMX](https://htmx.org) + [Alpine.js](https://alpinejs.dev), Jinja2 templates
- **Badge data** — YAML files in `api/data/`

## Getting started

```bash
python3 -m venv venv
venv/bin/pip install -r requirements.txt
```

Run the development server from the **project root**:

```bash
venv/bin/uvicorn main:app --app-dir api --reload
```

Then open [http://localhost:8000](http://localhost:8000).

## Project structure

```
api/                  FastAPI application
  data/
    badges.yml        Badge index (gewoon / buitengewoon)
    badges/<slug>.yml Badge detail (steps, introduction, afterword)
    images/           Badge images (<slug>.1.png, .2.png, .3.png)
  main.py             Application entry point
  spec.md             API specification
frontend/
  templates/          Jinja2 HTML templates
  static/             CSS and static assets
```

## License

Apache 2.0 — see [LICENSE.md](LICENSE.md).

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

## Frontend stack

The UI is a **server-rendered Jinja2 + HTMX + Alpine.js** hybrid — there is no
SPA, no JS bundler, no build step. All three libraries are loaded from a CDN in
`frontend/templates/base.html`.

- **Jinja2** renders the page server-side from FastAPI route handlers
  (`api/routers/html_*.py`). Use `TemplateResponse` and pass context as a dict.
- **HTMX** (`htmx.org@2.0.4`) handles partial page updates without full reloads.
  Default to HTMX swaps over `window.location` redirects whenever a form POST
  would otherwise cause a scroll jump or full reload — typical pattern:
  - Wrap the swappable region in `<div id="some-id">…</div>`
  - Form uses `hx-post="…"` + `hx-target="#some-id"` + `hx-swap="outerHTML"`
  - The endpoint checks `request.headers.get("HX-Request")` and returns a
    `partials/*.html` fragment in that case; otherwise falls back to a redirect
    (so non-JS clients still work).
  - Partial templates must include their own wrapping div+id so subsequent
    swaps still target the same element.
- **Alpine.js** handles client-side state inside server-rendered HTML. Used for
  step-card status transitions, dropdowns (`<details>` with `@toggle`), and
  inline notes editing. Keep Alpine state scoped to a single element with
  `x-data="..."`; avoid global stores.
- **Font Awesome icons** are pasted inline as SVG `<path>` elements (no CDN, no
  font file). See `frontend/templates/partials/icon_running.html` and
  `icon_leaf.html` for the pattern: copy the path from Font Awesome Free 6.x,
  preserve the license comment, and use `fill="currentColor"` so colour follows
  CSS.
- **No CSS framework** — all styles live in `frontend/static/style.css`. Use
  the existing class system (`.btn-secondary`, `.btn-sm`, `.notification-bar`,
  `.step-card`, etc.) before inventing new classes; mobile breakpoint is 700px.
- **Partials live in `frontend/templates/partials/`** — extract anything used
  by both a full page render and an HTMX swap into a partial so both paths
  render identical HTML.

## API specification

The full API spec lives at `api/spec.md`. **Keep it up to date** whenever you add, change, or remove endpoints — both the JSON API (`/api/…`) and the HTML layer.

## Security conventions

### Redirects must use server-derived values, not raw URL parameters

When building a `RedirectResponse` URL, **never interpolate a function-argument
variable that came from a URL path parameter, query string, or form field**.
Always re-derive the value from a server-side lookup:

- `slug` (URL path param) → use `badge["slug"]` after `_CATALOGUE.get(slug)`.
- `scout_id` / `group_id` / `speltak_id` → use the looked-up ORM row's
  attribute (`scout.id`, `group.slug`, `speltak.slug`).
- For the failure path where the lookup returned `None`, redirect to a
  **constant** URL (`"/"`, `"/badges"`, `"/groups"`), never the raw input.

CodeQL's `py/url-redirection` taint analysis flags any function-parameter
string in a `RedirectResponse` regardless of upstream UUID / slug validation.
It treats ORM attribute reads and catalogue dict reads as untainted. This
convention is therefore enforceable by CodeQL: introducing a new redirect
that interpolates a raw parameter will surface as an open finding.

```python
# WRONG — slug is a URL path parameter, CodeQL flags this
return RedirectResponse(f"/badges/{slug}", status_code=303)

# RIGHT — badge["slug"] comes from the catalogue dict
badge = _CATALOGUE.get(slug)
if not badge:
    return RedirectResponse("/", status_code=303)
return RedirectResponse(f"/badges/{badge['slug']}", status_code=303)
```

This sweep was applied across `html_badges.py` and `html_groups.py` in
v0.12.1 (26 sites) and again on the jaarinsigne `set-level` handlers in
v1.0.0 (CodeQL #82). Keep it that way.

## Releases and the `releases` branch

**Never push to the `releases` branch unless explicitly instructed by the user.**
The `releases` branch always points to the latest released version and is only
advanced when the user says to make a new release.

### `CHANGELOG.md` workflow

The changelog is maintained **per pull request** under an `## [Unreleased]`
header at the top of the file. Every feature / bugfix / breaking change PR
adds its bullets there before merge — this avoids the "what did we do last
month?" archaeology when it's time to cut a release.

When a new release is made, the `[Unreleased]` section is **consolidated**
into the new version's section (re-grouped, copy-edited, duplicates merged),
the `[Unreleased]` header is reset to empty, and the release is tagged.

When a new release is made:
1. Move `## [Unreleased]` content into a new `## [vX.Y.Z] — YYYY-MM-DD` section
   (consolidate / copy-edit; keep the standard subsections `### Nieuw`,
   `### Verbeteringen`, `### Opgelost`, `### Beveiliging`).
2. Re-add an empty `## [Unreleased]` header at the top.
3. Tag the release commit (`git tag -a vX.Y.Z ...`).
4. Fast-forward `releases` to that tag commit.
5. Merge the tag into `main` (`git checkout main && git merge --no-ff vX.Y.Z`)
   so the tag is reachable from both `releases` and `main`.
6. Create the GitHub release.

## Keeping the JSON API in sync with the library

Every public function added to `lib/insigne/` must have a corresponding JSON API
endpoint in `api/routers/` and at least one API-layer test in `tests/test_api_*.py`.
The unit tests verify correctness of what exists but do not detect missing endpoints,
so this is enforced by convention in code review.

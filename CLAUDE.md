# Insigne Systeem

## Python environment
- Always use `venv/bin/python` and `venv/bin/pip` — never system Python.
- Install dependencies: `venv/bin/pip install -r requirements.txt`

## Configuration
Create `config.yml` from the documented template (never commit it — it is
gitignored):
```
cp config.example.yml config.yml
```
**`config.example.yml` is the single source of truth for configuration** —
every option (database, jwt, `server`, `base_url`, `email`/SMTP, `admins`,
`allow_any_user_to_create_groups`) is listed and commented there. When you add
or change a config key in `lib/insigne/config.py`, update `config.example.yml`
in the same change.

The app reads `config.yml` from the working directory on startup. Override the
path with the `INSIGNE_CONFIG` environment variable.

**`base_url` must exactly match the browser's origin** (scheme + host, no
trailing slash, no `:443`) — it is the trusted origin for the CSRF
Origin/Referer check (`api/main.py:origin_csrf_check`), so a mismatch returns
403 *before* the handler runs (a failed POST then also sends no e-mail). Pick
one canonical host and 301-redirect the other at the proxy (the classic trap is
`www` vs the bare apex), and force http → https. `server.forwarded_allow_ips`
governs only real-client-IP logging — it does **not** affect this check.

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

### Auth/access helpers must not return `RedirectResponse`

Closely related to the rule above: a helper that takes a tainted parameter
(URL path id, query string, form field) and returns a `RedirectResponse`
will trip CodeQL's `py/reflective-xss` checker, because CodeQL can't prove
that every redirect path inside the helper uses a constant URL — and the
return value carries that doubt out to the caller. Even if every redirect
*is* in fact constant, the union return type makes the data flow opaque.

**Convention**: auth/access helpers return *data* (`User`, `None`, sentinels),
never response objects. The route handler constructs `RedirectResponse(...)`
itself from string literals, picking the target based on the helper's
return value.

```python
# WRONG — CodeQL flags `return scout_or_redirect`
def _require_scout_access(request, scout_id, db):
    if not _UUID_RE.match(scout_id):
        return None, RedirectResponse("/", status_code=303)
    ...
    return current_user, scout

# RIGHT — helper returns data only; caller builds the response
def _require_scout_access(request, scout_id, db) -> tuple[User | None, User | None]:
    current_user = _get_current_user(request, db)
    if current_user is None:
        return None, None            # caller → "/login"
    if not _UUID_RE.match(scout_id):
        return current_user, None    # caller → "/"
    ...
    return current_user, scout

# Caller
current_user, scout = _require_scout_access(request, scout_id, db)
if scout is None:
    return RedirectResponse("/login" if current_user is None else "/", status_code=303)
```

Applied to `_require_scout_access` in v1.0.0 (CodeQL #87) and to
`_require_user` / `_require_admin` in v1.1.0 (cleared 46 dismissed
`py/reflective-xss` alerts from issue #100). Apply the same
shape to any future auth helper.

### State-changing HTML endpoints rely on two CSRF defences

Cookie-authenticated state-changing browser requests (POST / PUT / DELETE /
PATCH on routes outside `/api/`) are protected by two independent layers:

1. **SameSite=Lax** on the `access_token` cookie. Set at every cookie-issuing
   site in `api/routers/users.py`. Blocks the vast majority of cross-site
   form submissions in modern browsers.
2. **Origin / Referer check** in the middleware at `api/main.py:origin_csrf_check`,
   following the OWASP CSRF Cheat Sheet "Identifying the Source Origin".
   Rejects 403 if the browser-sent `Origin` differs from `config.base_url`;
   if `Origin` is absent, falls back to `Referer` (must start with
   `config.base_url`). Requests missing **both** headers are rejected —
   browsers always send at least one on POST/PUT/DELETE/PATCH; non-browser
   clients should use the bearer-token API under `/api/`. Skips paths under
   `/api/` (bearer-token auth, not cookie-driven).

Together these are layer-1 and layer-2 of the same CSRF defence. Adding a
new state-changing HTML endpoint requires no per-route work — both layers
apply automatically as soon as it's registered. **Don't add a state-changing
GET endpoint** — it bypasses both layers. The two existing GET-mutating
endpoints (`/register/confirm/{code}` and `/profile/email-change/confirm/{token}`)
are e-mail-link confirmation flows whose one-shot secret tokens make them
CSRF-resistant by design; they're a deliberate exception, not a precedent.

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

## JSON API — removed in v1.2.0

The JSON API mirror of `lib/insigne/` was removed in v1.2.0 (issue #117).
The `api/routers/api_*.py` files, the `api/schemas.py` schemas, and
`api/spec.md` no longer exist on `main`; the matching `tests/integration/test_api_*.py`
test files are gone too.

If a future need arises (mobile app, external integration), the last
commit containing the API is reachable via the `json-api-final` tag:

```
git checkout -b restore-json-api json-api-final
# cherry-pick the routers you need onto a feature branch
```

The library functions in `lib/insigne/` were the source of truth for
the API and are still tested directly via the unit suite — rebuilding
endpoints over them is mechanical.

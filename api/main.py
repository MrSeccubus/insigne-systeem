import logging
import os
from datetime import datetime
from pathlib import Path

from fastapi import Depends, FastAPI, Request
from fastapi.responses import (
    FileResponse,
    HTMLResponse,
    JSONResponse,
    PlainTextResponse,
    Response,
)
from fastapi.staticfiles import StaticFiles
from sqlalchemy.orm import Session
from uvicorn.logging import DefaultFormatter

import insigne.models  # noqa: F401 — registers all ORM classes on Base.metadata

# Route ``insigne.*`` log records through uvicorn's DefaultFormatter so they
# show up in the same stream and format as uvicorn's access / error log:
#
#     INFO:     127.0.0.1:62389 - "GET /login HTTP/1.1" 200 OK
#     WARNING:  127.0.0.1 - "POST /login HTTP/1.1" 401 invalid credentials …
#
# Without this, ``insigne.*`` records fall through to Python's lastResort
# StreamHandler which prints just the bare message — the user sees uvicorn
# lines and bare app messages side-by-side. Idempotent: guard with the
# handler-list check so re-imports under tests don't pile up handlers.
_insigne_logger = logging.getLogger("insigne")
if not any(isinstance(h.formatter, DefaultFormatter) for h in _insigne_logger.handlers):
    _h = logging.StreamHandler()
    _h.setFormatter(DefaultFormatter("%(levelprefix)s %(message)s"))
    _insigne_logger.addHandler(_h)
    _insigne_logger.setLevel(logging.INFO)
from insigne import groups as groups_svc
from insigne import progress as progress_svc
from insigne import users as users_svc
from insigne.badges import BadgeCatalogue, jaarinsigne_levels_for_scout
from insigne.config import config
from insigne.database import get_db
import captcha
from ratelimit import limiter
from routers import html_admin, html_badges, html_contact, html_groups, users
from routers.users import _get_current_user
from slowapi.errors import RateLimitExceeded
from templates import templates

BASE_DIR = Path(__file__).parent.parent
FRONTEND_DIR = BASE_DIR / "frontend"
DATA_DIR = Path(__file__).parent / "data"
IMAGES_DIR = DATA_DIR / "images"
_CATALOGUE = BadgeCatalogue(DATA_DIR)
_DEV = os.environ.get("INSIGNE_DEV") == "1"  # set by serve_dev.sh

app = FastAPI()

# Per-IP rate limiting on the unauthenticated e-mail-sending endpoints
# (see ratelimit.py). The per-route @limiter.limit decorators need the limiter
# on app.state plus an exception handler for the 429.
app.state.limiter = limiter


@app.exception_handler(RateLimitExceeded)
async def _rate_limit_handler(request: Request, exc: RateLimitExceeded):
    return PlainTextResponse(
        "Te veel aanvragen. Probeer het over een tijdje opnieuw.",
        status_code=429,
        headers={"Retry-After": "3600"},
    )


# ── CSRF defence-in-depth: Origin / Referer header check ──────────────────────
#
# Authenticated state-changing requests are primarily protected by the
# access_token cookie's ``SameSite=Lax`` attribute. This middleware adds a
# second layer per the OWASP CSRF Cheat Sheet ("Identifying the Source Origin
# via Origin/Referer header"): any state-changing request whose Origin (or
# Referer, as fallback) doesn't match ``config.base_url`` is rejected with 403.
#
# Rules:
#  - GET / HEAD / OPTIONS are not checked (not state-changing).
#  - Paths under ``/api/`` are exempt — the JSON API uses bearer-token auth,
#    not cookies, so cross-site requests can't ride on the session.
#  - If ``Origin`` is present, it must match ``config.base_url`` exactly.
#  - If ``Origin`` is absent but ``Referer`` is present, ``Referer`` must
#    start with ``config.base_url`` (same scheme + host + port).
#  - If neither header is present, the request is rejected. Browsers always
#    send at least one on POST/PUT/DELETE/PATCH; non-browser clients should
#    use the bearer-token API under ``/api/``.
#
# Closes issue #99.

_CSRF_STATE_CHANGING_METHODS = {"POST", "PUT", "DELETE", "PATCH"}


def _csrf_reject(detail: str):
    return PlainTextResponse(
        f"Aanvraag geweigerd: {detail} "
        "Probeer opnieuw vanaf de oorspronkelijke pagina.",
        status_code=403,
    )


@app.middleware("http")
async def origin_csrf_check(request: Request, call_next):
    if request.method in _CSRF_STATE_CHANGING_METHODS and not request.url.path.startswith("/api/"):
        origin = request.headers.get("origin")
        referer = request.headers.get("referer")
        if origin:
            if origin != config.base_url:
                return _csrf_reject("ongeldige Origin-header.")
        elif referer:
            # The ``+ "/"`` is what makes the prefix check safe against
            # path-confusion (e.g. ``http://localhost:8000.evil.com/``):
            # the byte after the port must be ``/``, not anything else.
            # Relies on ``config.base_url`` being stripped of any trailing
            # slash at parse time (see lib/insigne/config.py).
            if not (referer == config.base_url or referer.startswith(config.base_url + "/")):
                return _csrf_reject("ongeldige Referer-header.")
        else:
            return _csrf_reject("Origin- en Referer-header ontbreken.")
    return await call_next(request)


# ── Security headers ──────────────────────────────────────────────────────────
#
# Applied to every response. The CSP is deliberately *pragmatic*, not strict:
# the UI uses inline <script> blocks and Alpine.js, which evaluates its x-data /
# @click expressions via ``new Function`` — so ``script-src`` must allow
# ``'unsafe-inline'`` and ``'unsafe-eval'``. Tightening to a nonce/hash-based
# policy would mean refactoring every inline script and dropping the standard
# Alpine build; out of scope here. What this still buys us:
#   * frame-ancestors 'none' + X-Frame-Options: DENY — clickjacking protection
#     on the cookie-authenticated forms (logout, sign-off, delete, approve…).
#   * object-src 'none', base-uri 'self', form-action 'self' — shrink the XSS
#     blast radius and block <base>/form-action hijacking.
#   * X-Content-Type-Options: nosniff — no MIME sniffing.
# Notes:
#   * worker-src allows blob: because the ALTCHA captcha widget spawns its
#     proof-of-work worker from a Blob URL — without it the captcha breaks.
#   * All app resources (vendored JS, css, images, /altcha/challenge, htmx
#     fetches) are same-origin, so 'self' covers script/style/img/connect.
#   * HSTS is intentionally NOT set here — it belongs at the TLS-terminating
#     reverse proxy (and must never be sent over plain-HTTP dev/localhost).
_CSP = "; ".join([
    "default-src 'self'",
    "script-src 'self' 'unsafe-inline' 'unsafe-eval'",
    "style-src 'self' 'unsafe-inline'",
    "img-src 'self' data:",
    "connect-src 'self'",
    "worker-src 'self' blob:",
    "frame-ancestors 'none'",
    "object-src 'none'",
    "base-uri 'self'",
    "form-action 'self'",
])
_SECURITY_HEADERS = {
    "Content-Security-Policy": _CSP,
    "X-Frame-Options": "DENY",
    "X-Content-Type-Options": "nosniff",
    "Referrer-Policy": "same-origin",
}


@app.middleware("http")
async def security_headers(request: Request, call_next):
    response = await call_next(request)
    # Direct assignment (not setdefault) so this policy is authoritative — a
    # handler can't accidentally ship a weaker CSP/X-Frame-Options. No handler
    # sets these today; this keeps it that way. (Unhandled-500 responses from
    # Starlette's ServerErrorMiddleware sit above this middleware and so don't
    # get these headers — acceptable: they're generic error pages.)
    for header, value in _SECURITY_HEADERS.items():
        response.headers[header] = value
    return response


app.include_router(users.router)
app.include_router(html_admin.router)
app.include_router(html_badges.router)
app.include_router(html_groups.router)
app.include_router(html_contact.router)
app.include_router(captcha.router)

class _ImmutableStaticFiles(StaticFiles):
    """StaticFiles with a 1-year immutable Cache-Control (Lighthouse "efficient
    cache policy"). Safe for /images (badge artwork never changes per URL) and
    for /static: assets that can change — style.css, badge_filters.js, and the
    vendored JS (which must be patchable, e.g. for a security fix) — are
    cache-busted with a ``?v={app_version}`` query in base.html (a new URL on
    each release, so a patched file reaches clients immediately despite
    ``immutable``); icons/manifest/favicon are stable. Applies to both 200 and
    304 (both expose
    ``.headers``). Note: ``/sw.js`` is served by its own route with no-cache, so
    the worker itself is never immutably cached."""

    def file_response(self, *args, **kwargs):
        resp = super().file_response(*args, **kwargs)
        # In dev (serve_dev.sh sets INSIGNE_DEV=1) don't cache, so edits to
        # static assets show on reload without cache-busting or hard-reloads.
        resp.headers["Cache-Control"] = (
            "no-cache" if _DEV else "public, max-age=31536000, immutable"
        )
        return resp


IMAGES_DIR.mkdir(parents=True, exist_ok=True)
app.mount("/static", _ImmutableStaticFiles(directory=FRONTEND_DIR / "static"), name="static")
app.mount("/images", _ImmutableStaticFiles(directory=IMAGES_DIR), name="images")


# ── PWA pages (#101) ──────────────────────────────────────────────────────────

@app.get("/ping", include_in_schema=False)
async def ping():
    """Tiny connectivity probe for the client's offline detection. The service
    worker never intercepts it, so a failed fetch means the client is truly
    offline — more reliable than ``navigator.onLine``, which doesn't flip on
    reload under throttling or on a network with no real internet."""
    return Response(status_code=204)


@app.get("/sw.js", include_in_schema=False)
async def service_worker():
    """Serve the service worker from the ROOT path so it can claim ``scope: /``.

    A worker served from ``/static/sw.js`` may, by default, only control
    ``/static/`` — registering it with ``scope: "/"`` is rejected by the browser
    unless the response carries ``Service-Worker-Allowed: /``. Serving it from
    the root sidesteps that (its max scope is ``/``); the header is added too as
    belt-and-suspenders. ``no-cache`` so a new deploy's worker is picked up."""
    return FileResponse(
        FRONTEND_DIR / "static" / "sw.js",
        media_type="text/javascript",
        headers={"Service-Worker-Allowed": "/", "Cache-Control": "no-cache"},
    )


@app.get("/install", response_class=HTMLResponse)
async def install_instructions(request: Request, db: Session = Depends(get_db)):
    return templates.TemplateResponse(
        request=request, name="install.html",
        context={
            "current_user": _get_current_user(request, db),
            "install_url": config.base_url,
        },
    )


@app.get("/sync", response_class=HTMLResponse)
async def sync_page(request: Request, db: Session = Depends(get_db)):
    """Pre-download the badge catalogue into the offline cache. Reachable from
    the 'Data synchroniseren' menu item, which is only shown when running as an
    installed PWA (client-side, see base.html)."""
    return templates.TemplateResponse(
        request=request, name="sync.html",
        context={"current_user": _get_current_user(request, db)},
    )


@app.get("/offline", response_class=HTMLResponse)
async def offline_fallback(request: Request, db: Session = Depends(get_db)):
    """Served by the service worker when no cached entry is available."""
    return templates.TemplateResponse(
        request=request, name="offline.html",
        context={"current_user": _get_current_user(request, db)},
    )


@app.get("/offline/disabled", response_class=HTMLResponse)
async def offline_disabled(request: Request, db: Session = Depends(get_db)):
    """Served by the service worker for screens that can't work offline
    (aftekeningen, groepsbeheer, admin). Pre-cached as part of the SW shell."""
    return templates.TemplateResponse(
        request=request, name="offline_disabled.html",
        context={"current_user": _get_current_user(request, db)},
    )


@app.get("/offline/manifest.json")
async def offline_manifest(request: Request, db: Session = Depends(get_db)):
    """URLs the 'Data synchroniseren' button warms into the cache. Always the
    whole badge catalogue (every eis on every niveau, niveau selection being
    client-side) plus artwork. For a logged-in user we also add their own home
    page and the speltak progress overviews they lead, so a leader can review
    their speltak offline (the catalogue badge pages already render the user's
    own progress, so a scout's own progress is covered too). All URLs are
    server-derived (catalogue dict / ORM slugs), never request input."""
    urls: list[str] = []
    for badges in _CATALOGUE.list().values():
        for badge in badges:
            urls.append(f"/badges/{badge['slug']}")
            urls.extend(badge.get("images", []))

    current_user = _get_current_user(request, db)
    if current_user is not None:
        urls.append("/")
        led = groups_svc.list_my_speltakken(db, current_user.id)
        if led:
            urls.append("/my-speltakken")
            for group, speltak in led:
                urls.append(f"/groups/{group.slug}/speltakken/{speltak.slug}/progress")
    return JSONResponse({"urls": urls})


@app.get("/", response_class=HTMLResponse)
async def index(request: Request, db: Session = Depends(get_db)):
    current_user = _get_current_user(request, db)

    all_badges = _CATALOGUE.list()
    signoff_count = 0
    all_progress: dict[str, dict] = {}
    user_favorite_slugs: set[str] = set()
    progress_slugs: set[str] = set()

    group_invites: list = []
    speltak_invites: list = []
    my_requests: list = []
    pending_request_count = 0
    my_group_memberships: list = []
    my_speltak_memberships: list = []
    current_user_speltak_types: set[str] = set()
    if current_user:
        for entry in progress_svc.list_progress(db, current_user.id):
            all_progress.setdefault(entry.badge_slug, {})[(entry.level_index, entry.step_index)] = entry
        signoff_count = len(progress_svc.list_signoff_requests(db, current_user.id))
        group_invites, speltak_invites = groups_svc.list_pending_invitations_for_user(db, current_user.id)
        my_requests = groups_svc.list_my_membership_requests(db, current_user.id)
        pending_request_count = groups_svc.count_pending_requests_for_leader(db, current_user.id)
        my_group_memberships, my_speltak_memberships = groups_svc.list_active_memberships_for_user(db, current_user.id)
        user_favorite_slugs = users_svc.get_user_favorite_slugs(db, current_user.id)
        progress_slugs = set(all_progress.keys())
        # All speltak types the current user has any active membership in,
        # regardless of role. The home page uses this for category-section
        # default-expand rules: ``"explorers" in current_user_speltak_types``
        # tells the Explorers section to render uncollapsed. Future categories
        # ("bevers", etc.) can reuse the same set without adding new context.
        current_user_speltak_types = {
            m.speltak.speltak_type
            for m in my_speltak_memberships
            if m.speltak and m.speltak.speltak_type
        }

    # Enrich each badge with level cards
    for badges in all_badges.values():
        for badge in badges:
            detail = _CATALOGUE.get(badge["slug"])
            if detail.get("type") == "jaarinsigne":
                badge["type"] = "jaarinsigne"
                slug_progress = all_progress.get(badge["slug"], {})
                jl = progress_svc.get_jaarinsigne_level(db, current_user.id, badge["slug"]) if current_user else None
                if jl:
                    speltak_slug = jl.speltak_slug
                elif current_user:
                    speltak_slug = groups_svc.get_user_primary_speltak_type(db, current_user.id)
                else:
                    speltak_slug = None
                resolved_level_index = _CATALOGUE.resolve_jaarinsigne_level_index(detail, speltak_slug)
                levels_to_show = jaarinsigne_levels_for_scout(detail, slug_progress, resolved_level_index)
                if levels_to_show:
                    cards = []
                    for level in levels_to_show:
                        li = level["level_index"]
                        n_steps = len(level["steps"])
                        cards.append({
                            "index": li,
                            "name": level["name"],
                            "short_name": level["kort"],
                            "image": f"/images/{badge['slug']}.png",
                            "total": n_steps,
                            "completed": sum(
                                1 for step_idx in range(n_steps)
                                if slug_progress.get((li, step_idx))
                                and slug_progress[(li, step_idx)].status == "signed_off"
                            ),
                            "completed_at": max(
                                (slug_progress[(li, step_idx)].signed_off_at
                                 for step_idx in range(n_steps)
                                 if slug_progress.get((li, step_idx))
                                 and slug_progress[(li, step_idx)].status == "signed_off"
                                 and slug_progress[(li, step_idx)].signed_off_at),
                                default=None,
                            ),
                        })
                    badge["level_cards"] = cards
                else:
                    # Jaarinsigne not available for this scout's speltak and no
                    # progress to show. Render a placeholder card so the user can
                    # still navigate to the detail page.
                    badge["level_cards"] = [{
                        "index": -1,
                        "name": "Niet beschikbaar voor jouw speltak",
                        "short_name": "—",
                        "image": f"/images/{badge['slug']}.png",
                        "total": 0,
                        "completed": 0,
                        "completed_at": None,
                        "unavailable": True,
                    }]
                continue
            badge["type"] = "gewoon"
            niveau_label = detail.get("niveau_label", "Niveau")
            niveau_label_kort = detail.get("niveau_label_kort", "N")
            badge["level_cards"] = [
                {
                    "index": niveau_idx,
                    "name": f"{niveau_label} {niveau_idx + 1}",
                    "short_name": f"{niveau_label_kort}{niveau_idx + 1}",
                    "image": f"/images/{badge['slug']}.{niveau_idx + 1}.png",
                    "total": sum(
                        1 for group in detail["levels"]
                        if group["steps"][niveau_idx]["text"].strip()
                    ),
                    "completed": sum(
                        1 for eis_idx, group in enumerate(detail["levels"])
                        if group["steps"][niveau_idx]["text"].strip()
                        and all_progress.get(badge["slug"], {}).get((eis_idx, niveau_idx))
                        and all_progress[badge["slug"]][(eis_idx, niveau_idx)].status == "signed_off"
                    ),
                    "completed_at": max(
                        (all_progress[badge["slug"]][(eis_idx, niveau_idx)].signed_off_at
                         for eis_idx, group in enumerate(detail["levels"])
                         if group["steps"][niveau_idx]["text"].strip()
                         and all_progress.get(badge["slug"], {}).get((eis_idx, niveau_idx))
                         and all_progress[badge["slug"]][(eis_idx, niveau_idx)].status == "signed_off"
                         and all_progress[badge["slug"]][(eis_idx, niveau_idx)].signed_off_at),
                        default=None,
                    ),
                }
                for niveau_idx in range(3)
            ]

    signed_off_niveaus = sorted(
        [
            {
                "slug": badge["slug"],
                "title": badge["title"],
                "niveau_number": card["index"] + 1,
                "image": card["image"],
                "completed_at": card["completed_at"],
            }
            for badges in all_badges.values()
            for badge in badges
            for card in badge["level_cards"]
            if card["completed"] == card["total"] and card["total"] > 0
        ],
        key=lambda n: n["completed_at"] or datetime.min,
    )

    response = templates.TemplateResponse(
        request=request,
        name="index.html",
        context={
            "current_user": current_user,
            "category_labels": _CATALOGUE.category_labels,
            "all_badges": all_badges,
            "all_progress": all_progress,
            "signoff_count": signoff_count,
            "group_invites": group_invites,
            "speltak_invites": speltak_invites,
            "my_requests": my_requests,
            "pending_request_count": pending_request_count,
            "my_group_memberships": my_group_memberships,
            "my_speltak_memberships": my_speltak_memberships,
            "allow_invite_leader": current_user and (config.allow_any_user_to_create_groups or current_user.is_admin),
            "signed_off_niveaus": signed_off_niveaus,
            "user_favorite_slugs": user_favorite_slugs,
            "progress_slugs": progress_slugs,
            "current_user_speltak_types": current_user_speltak_types,
        },
    )
    response.headers["Cache-Control"] = "no-store"
    return response


@app.get("/ping")
async def ping():
    return HTMLResponse("<p>Pong from FastAPI.</p>")

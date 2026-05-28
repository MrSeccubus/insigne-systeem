from datetime import datetime
from pathlib import Path

from fastapi import Depends, FastAPI, Request
from fastapi.responses import HTMLResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy.orm import Session

import insigne.models  # noqa: F401 — registers all ORM classes on Base.metadata
from insigne import groups as groups_svc
from insigne import progress as progress_svc
from insigne import users as users_svc
from insigne.badges import BadgeCatalogue, jaarinsigne_levels_for_scout
from insigne.config import config
from insigne.database import get_db
from routers import api_admin, api_auth, api_badges, api_contact, api_groups, api_progress, api_users, api_version, html_admin, html_badges, html_contact, html_groups, users
from routers.api_groups import invitations_router, pending_requests_router
from routers.users import _get_current_user
from templates import templates

BASE_DIR = Path(__file__).parent.parent
FRONTEND_DIR = BASE_DIR / "frontend"
DATA_DIR = Path(__file__).parent / "data"
IMAGES_DIR = DATA_DIR / "images"
_CATALOGUE = BadgeCatalogue(DATA_DIR)

app = FastAPI()


# ── CSRF defence-in-depth: Origin header check ─────────────────────────────────
#
# Authenticated state-changing requests are primarily protected by the
# access_token cookie's ``SameSite=Lax`` attribute, which blocks the
# overwhelming majority of cross-site form submissions. This middleware adds a
# second layer: any browser-driven state-changing request whose Origin header
# doesn't match ``config.base_url`` is rejected with 403, regardless of
# SameSite behaviour.
#
# What's allowed without an Origin check:
#  - Non-state-changing HTTP methods (GET / HEAD / OPTIONS).
#  - Paths under ``/api/`` — the JSON API uses bearer-token auth, not cookies,
#    so cross-site requests can't ride on the session.
#  - Requests that omit the Origin header entirely. Browsers always send Origin
#    on POST/PUT/DELETE/PATCH; only non-browser clients (curl, server-to-server,
#    TestClient) omit it. Blocking them would be over-strict for what is
#    primarily a CSRF defence.
#
# Closes issue #99 (the "evaluate CSRF posture" follow-up).

_CSRF_STATE_CHANGING_METHODS = {"POST", "PUT", "DELETE", "PATCH"}


@app.middleware("http")
async def origin_csrf_check(request: Request, call_next):
    if request.method in _CSRF_STATE_CHANGING_METHODS and not request.url.path.startswith("/api/"):
        origin = request.headers.get("origin")
        if origin and origin != config.base_url:
            return PlainTextResponse(
                "Aanvraag geweigerd: ongeldige Origin-header. "
                "Probeer opnieuw vanaf de oorspronkelijke pagina.",
                status_code=403,
            )
    return await call_next(request)


app.include_router(users.router)
app.include_router(html_admin.router)
app.include_router(html_badges.router)
app.include_router(html_groups.router)
app.include_router(html_contact.router)
app.include_router(api_users.router, prefix="/api")
app.include_router(api_contact.router, prefix="/api")
app.include_router(api_auth.router, prefix="/api")
app.include_router(api_progress.router, prefix="/api")
app.include_router(api_badges.router, prefix="/api")
app.include_router(api_version.router, prefix="/api")
app.include_router(api_admin.router, prefix="/api")
app.include_router(api_groups.router, prefix="/api")
app.include_router(invitations_router, prefix="/api")
app.include_router(pending_requests_router, prefix="/api")

IMAGES_DIR.mkdir(parents=True, exist_ok=True)
app.mount("/static", StaticFiles(directory=FRONTEND_DIR / "static"), name="static")
app.mount("/images", StaticFiles(directory=IMAGES_DIR), name="images")


@app.get("/", response_class=HTMLResponse)
async def index(request: Request, only_favorites: int = 0, only_in_progress: int = 0, db: Session = Depends(get_db)):
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
            "only_favorites": bool(only_favorites and current_user),
            "progress_slugs": progress_slugs,
            "only_in_progress": bool(only_in_progress and current_user),
            "current_user_speltak_types": current_user_speltak_types,
        },
    )
    response.headers["Cache-Control"] = "no-store"
    return response


@app.get("/ping")
async def ping():
    return HTMLResponse("<p>Pong from FastAPI.</p>")

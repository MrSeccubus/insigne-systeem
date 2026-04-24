from pathlib import Path

from fastapi import Depends, FastAPI, Request
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy.orm import Session

import insigne.models  # noqa: F401 — registers all ORM classes on Base.metadata
from insigne import groups as groups_svc
from insigne import progress as progress_svc
from insigne.badges import get_badge, list_badges
from insigne.config import config
from insigne.database import get_db
from routers import api_auth, api_badges, api_contact, api_groups, api_progress, api_users, html_badges, html_contact, html_groups, users
from routers.api_groups import invitations_router, pending_requests_router
from routers.users import _get_current_user
from templates import templates

BASE_DIR = Path(__file__).parent.parent
FRONTEND_DIR = BASE_DIR / "frontend"
DATA_DIR = Path(__file__).parent / "data"
IMAGES_DIR = DATA_DIR / "images"

app = FastAPI()

app.include_router(users.router)
app.include_router(html_badges.router)
app.include_router(html_groups.router)
app.include_router(html_contact.router)
app.include_router(api_users.router, prefix="/api")
app.include_router(api_contact.router, prefix="/api")
app.include_router(api_auth.router, prefix="/api")
app.include_router(api_progress.router, prefix="/api")
app.include_router(api_badges.router, prefix="/api")
app.include_router(api_groups.router, prefix="/api")
app.include_router(invitations_router, prefix="/api")
app.include_router(pending_requests_router, prefix="/api")

IMAGES_DIR.mkdir(parents=True, exist_ok=True)
app.mount("/static", StaticFiles(directory=FRONTEND_DIR / "static"), name="static")
app.mount("/images", StaticFiles(directory=IMAGES_DIR), name="images")


@app.get("/", response_class=HTMLResponse)
async def index(request: Request, db: Session = Depends(get_db)):
    current_user = _get_current_user(request, db)

    all_badges = list_badges(DATA_DIR)
    signoff_count = 0
    all_progress: dict[str, dict] = {}

    group_invites: list = []
    speltak_invites: list = []
    my_requests: list = []
    pending_request_count = 0
    my_group_memberships: list = []
    my_speltak_memberships: list = []
    if current_user:
        for entry in progress_svc.list_progress(db, current_user.id):
            all_progress.setdefault(entry.badge_slug, {})[(entry.level_index, entry.step_index)] = entry
        signoff_count = len(progress_svc.list_signoff_requests(db, current_user.id))
        group_invites, speltak_invites = groups_svc.list_pending_invitations_for_user(db, current_user.id)
        my_requests = groups_svc.list_my_membership_requests(db, current_user.id)
        pending_request_count = groups_svc.count_pending_requests_for_leader(db, current_user.id)
        my_group_memberships, my_speltak_memberships = groups_svc.list_active_memberships_for_user(db, current_user.id)

    # Enrich each badge with 3 niveau cards (one per a/b/c sub-task level)
    for badges in all_badges.values():
        for badge in badges:
            detail = get_badge(DATA_DIR, badge["slug"])
            n_eisen = len(detail["levels"])  # always 5
            badge["level_cards"] = [
                {
                    "index": niveau_idx,
                    "name": f"Niveau {niveau_idx + 1}",
                    "image": f"/images/{badge['slug']}.{niveau_idx + 1}.png",
                    "total": n_eisen,
                    "completed": sum(
                        1 for eis_idx in range(n_eisen)
                        if all_progress.get(badge["slug"], {}).get((eis_idx, niveau_idx)) and
                           all_progress[badge["slug"]][(eis_idx, niveau_idx)].status == "signed_off"
                    ),
                }
                for niveau_idx in range(3)
            ]

    response = templates.TemplateResponse(
        request=request,
        name="index.html",
        context={
            "current_user": current_user,
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
        },
    )
    response.headers["Cache-Control"] = "no-store"
    return response


@app.get("/ping")
async def ping():
    return HTMLResponse("<p>Pong from FastAPI.</p>")

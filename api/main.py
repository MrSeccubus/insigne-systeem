from pathlib import Path

from fastapi import Depends, FastAPI, Request
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

import insigne.models  # noqa: F401 — registers all ORM classes on Base.metadata
from insigne import progress as progress_svc
from insigne.badges import get_badge, list_badges
from insigne.database import Base, engine, get_db
from routers import api_auth, api_badges, api_progress, api_users, html_badges, users
from routers.users import _get_current_user

BASE_DIR = Path(__file__).parent.parent
FRONTEND_DIR = BASE_DIR / "frontend"
DATA_DIR = Path(__file__).parent / "data"
IMAGES_DIR = DATA_DIR / "images"

app = FastAPI()

Base.metadata.create_all(bind=engine)

app.include_router(users.router)
app.include_router(html_badges.router)
app.include_router(api_users.router, prefix="/api")
app.include_router(api_auth.router, prefix="/api")
app.include_router(api_progress.router, prefix="/api")
app.include_router(api_badges.router, prefix="/api")

IMAGES_DIR.mkdir(parents=True, exist_ok=True)
app.mount("/static", StaticFiles(directory=FRONTEND_DIR / "static"), name="static")
app.mount("/images", StaticFiles(directory=IMAGES_DIR), name="images")
templates = Jinja2Templates(directory=FRONTEND_DIR / "templates")
templates.env.globals["current_user"] = None


@app.get("/", response_class=HTMLResponse)
async def index(request: Request, db: Session = Depends(get_db)):
    current_user = _get_current_user(request, db)

    all_badges = list_badges(DATA_DIR)
    badge_stats: dict[str, dict] = {}
    signoff_count = 0

    if current_user:
        all_entries = progress_svc.list_progress(db, current_user.id)
        completed_by_slug: dict[str, int] = {}
        for entry in all_entries:
            if entry.status == "completed":
                completed_by_slug[entry.badge_slug] = completed_by_slug.get(entry.badge_slug, 0) + 1

        for badges in all_badges.values():
            for badge in badges:
                detail = get_badge(DATA_DIR, badge["slug"])
                total = sum(len(level["steps"]) for level in detail["levels"])
                badge_stats[badge["slug"]] = {
                    "total": total,
                    "completed": completed_by_slug.get(badge["slug"], 0),
                }

        signoff_count = len(progress_svc.list_signoff_requests(db, current_user.id))

    return templates.TemplateResponse(
        request=request,
        name="index.html",
        context={
            "current_user": current_user,
            "all_badges": all_badges,
            "badge_stats": badge_stats,
            "signoff_count": signoff_count,
        },
    )


@app.get("/ping")
async def ping():
    return HTMLResponse("<p>Pong from FastAPI.</p>")

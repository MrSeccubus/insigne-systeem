from pathlib import Path

from fastapi import Depends, FastAPI, Request
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

import insigne.models  # noqa: F401 — registers all ORM classes on Base.metadata
from insigne.database import Base, engine, get_db
from routers import api_auth, api_badges, api_progress, api_users, users
from routers.users import _get_current_user

BASE_DIR = Path(__file__).parent.parent
FRONTEND_DIR = BASE_DIR / "frontend"
IMAGES_DIR = Path(__file__).parent / "data" / "images"

app = FastAPI()

Base.metadata.create_all(bind=engine)

app.include_router(users.router)
app.include_router(api_users.router, prefix="/api")
app.include_router(api_auth.router, prefix="/api")
app.include_router(api_progress.router, prefix="/api")
app.include_router(api_badges.router, prefix="/api")

IMAGES_DIR.mkdir(parents=True, exist_ok=True)
app.mount("/static", StaticFiles(directory=FRONTEND_DIR / "static"), name="static")
app.mount("/images", StaticFiles(directory=IMAGES_DIR), name="images")
templates = Jinja2Templates(directory=FRONTEND_DIR / "templates")


@app.get("/", response_class=HTMLResponse)
async def index(request: Request, db: Session = Depends(get_db)):
    current_user = _get_current_user(request, db)
    return templates.TemplateResponse(
        request=request,
        name="index.html",
        context={"current_user": current_user},
    )


@app.get("/ping")
async def ping():
    return HTMLResponse("<p>Pong from FastAPI.</p>")

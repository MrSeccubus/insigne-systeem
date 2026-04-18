from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

load_dotenv()

import models  # noqa: F401 — registers all ORM classes on Base.metadata
from database import Base, engine

BASE_DIR = Path(__file__).parent.parent
FRONTEND_DIR = BASE_DIR / "frontend"
IMAGES_DIR = Path(__file__).parent / "data" / "images"

app = FastAPI()

Base.metadata.create_all(bind=engine)

app.mount("/static", StaticFiles(directory=FRONTEND_DIR / "static"), name="static")
app.mount("/images", StaticFiles(directory=IMAGES_DIR), name="images")
templates = Jinja2Templates(directory=FRONTEND_DIR / "templates")


@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    return templates.TemplateResponse(request=request, name="index.html")


@app.get("/ping")
async def ping():
    return HTMLResponse("<p>Pong from FastAPI.</p>")

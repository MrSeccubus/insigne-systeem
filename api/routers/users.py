from pathlib import Path

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from insigne import users as user_svc
from insigne.auth import create_access_token
from insigne.database import get_db
from insigne.email import send_password_reset_email, send_registration_email, send_welcome_email

router = APIRouter()

_TEMPLATES = Jinja2Templates(directory=Path(__file__).parent.parent.parent / "frontend" / "templates")


def _partial(request: Request, name: str, **ctx):
    return _TEMPLATES.TemplateResponse(request=request, name=f"partials/{name}", context=ctx)


@router.get("/register", response_class=HTMLResponse)
async def register_page(request: Request):
    return _TEMPLATES.TemplateResponse(request=request, name="register.html")


@router.post("/register", response_class=HTMLResponse)
async def register(
    request: Request,
    email: str = Form(...),
    db: Session = Depends(get_db),
):
    code, token_type, user = user_svc.start_registration(db, email)
    naam = user.name or user.email.split("@")[0]
    if token_type == "email_confirmation":
        send_registration_email(user.email, naam, code)
    else:
        send_password_reset_email(user.email, naam, code)
    return _partial(request, "register_step2.html", email=email.strip().lower())


@router.post("/register/confirm", response_class=HTMLResponse)
async def register_confirm(
    request: Request,
    email: str = Form(...),
    code: str = Form(...),
    db: Session = Depends(get_db),
):
    setup_token = user_svc.confirm_email(db, code)
    if setup_token is None:
        return _partial(request, "register_step2.html", email=email,
                        error="Invalid or expired code. Please try again.")
    return _partial(request, "register_step3.html", setup_token=setup_token)


@router.post("/register/activate", response_class=HTMLResponse)
async def register_activate(
    request: Request,
    setup_token: str = Form(...),
    password: str = Form(...),
    name: str = Form(""),
    db: Session = Depends(get_db),
):
    try:
        user, is_new = user_svc.activate_account(db, setup_token, password, name)
    except user_svc.ActivationError as exc:
        if str(exc) == "expired":
            error = "This link has expired. Please start over."
        else:
            error = "Password must be at least 8 characters."
        return _partial(request, "register_step3.html", setup_token=setup_token, error=error)

    if is_new:
        send_welcome_email(user.email, user.name or user.email.split("@")[0])
    access_token, _ = create_access_token(user.id)
    response = HTMLResponse(content="")
    response.headers["HX-Redirect"] = "/"
    response.set_cookie(
        key="access_token",
        value=access_token,
        httponly=True,
        samesite="lax",
        max_age=30 * 24 * 3600,
    )
    return response

from pathlib import Path

import jwt
from fastapi import APIRouter, BackgroundTasks, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from insigne import users as user_svc
from insigne.auth import create_access_token, decode_access_token
from insigne.config import config
from insigne.database import get_db
from insigne.email import send_password_reset_email, send_registration_email, send_welcome_email
from insigne.models import User

_secure_cookies = config.base_url.startswith("https://")

router = APIRouter()

_TEMPLATES = Jinja2Templates(directory=Path(__file__).parent.parent.parent / "frontend" / "templates")
_TEMPLATES.env.globals["current_user"] = None


def _partial(request: Request, name: str, **ctx):
    return _TEMPLATES.TemplateResponse(request=request, name=f"partials/{name}", context=ctx)


def _page(request: Request, name: str, db: Session, **ctx):
    ctx.setdefault("current_user", _get_current_user(request, db))
    return _TEMPLATES.TemplateResponse(request=request, name=name, context=ctx)


def _get_current_user(request: Request, db: Session) -> User | None:
    token = request.cookies.get("access_token")
    if not token:
        return None
    try:
        user_id = decode_access_token(token)
    except jwt.PyJWTError:
        return None
    return db.get(User, user_id)


# --- Registration ---

@router.get("/register", response_class=HTMLResponse)
async def register_page(request: Request, db: Session = Depends(get_db)):
    return _page(request, "register.html", db)


@router.get("/register/confirm", response_class=HTMLResponse)
async def register_confirm_manual(request: Request, db: Session = Depends(get_db)):
    return _TEMPLATES.TemplateResponse(
        request=request,
        name="register.html",
        context={"current_user": _get_current_user(request, db), "prefill_step2": True, "email": ""},
    )


@router.get("/register/confirm/{code}", response_class=HTMLResponse)
async def register_confirm_link(request: Request, code: str, db: Session = Depends(get_db)):
    current_user = _get_current_user(request, db)
    setup_token = user_svc.confirm_email(db, code)
    if setup_token is None:
        return _TEMPLATES.TemplateResponse(
            request=request,
            name="register.html",
            context={
                "current_user": current_user,
                "prefill_step2": False,
                "link_error": "Deze bevestigingslink is verlopen of ongeldig. Vraag een nieuwe code aan.",
            },
        )
    return _TEMPLATES.TemplateResponse(
        request=request,
        name="register.html",
        context={"current_user": current_user, "prefill_step3": True, "setup_token": setup_token},
    )


@router.post("/register", response_class=HTMLResponse)
async def register(
    request: Request,
    background_tasks: BackgroundTasks,
    email: str = Form(...),
    db: Session = Depends(get_db),
):
    code, token_type, user = user_svc.start_registration(db, email)
    naam = user.name or user.email.split("@")[0]
    if token_type == "email_confirmation":
        background_tasks.add_task(send_registration_email, user.email, naam, code)
    else:
        background_tasks.add_task(send_password_reset_email, user.email, naam, code)
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
                        error="Ongeldige of verlopen code. Probeer het opnieuw.")
    return _partial(request, "register_step3.html", setup_token=setup_token)


@router.post("/register/activate", response_class=HTMLResponse)
async def register_activate(
    request: Request,
    background_tasks: BackgroundTasks,
    setup_token: str = Form(...),
    password: str = Form(...),
    name: str = Form(""),
    db: Session = Depends(get_db),
):
    try:
        user, is_new = user_svc.activate_account(db, setup_token, password, name)
    except user_svc.ActivationError as exc:
        if str(exc) == "expired":
            error = "Deze link is verlopen. Begin opnieuw."
        else:
            error = "Wachtwoord moet minimaal 8 tekens bevatten."
        return _partial(request, "register_step3.html", setup_token=setup_token, error=error)

    if is_new:
        background_tasks.add_task(send_welcome_email, user.email, user.name or user.email.split("@")[0])
    access_token, _ = create_access_token(user.id)
    response = HTMLResponse(content="")
    response.headers["HX-Redirect"] = "/"
    response.set_cookie(
        key="access_token",
        value=access_token,
        httponly=True,
        samesite="lax",
        secure=_secure_cookies,
        max_age=30 * 24 * 3600,
    )
    return response


# --- Profile ---

@router.get("/profile", response_class=HTMLResponse)
async def profile_page(request: Request, db: Session = Depends(get_db)):
    current_user = _get_current_user(request, db)
    if current_user is None:
        return RedirectResponse(url="/login", status_code=303)
    return _page(request, "profile.html", db)


@router.post("/profile", response_class=HTMLResponse)
async def profile_update(
    request: Request,
    name: str = Form(""),
    email: str = Form(...),
    password: str = Form(""),
    db: Session = Depends(get_db),
):
    current_user = _get_current_user(request, db)
    if current_user is None:
        return RedirectResponse(url="/login", status_code=303)
    try:
        user_svc.update_user(
            db,
            current_user,
            name=name or None,
            email=email or None,
            password=password if password else None,
        )
    except ValueError:
        return _page(request, "profile.html", db,
                     error="Wachtwoord moet minimaal 8 tekens bevatten.")
    except IntegrityError:
        db.rollback()
        return _page(request, "profile.html", db,
                     error="Dit e-mailadres is al in gebruik.")
    return _page(request, "profile.html", db, success="Wijzigingen opgeslagen.")


# --- Login ---

@router.get("/login", response_class=HTMLResponse)
async def login_page(request: Request, db: Session = Depends(get_db)):
    return _page(request, "login.html", db)


@router.post("/login", response_class=HTMLResponse)
async def login(
    request: Request,
    email: str = Form(...),
    password: str = Form(...),
    db: Session = Depends(get_db),
):
    user = user_svc.authenticate(db, email, password)
    if user is None:
        return _partial(request, "login_form.html", email=email,
                        error="Ongeldig e-mailadres of wachtwoord.")
    access_token, _ = create_access_token(user.id)
    response = HTMLResponse(content="")
    response.headers["HX-Redirect"] = "/"
    response.set_cookie(
        key="access_token",
        value=access_token,
        httponly=True,
        samesite="lax",
        secure=_secure_cookies,
        max_age=30 * 24 * 3600,
    )
    return response


# --- Logout ---

@router.post("/logout")
async def logout():
    response = RedirectResponse(url="/login", status_code=303)
    response.delete_cookie("access_token")
    return response


# --- Forgot password ---

@router.get("/forgot-password", response_class=HTMLResponse)
async def forgot_password_page(request: Request, db: Session = Depends(get_db)):
    return _page(request, "forgot_password.html", db)


@router.post("/forgot-password", response_class=HTMLResponse)
async def forgot_password(
    request: Request,
    background_tasks: BackgroundTasks,
    email: str = Form(...),
    db: Session = Depends(get_db),
):
    code = user_svc.forgot_password(db, email)
    if code is not None:
        user = db.query(User).filter(User.email == email.strip().lower()).first()
        naam = user.name or user.email.split("@")[0]
        background_tasks.add_task(send_password_reset_email, user.email, naam, code)
    return _partial(request, "forgot_password_step2.html", email=email.strip().lower())


@router.get("/forgot-password/confirm", response_class=HTMLResponse)
async def forgot_password_confirm_manual(request: Request, db: Session = Depends(get_db)):
    return _page(request, "forgot_password.html", db, prefill_step2=True, email="")


@router.get("/forgot-password/confirm/{code}", response_class=HTMLResponse)
async def forgot_password_confirm_link(request: Request, code: str, db: Session = Depends(get_db)):
    current_user = _get_current_user(request, db)
    setup_token = user_svc.confirm_email(db, code)
    if setup_token is None:
        return _TEMPLATES.TemplateResponse(
            request=request,
            name="forgot_password.html",
            context={
                "current_user": current_user,
                "link_error": "Deze herstelcode is verlopen of ongeldig. Vraag een nieuwe aan.",
            },
        )
    return _TEMPLATES.TemplateResponse(
        request=request,
        name="forgot_password.html",
        context={"current_user": current_user, "prefill_step3": True, "setup_token": setup_token},
    )


@router.post("/forgot-password/confirm", response_class=HTMLResponse)
async def forgot_password_confirm(
    request: Request,
    email: str = Form(...),
    code: str = Form(...),
    db: Session = Depends(get_db),
):
    setup_token = user_svc.confirm_email(db, code)
    if setup_token is None:
        return _partial(request, "forgot_password_step2.html", email=email,
                        error="Ongeldige of verlopen code. Probeer het opnieuw.")
    return _partial(request, "forgot_password_step3.html", setup_token=setup_token)


@router.post("/forgot-password/reset", response_class=HTMLResponse)
async def forgot_password_reset(
    request: Request,
    setup_token: str = Form(...),
    password: str = Form(...),
    db: Session = Depends(get_db),
):
    try:
        user, _ = user_svc.activate_account(db, setup_token, password)
    except user_svc.ActivationError as exc:
        if str(exc) == "expired":
            error = "Deze link is verlopen. Begin opnieuw."
        else:
            error = "Wachtwoord moet minimaal 8 tekens bevatten."
        return _partial(request, "forgot_password_step3.html", setup_token=setup_token, error=error)

    access_token, _ = create_access_token(user.id)
    response = HTMLResponse(content="")
    response.headers["HX-Redirect"] = "/"
    response.set_cookie(
        key="access_token",
        value=access_token,
        httponly=True,
        samesite="lax",
        secure=_secure_cookies,
        max_age=30 * 24 * 3600,
    )
    return response

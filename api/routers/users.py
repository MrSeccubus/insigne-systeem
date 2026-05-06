from pathlib import Path

import yaml
import jwt
from fastapi import APIRouter, BackgroundTasks, Depends, File, Form, Request, UploadFile
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from insigne import progress_export as export_svc
from insigne import users as user_svc
from insigne.auth import create_access_token, decode_access_token
from insigne.config import config
from insigne.database import get_db
from insigne.email import (
    send_email_change_confirm_email,
    send_email_change_revert_email,
    send_password_reset_email,
    send_registration_email,
    send_welcome_email,
)
from insigne.models import User
from templates import templates as _TEMPLATES

_secure_cookies = config.base_url.startswith("https://")
_DATA_DIR = Path(__file__).parent.parent / "data"

router = APIRouter()


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
    pending = user_svc.pending_email_change(db, current_user.id)
    return _page(request, "profile.html", db, pending_email_change=pending)


@router.post("/profile", response_class=HTMLResponse)
async def profile_update(
    request: Request,
    background_tasks: BackgroundTasks,
    name: str = Form(""),
    email: str = Form(...),
    password: str = Form(""),
    db: Session = Depends(get_db),
):
    current_user = _get_current_user(request, db)
    if current_user is None:
        return RedirectResponse(url="/login", status_code=303)

    email_changing = email and email.strip().lower() != (current_user.email or "").lower()

    try:
        user_svc.update_user(
            db,
            current_user,
            name=name or None,
            email=None,  # email change handled separately
            password=password if password else None,
        )
    except ValueError:
        return _page(request, "profile.html", db,
                     error="Wachtwoord moet minimaal 8 tekens bevatten.")

    if email_changing:
        try:
            req = user_svc.request_email_change(db, current_user, email)
        except user_svc.EmailChangeError as exc:
            if str(exc) == "email_taken":
                return _page(request, "profile.html", db,
                             error="Dit e-mailadres is al in gebruik.")
            return _page(request, "profile.html", db,
                         error="Ongeldige invoer.")
        naam = current_user.name or (current_user.email or "").split("@")[0]
        background_tasks.add_task(
            send_email_change_confirm_email,
            req.new_email, naam, req.new_email, req.confirm_token,
        )
        background_tasks.add_task(
            send_email_change_revert_email,
            req.old_email, naam, req.old_email, req.new_email, req.revert_token,
        )
        pending = user_svc.pending_email_change(db, current_user.id)
        return _page(request, "profile.html", db,
                     success="Wijzigingen opgeslagen.",
                     pending_email_change=pending)

    return _page(request, "profile.html", db, success="Wijzigingen opgeslagen.")


# --- Email change confirm / revert ---

@router.get("/profile/email-change/confirm/{token}", response_class=HTMLResponse)
async def email_change_confirm(request: Request, token: str, db: Session = Depends(get_db)):
    req = user_svc.confirm_email_change(db, token)
    if req is None:
        current_user = _get_current_user(request, db)
        return _TEMPLATES.TemplateResponse(
            request=request,
            name="email_change_result.html",
            context={"current_user": current_user, "result": "expired"},
        )
    current_user = _get_current_user(request, db)
    return _TEMPLATES.TemplateResponse(
        request=request,
        name="email_change_result.html",
        context={"current_user": current_user, "result": "confirmed", "new_email": req.new_email},
    )


@router.get("/profile/email-change/revert/{token}", response_class=HTMLResponse)
async def email_change_revert_page(request: Request, token: str, db: Session = Depends(get_db)):
    current_user = _get_current_user(request, db)
    req = user_svc.get_revert_request(db, token)
    if req is None:
        return _TEMPLATES.TemplateResponse(
            request=request,
            name="email_change_result.html",
            context={"current_user": current_user, "result": "expired"},
        )
    return _TEMPLATES.TemplateResponse(
        request=request,
        name="email_change_revert_confirm.html",
        context={
            "current_user": current_user,
            "token": token,
            "old_email": req.old_email,
            "new_email": req.new_email,
        },
    )


@router.post("/profile/email-change/revert/{token}", response_class=HTMLResponse)
async def email_change_revert(request: Request, token: str, db: Session = Depends(get_db)):
    req = user_svc.revert_email_change(db, token)
    current_user = _get_current_user(request, db)
    if req is None:
        return _TEMPLATES.TemplateResponse(
            request=request,
            name="email_change_result.html",
            context={"current_user": current_user, "result": "expired"},
        )
    return _TEMPLATES.TemplateResponse(
        request=request,
        name="email_change_result.html",
        context={"current_user": current_user, "result": "reverted", "old_email": req.old_email},
    )


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


# --- Export / Import ---

@router.get("/export", response_class=HTMLResponse)
async def export_page(request: Request, db: Session = Depends(get_db)):
    current_user = _get_current_user(request, db)
    if not current_user:
        return RedirectResponse("/login", status_code=303)
    return _page(request, "export.html", db, import_result=None)


@router.get("/export/download")
def export_download(request: Request, format: str = "yaml", db: Session = Depends(get_db)):
    from fastapi.responses import StreamingResponse
    current_user = _get_current_user(request, db)
    if not current_user:
        return RedirectResponse("/login", status_code=303)
    if format not in ("yaml", "pdf"):
        format = "yaml"
    data = export_svc.export_data(db, current_user.id)
    name = (current_user.name or "export").replace(" ", "_")
    if format == "pdf":
        yaml_str = export_svc.to_yaml(data)
        pdf_bytes = export_svc.to_pdf(data, data_dir=_DATA_DIR)
        content = export_svc.embed_yaml_in_pdf(pdf_bytes, yaml_str)
        return StreamingResponse(
            iter([content]),
            media_type="application/pdf",
            headers={"Content-Disposition": f'attachment; filename="{name}_voortgang.pdf"'},
        )
    yaml_str = export_svc.to_yaml(data)
    return StreamingResponse(
        iter([yaml_str.encode()]),
        media_type="application/x-yaml",
        headers={"Content-Disposition": f'attachment; filename="{name}_voortgang.yml"'},
    )


@router.post("/export/import", response_class=HTMLResponse)
async def import_progress_html(
    request: Request,
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
):
    current_user = _get_current_user(request, db)
    if not current_user:
        return RedirectResponse("/login", status_code=303)

    raw = await file.read()
    filename = file.filename or ""
    error = None
    count = 0

    try:
        if filename.lower().endswith(".pdf"):
            yaml_str = export_svc.extract_yaml_from_pdf(raw)
            if not yaml_str:
                error = "Geen voortgangsgegevens gevonden in de PDF."
            else:
                data = yaml.safe_load(yaml_str)
        elif filename.lower().endswith((".yml", ".yaml")):
            data = yaml.safe_load(raw.decode())
        else:
            error = "Upload een .yml- of .pdf-bestand."

        if not error:
            if not isinstance(data, dict) or data.get("version") != 1:
                error = "Onbekend exportformaat."
            else:
                count = export_svc.import_progress(db, current_user.id, data)
    except Exception:
        error = "Het bestand kon niet worden verwerkt."

    return _page(request, "export.html", db,
                 import_result={"error": error, "count": count} if error is None else {"error": error, "count": 0})

from pathlib import Path

import markdown as _markdown
from fastapi import APIRouter, BackgroundTasks, Depends, Form, Request
from fastapi.responses import HTMLResponse
from sqlalchemy.orm import Session

import captcha
from insigne.config import config
from insigne.database import get_db
from insigne.email import send_contact_form_email
from ratelimit import contact_rate_limit
from routers.users import _get_current_user
from templates import templates as _TEMPLATES

_TEMPLATES_DIR = Path(__file__).parent.parent.parent / "frontend" / "templates"
_CUSTOM_POLICY = _TEMPLATES_DIR / "privacy_policy_custom.md"
_DEFAULT_POLICY = _TEMPLATES_DIR / "privacy_policy_default.md"

router = APIRouter()

def _render(request, current_user, *, success=False, error=None,
            prefill_subject="", prefill_body="", prefill_email=""):
    ctx = {"current_user": current_user, "success": success,
           "error": error, "prefill_subject": prefill_subject,
           "prefill_body": prefill_body, "prefill_email": prefill_email,
           # The template shows the ALTCHA widget for anonymous users only when
           # the captcha is enabled (see contact.html).
           "captcha_enabled": (not current_user) and captcha.is_enabled()}
    return _TEMPLATES.TemplateResponse(request=request, name="contact.html", context=ctx)


@router.get("/contact", response_class=HTMLResponse)
async def contact_page(request: Request, db: Session = Depends(get_db)):
    current_user = _get_current_user(request, db)
    return _render(request, current_user)


@router.post("/contact", response_class=HTMLResponse)
@contact_rate_limit
async def contact_submit(
    request: Request,
    background_tasks: BackgroundTasks,
    subject: str = Form(...),
    body: str = Form(...),
    sender_email: str = Form(""),
    altcha: str = Form(""),
    db: Session = Depends(get_db),
):
    current_user = _get_current_user(request, db)

    if current_user:
        email = current_user.email
    else:
        email = sender_email.strip()
        if captcha.is_enabled() and not captcha.verify(altcha):
            return _render(request, current_user,
                           error="De verificatie is mislukt. Laad de pagina opnieuw en probeer het nog eens.",
                           prefill_subject=subject, prefill_body=body, prefill_email=email)

    if config.admins:
        for admin_email in config.admins:
            background_tasks.add_task(send_contact_form_email, admin_email, email, subject, body)

    return _render(request, current_user, success=True)


@router.get("/privacy", response_class=HTMLResponse)
async def privacy_page(request: Request, db: Session = Depends(get_db)):
    current_user = _get_current_user(request, db)
    is_default = not _CUSTOM_POLICY.exists()
    md_file = _DEFAULT_POLICY if is_default else _CUSTOM_POLICY
    content = _markdown.markdown(md_file.read_text(encoding="utf-8"))
    is_admin = bool(current_user and current_user.is_admin)
    return _TEMPLATES.TemplateResponse(
        request=request,
        name="privacy_policy.html",
        context={
            "current_user": current_user,
            "is_admin": is_admin,
            "is_default": is_default,
            "content": content,
        },
    )

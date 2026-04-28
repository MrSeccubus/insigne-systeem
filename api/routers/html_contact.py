import hashlib
import hmac
import random
import time
from pathlib import Path

import markdown as _markdown
from fastapi import APIRouter, BackgroundTasks, Depends, Form, Request
from fastapi.responses import HTMLResponse
from sqlalchemy.orm import Session

from insigne.config import config
from insigne.database import get_db
from insigne.email import send_contact_form_email
from routers.users import _get_current_user
from templates import templates as _TEMPLATES

_TEMPLATES_DIR = Path(__file__).parent.parent.parent / "frontend" / "templates"
_CUSTOM_POLICY = _TEMPLATES_DIR / "privacy_policy_custom.md"
_DEFAULT_POLICY = _TEMPLATES_DIR / "privacy_policy_default.md"

router = APIRouter()

_BUCKET_SECONDS = 600  # 10-minute validity window


def _captcha_secret() -> bytes:
    """Derive a captcha-specific key from the JWT secret so they are independent."""
    return hmac.new(
        config.jwt_secret_key.encode(),
        b"captcha-secret",
        hashlib.sha256,
    ).digest()


def _current_bucket() -> int:
    return int(time.time()) // _BUCKET_SECONDS


def _make_token(answer: int, bucket: int) -> str:
    mac = hmac.new(
        _captcha_secret(),
        f"{answer}:{bucket}".encode(),
        hashlib.sha256,
    ).hexdigest()
    return f"{bucket}:{mac}"


def _verify_token(answer: int, token: str) -> bool:
    """Accept tokens from the current or previous bucket (handles boundary edge-cases)."""
    try:
        bucket_str, mac = token.split(":", 1)
        bucket = int(bucket_str)
    except (ValueError, AttributeError):
        return False
    current = _current_bucket()
    if bucket not in (current, current - 1):
        return False
    expected = hmac.new(
        _captcha_secret(),
        f"{answer}:{bucket}".encode(),
        hashlib.sha256,
    ).hexdigest()
    return hmac.compare_digest(expected, mac)


def _new_captcha() -> tuple[int, int, str]:
    a = random.randint(1, 9)
    b = random.randint(1, 9)
    return a, b, _make_token(a + b, _current_bucket())


def _render(request, current_user, *, success=False, error=None,
            prefill_subject="", prefill_body="", prefill_email=""):
    ctx = {"current_user": current_user, "success": success,
           "error": error, "prefill_subject": prefill_subject,
           "prefill_body": prefill_body, "prefill_email": prefill_email}
    if not current_user:
        a, b, token = _new_captcha()
        ctx.update(captcha_a=a, captcha_b=b, captcha_token=token)
    return _TEMPLATES.TemplateResponse(request=request, name="contact.html", context=ctx)


@router.get("/contact", response_class=HTMLResponse)
async def contact_page(request: Request, db: Session = Depends(get_db)):
    current_user = _get_current_user(request, db)
    return _render(request, current_user)


@router.post("/contact", response_class=HTMLResponse)
async def contact_submit(
    request: Request,
    background_tasks: BackgroundTasks,
    subject: str = Form(...),
    body: str = Form(...),
    sender_email: str = Form(""),
    captcha_token: str = Form(""),
    captcha_answer: str = Form(""),
    db: Session = Depends(get_db),
):
    current_user = _get_current_user(request, db)

    if current_user:
        email = current_user.email
    else:
        email = sender_email.strip()
        try:
            answer_int = int(captcha_answer.strip())
        except ValueError:
            answer_int = -1
        if not _verify_token(answer_int, captcha_token):
            return _render(request, current_user, error="Onjuist antwoord op de rekensom. Probeer het opnieuw.",
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

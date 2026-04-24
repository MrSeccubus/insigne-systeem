import hashlib
import hmac
import random

from fastapi import APIRouter, BackgroundTasks, Depends, Form, Request
from fastapi.responses import HTMLResponse
from sqlalchemy.orm import Session

from insigne.config import config
from insigne.database import get_db
from insigne.email import send_contact_form_email
from routers.users import _get_current_user
from templates import templates as _TEMPLATES

router = APIRouter()


def _captcha_token(answer: int) -> str:
    return hmac.new(
        config.jwt_secret_key.encode(),
        str(answer).encode(),
        hashlib.sha256,
    ).hexdigest()


def _new_captcha() -> tuple[int, int, str]:
    a = random.randint(1, 9)
    b = random.randint(1, 9)
    return a, b, _captcha_token(a + b)


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
        if not hmac.compare_digest(_captcha_token(answer_int), captcha_token):
            return _render(request, current_user, error="Onjuist antwoord op de rekensom. Probeer het opnieuw.",
                           prefill_subject=subject, prefill_body=body, prefill_email=email)

    if config.admins:
        for admin_email in config.admins:
            background_tasks.add_task(send_contact_form_email, admin_email, email, subject, body)

    return _render(request, current_user, success=True)

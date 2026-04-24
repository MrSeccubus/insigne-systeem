from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from sqlalchemy.orm import Session

from insigne.config import config
from insigne.database import get_db
from insigne.email import send_contact_form_email
from routers.html_contact import _new_captcha, _verify_token
from deps import get_current_user_or_none
from schemas import ContactCaptchaResponse, ContactRequest

router = APIRouter(prefix="/contact", tags=["contact"])


@router.get("/captcha", response_model=ContactCaptchaResponse)
async def get_captcha():
    a, b, token = _new_captcha()
    return ContactCaptchaResponse(token=token, a=a, b=b)


@router.post("", status_code=202)
async def send_contact(
    body: ContactRequest,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user_or_none),
):
    if current_user:
        email = current_user.email
    else:
        if not body.sender_email:
            raise HTTPException(status_code=422, detail="sender_email is required for anonymous requests.")
        if body.captcha_token is None or body.captcha_answer is None:
            raise HTTPException(status_code=422, detail="captcha_token and captcha_answer are required for anonymous requests.")
        if not _verify_token(body.captcha_answer, body.captcha_token):
            raise HTTPException(status_code=400, detail="Invalid or expired captcha.")
        email = str(body.sender_email)

    if config.admins:
        for admin_email in config.admins:
            background_tasks.add_task(send_contact_form_email, admin_email, email, body.subject, body.body)

    return {"detail": "Message sent."}

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from sqlalchemy.orm import Session

from insigne import users as user_svc
from insigne.auth import create_access_token
from insigne.database import get_db
from insigne.email import send_password_reset_email
from insigne.models import User

from schemas import ForgotPasswordRequest, LoginRequest, TokenResponse

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/token", response_model=TokenResponse)
async def login(body: LoginRequest, db: Session = Depends(get_db)):
    user = user_svc.authenticate(db, body.email, body.password)
    if user is None:
        raise HTTPException(status_code=401, detail="Invalid credentials.")
    access_token, expires_at = create_access_token(user.id)
    return TokenResponse(access_token=access_token, expires_at=expires_at)


@router.post("/forgot-password", status_code=202)
async def forgot_password(body: ForgotPasswordRequest, background_tasks: BackgroundTasks, db: Session = Depends(get_db)):
    code = user_svc.forgot_password(db, body.email)
    if code is not None:
        email = body.email.strip().lower()
        user = db.query(User).filter_by(email=email).first()
        naam = user.name or email.split("@")[0]
        background_tasks.add_task(send_password_reset_email, email, naam, code)
    return {"detail": "If this email is registered, a reset code has been sent."}

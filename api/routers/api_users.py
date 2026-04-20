from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Response
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from insigne import users as user_svc
from insigne.auth import create_access_token
from insigne.database import get_db
from insigne.email import send_password_reset_email, send_registration_email, send_welcome_email
from insigne.models import User

from deps import get_current_user
from schemas import (
    ActivateRequest,
    ConfirmRequest,
    RegisterRequest,
    SetupTokenResponse,
    TokenResponse,
    UpdateUserRequest,
    UserResponse,
)

router = APIRouter(prefix="/users", tags=["users"])


def _user_response(user: User) -> UserResponse:
    return UserResponse(id=user.id, email=user.email, name=user.name, created_at=user.created_at)


@router.post("", status_code=202)
async def register(body: RegisterRequest, background_tasks: BackgroundTasks, db: Session = Depends(get_db)):
    code, token_type, user = user_svc.start_registration(db, body.email)
    naam = user.name or user.email.split("@")[0]
    if token_type == "email_confirmation":
        background_tasks.add_task(send_registration_email, user.email, naam, code)
    else:
        background_tasks.add_task(send_password_reset_email, user.email, naam, code)
    return {"detail": "Confirmation email sent."}


@router.post("/confirm", response_model=SetupTokenResponse)
async def confirm(body: ConfirmRequest, db: Session = Depends(get_db)):
    setup_token = user_svc.confirm_email(db, body.code)
    if setup_token is None:
        raise HTTPException(status_code=400, detail="Invalid or expired code.")
    return SetupTokenResponse(setup_token=setup_token)


@router.post("/activate", response_model=TokenResponse)
async def activate(body: ActivateRequest, background_tasks: BackgroundTasks, db: Session = Depends(get_db)):
    try:
        user, is_new = user_svc.activate_account(db, body.setup_token, body.password, body.name)
    except user_svc.ActivationError as exc:
        detail = (
            "Setup token is invalid or expired."
            if str(exc) == "expired"
            else "Password must be at least 8 characters."
        )
        raise HTTPException(status_code=400, detail=detail)
    if is_new:
        background_tasks.add_task(send_welcome_email, user.email, user.name or user.email.split("@")[0])
    access_token, expires_at = create_access_token(user.id)
    return TokenResponse(access_token=access_token, expires_at=expires_at)


@router.get("/me", response_model=UserResponse)
async def get_me(current_user: User = Depends(get_current_user)):
    return _user_response(current_user)


@router.put("/me", response_model=UserResponse)
async def update_me(
    body: UpdateUserRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    try:
        user = user_svc.update_user(
            db, current_user, name=body.name, email=body.email, password=body.password
        )
    except ValueError:
        raise HTTPException(status_code=400, detail="Password must be at least 8 characters.")
    except IntegrityError:
        raise HTTPException(status_code=409, detail="Email address already in use.")
    return _user_response(user)


@router.delete("/me", status_code=204)
async def delete_me(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    user_svc.delete_user(db, current_user)
    return Response(status_code=204)

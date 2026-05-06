from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Response, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from insigne import groups as groups_svc
from insigne import users as user_svc
from insigne.auth import create_access_token
from insigne.database import get_db
from insigne.email import (
    send_account_deleted_email,
    send_email_change_confirm_email,
    send_email_change_revert_email,
    send_password_reset_email,
    send_registration_email,
    send_welcome_email,
)
from insigne.models import User

from deps import get_current_user
from schemas import (
    ActivateRequest,
    ActiveMembershipsResponse,
    ConfirmRequest,
    EmailChangeTokenRequest,
    MembershipRequestResponse,
    PendingEmailChangeResponse,
    RegisterRequest,
    SetupTokenResponse,
    TokenResponse,
    UpdateUserRequest,
    UserGroupMembershipResponse,
    UserResponse,
    UserSpeltakMembershipResponse,
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


@router.put("/me", status_code=200)
async def update_me(
    body: UpdateUserRequest,
    background_tasks: BackgroundTasks,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    email_changing = body.email and str(body.email).lower() != (current_user.email or "").lower()

    try:
        user_svc.update_user(
            db, current_user,
            name=body.name,
            email=None,  # email change handled separately
            password=body.password,
        )
    except ValueError:
        raise HTTPException(status_code=400, detail="Password must be at least 8 characters.")

    if email_changing:
        try:
            req = user_svc.request_email_change(db, current_user, str(body.email))
        except user_svc.EmailChangeError as exc:
            if str(exc) == "email_taken":
                raise HTTPException(status_code=409, detail="Email address already in use.")
            raise HTTPException(status_code=400, detail="Invalid input.")
        naam = current_user.name or (current_user.email or "").split("@")[0]
        background_tasks.add_task(
            send_email_change_confirm_email,
            req.new_email, naam, req.new_email, req.confirm_token,
        )
        background_tasks.add_task(
            send_email_change_revert_email,
            req.old_email, naam, req.old_email, req.new_email, req.revert_token,
        )
        return {"detail": f"Email change confirmation sent to {req.new_email}."}

    return _user_response(current_user)


@router.get("/me/email-change", response_model=PendingEmailChangeResponse | None)
async def get_pending_email_change(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    req = user_svc.pending_email_change(db, current_user.id)
    if req is None:
        return None
    return PendingEmailChangeResponse(new_email=req.new_email, expires_at=req.expires_at)


@router.post("/email-change/confirm")
async def confirm_email_change(body: EmailChangeTokenRequest, db: Session = Depends(get_db)):
    req = user_svc.confirm_email_change(db, body.token)
    if req is None:
        raise HTTPException(status_code=400, detail="Invalid or expired token.")
    return {"detail": "Email address updated successfully."}


@router.post("/email-change/revert")
async def revert_email_change(body: EmailChangeTokenRequest, db: Session = Depends(get_db)):
    req = user_svc.revert_email_change(db, body.token)
    if req is None:
        raise HTTPException(status_code=400, detail="Invalid or expired token.")
    return {"detail": "Email address reverted successfully."}


@router.delete("/me", status_code=204)
async def delete_me(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if current_user.email:
        send_account_deleted_email(current_user.email, current_user.name or current_user.email)
    user_svc.delete_user(db, current_user)
    return Response(status_code=204)


@router.get("/me/memberships", response_model=ActiveMembershipsResponse)
def get_my_memberships(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    gm, sm = groups_svc.list_active_memberships_for_user(db, current_user.id)
    return ActiveMembershipsResponse(
        group_memberships=[
            UserGroupMembershipResponse(
                group_id=m.group_id, role=m.role,
                approved=m.approved, withdrawn=m.withdrawn,
            ) for m in gm
        ],
        speltak_memberships=[
            UserSpeltakMembershipResponse(
                speltak_id=m.speltak_id, group_id=m.speltak.group_id,
                role=m.role, approved=m.approved, withdrawn=m.withdrawn,
            ) for m in sm
        ],
    )


@router.get("/me/requests", response_model=list[MembershipRequestResponse])
def get_my_requests(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    reqs = groups_svc.list_my_membership_requests(db, current_user.id)
    return [
        MembershipRequestResponse(
            id=r.id, user_id=r.user_id, group_id=r.group_id,
            speltak_id=r.speltak_id, status=r.status,
            reviewed_by_id=r.reviewed_by_id, created_at=r.created_at,
        ) for r in reqs
    ]


@router.delete("/me/requests", status_code=status.HTTP_204_NO_CONTENT)
def cancel_all_my_requests(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    groups_svc.cancel_all_membership_requests(db, user_id=current_user.id)
    return Response(status_code=204)


@router.delete("/me/requests/{req_id}", status_code=status.HTTP_204_NO_CONTENT)
def cancel_my_request(
    req_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    groups_svc.cancel_membership_request(db, request_id=req_id, user_id=current_user.id)
    return Response(status_code=204)

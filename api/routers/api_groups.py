from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from insigne import groups as groups_svc
from insigne.config import config
from insigne.database import get_db
from insigne.models import User
from deps import get_current_user
from schemas import (
    AttachEmailRequest,
    CreateEmaillessScoutRequest,
    CreateGroupRequest,
    CreateMembershipRequestRequest,
    CreateSpeltakRequest,
    GroupMembershipResponse,
    GroupResponse,
    InvitationListResponse,
    GroupInvitationResponse,
    MembershipRequestResponse,
    SpeltakInvitationResponse,
    SetMemberRoleRequest,
    SetSpeltakRoleRequest,
    SpeltakMembershipResponse,
    SpeltakResponse,
    TransferScoutRequest,
    UpdateGroupRequest,
    UpdateSpeltakRequest,
)


router = APIRouter(prefix="/groups", tags=["groups"])


def _group_response(g) -> GroupResponse:
    return GroupResponse(id=g.id, name=g.name, slug=g.slug,
                         created_at=g.created_at.isoformat())


def _speltak_response(s) -> SpeltakResponse:
    return SpeltakResponse(id=s.id, group_id=s.group_id, name=s.name, slug=s.slug,
                           peer_signoff=s.peer_signoff)


def _group_membership_response(m) -> GroupMembershipResponse:
    return GroupMembershipResponse(
        user_id=m.user_id, role=m.role,
        approved=m.approved, withdrawn=m.withdrawn,
        invited_by_id=m.invited_by_id,
    )


def _speltak_membership_response(m) -> SpeltakMembershipResponse:
    return SpeltakMembershipResponse(
        user_id=m.user_id, role=m.role,
        approved=m.approved, withdrawn=m.withdrawn,
        invited_by_id=m.invited_by_id,
    )


# ── Groups ────────────────────────────────────────────────────────────────────

@router.get("", response_model=list[GroupResponse])
def list_groups(db: Session = Depends(get_db)):
    return [_group_response(g) for g in groups_svc.list_groups(db)]


@router.post("", response_model=GroupResponse, status_code=status.HTTP_201_CREATED)
def create_group(
    body: CreateGroupRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    if not current_user.is_admin and not config.allow_any_user_to_create_groups:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Group creation is restricted to admins.")
    if groups_svc.get_group_by_slug(db, body.slug):
        raise HTTPException(status.HTTP_409_CONFLICT, "Slug already in use.")
    group = groups_svc.create_group(db, name=body.name, slug=body.slug,
                                    created_by_id=current_user.id)
    return _group_response(group)


@router.get("/{group_id}", response_model=GroupResponse)
def get_group(group_id: str, db: Session = Depends(get_db)):
    g = groups_svc.get_group(db, group_id)
    if not g:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Group not found.")
    return _group_response(g)


@router.put("/{group_id}", response_model=GroupResponse)
def update_group(
    group_id: str,
    body: UpdateGroupRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    g = groups_svc.get_group(db, group_id)
    if not g:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Group not found.")
    if not groups_svc.can_manage_group(current_user, db, group_id):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Not allowed.")
    existing = groups_svc.get_group_by_slug(db, body.slug)
    if existing and existing.id != group_id:
        raise HTTPException(status.HTTP_409_CONFLICT, "Slug already in use.")
    return _group_response(groups_svc.update_group(db, g, name=body.name, slug=body.slug))


@router.delete("/{group_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_group(
    group_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    g = groups_svc.get_group(db, group_id)
    if not g:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Group not found.")
    if not groups_svc.can_manage_group(current_user, db, group_id):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Not allowed.")
    groups_svc.delete_group(db, g)


# ── Group members ─────────────────────────────────────────────────────────────

@router.get("/{group_id}/members", response_model=list[GroupMembershipResponse])
def list_group_members(
    group_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    if not groups_svc.get_group(db, group_id):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Group not found.")
    if not groups_svc.can_manage_group(current_user, db, group_id):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Not allowed.")
    return [_group_membership_response(m)
            for m in groups_svc.list_group_members(db, group_id)]


@router.get("/{group_id}/members/pending", response_model=list[GroupMembershipResponse])
def list_pending_group_members(
    group_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    if not groups_svc.get_group(db, group_id):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Group not found.")
    if not groups_svc.can_manage_group(current_user, db, group_id):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Not allowed.")
    return [_group_membership_response(m)
            for m in groups_svc.list_pending_group_members(db, group_id)]


@router.post("/{group_id}/members", status_code=status.HTTP_204_NO_CONTENT)
def set_group_member_role(
    group_id: str,
    body: SetMemberRoleRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    if not groups_svc.get_group(db, group_id):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Group not found.")
    if not groups_svc.can_manage_group(current_user, db, group_id):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Not allowed.")
    groups_svc.set_group_role(db, user_id=body.user_id, group_id=group_id, role=body.role)


@router.delete("/{group_id}/members/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
def remove_group_member(
    group_id: str,
    user_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    if not groups_svc.get_group(db, group_id):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Group not found.")
    if not groups_svc.can_manage_group(current_user, db, group_id):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Not allowed.")
    groups_svc.remove_group_member(db, user_id=user_id, group_id=group_id)


@router.post("/{group_id}/members/{user_id}/withdraw", status_code=status.HTTP_204_NO_CONTENT)
def withdraw_group_invite(
    group_id: str,
    user_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    if not groups_svc.get_group(db, group_id):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Group not found.")
    if not groups_svc.can_manage_group(current_user, db, group_id):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Not allowed.")
    groups_svc.withdraw_group_invite(db, user_id=user_id, group_id=group_id)


@router.post("/{group_id}/members/{user_id}/dismiss", status_code=status.HTTP_204_NO_CONTENT)
def dismiss_group_invite(
    group_id: str,
    user_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    if not groups_svc.get_group(db, group_id):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Group not found.")
    if current_user.id != user_id:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Not allowed.")
    groups_svc.dismiss_group_invite(db, user_id=user_id, group_id=group_id)


@router.post("/{group_id}/members/{user_id}/accept", status_code=status.HTTP_204_NO_CONTENT)
def accept_group_invite(
    group_id: str,
    user_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    if not groups_svc.get_group(db, group_id):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Group not found.")
    if current_user.id != user_id:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Not allowed.")
    groups_svc.accept_group_invite(db, user_id=user_id, group_id=group_id)


@router.post("/{group_id}/members/{user_id}/deny", status_code=status.HTTP_204_NO_CONTENT)
def deny_group_invite(
    group_id: str,
    user_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    if not groups_svc.get_group(db, group_id):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Group not found.")
    if current_user.id != user_id:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Not allowed.")
    groups_svc.deny_group_invite(db, user_id=user_id, group_id=group_id)


# ── Speltakken ────────────────────────────────────────────────────────────────

@router.post("/{group_id}/speltakken", response_model=SpeltakResponse,
             status_code=status.HTTP_201_CREATED)
def create_speltak(
    group_id: str,
    body: CreateSpeltakRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    if not groups_svc.get_group(db, group_id):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Group not found.")
    if not groups_svc.can_manage_group(current_user, db, group_id):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Not allowed.")
    if groups_svc.get_speltak_by_slug(db, group_id, body.slug):
        raise HTTPException(status.HTTP_409_CONFLICT, "Slug already in use.")
    s = groups_svc.create_speltak(db, group_id=group_id, name=body.name, slug=body.slug,
                                  peer_signoff=body.peer_signoff)
    return _speltak_response(s)


@router.put("/{group_id}/speltakken/{speltak_id}", response_model=SpeltakResponse)
def update_speltak(
    group_id: str,
    speltak_id: str,
    body: UpdateSpeltakRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    s = groups_svc.get_speltak(db, speltak_id)
    if not s or s.group_id != group_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Speltak not found.")
    if not groups_svc.can_manage_group(current_user, db, group_id):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Not allowed.")
    existing = groups_svc.get_speltak_by_slug(db, group_id, body.slug)
    if existing and existing.id != speltak_id:
        raise HTTPException(status.HTTP_409_CONFLICT, "Slug already in use.")
    return _speltak_response(groups_svc.update_speltak(db, s, name=body.name, slug=body.slug,
                                                       peer_signoff=body.peer_signoff))


@router.delete("/{group_id}/speltakken/{speltak_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_speltak(
    group_id: str,
    speltak_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    s = groups_svc.get_speltak(db, speltak_id)
    if not s or s.group_id != group_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Speltak not found.")
    if not groups_svc.can_manage_group(current_user, db, group_id):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Not allowed.")
    groups_svc.delete_speltak(db, s)


# ── Speltak members ───────────────────────────────────────────────────────────

@router.get("/{group_id}/speltakken/{speltak_id}/members",
            response_model=list[SpeltakMembershipResponse])
def list_speltak_members(
    group_id: str,
    speltak_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    s = groups_svc.get_speltak(db, speltak_id)
    if not s or s.group_id != group_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Speltak not found.")
    if not groups_svc.can_manage_speltak(current_user, db, speltak_id):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Not allowed.")
    return [_speltak_membership_response(m)
            for m in groups_svc.list_speltak_members(db, speltak_id)]


@router.get("/{group_id}/speltakken/{speltak_id}/members/pending",
            response_model=list[SpeltakMembershipResponse])
def list_pending_speltak_members(
    group_id: str,
    speltak_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    s = groups_svc.get_speltak(db, speltak_id)
    if not s or s.group_id != group_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Speltak not found.")
    if not groups_svc.can_manage_speltak(current_user, db, speltak_id):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Not allowed.")
    return [_speltak_membership_response(m)
            for m in groups_svc.list_pending_speltak_members(db, speltak_id)]


@router.post("/{group_id}/speltakken/{speltak_id}/members",
             status_code=status.HTTP_204_NO_CONTENT)
def set_speltak_member_role(
    group_id: str,
    speltak_id: str,
    body: SetSpeltakRoleRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    s = groups_svc.get_speltak(db, speltak_id)
    if not s or s.group_id != group_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Speltak not found.")
    if not groups_svc.can_manage_speltak(current_user, db, speltak_id):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Not allowed.")
    groups_svc.set_speltak_role(db, user_id=body.user_id, speltak_id=speltak_id, role=body.role)


@router.delete("/{group_id}/speltakken/{speltak_id}/members/{user_id}",
               status_code=status.HTTP_204_NO_CONTENT)
def remove_speltak_member(
    group_id: str,
    speltak_id: str,
    user_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    s = groups_svc.get_speltak(db, speltak_id)
    if not s or s.group_id != group_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Speltak not found.")
    if not groups_svc.can_manage_speltak(current_user, db, speltak_id):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Not allowed.")
    groups_svc.remove_speltak_member(db, user_id=user_id, speltak_id=speltak_id)


@router.post("/{group_id}/speltakken/{speltak_id}/members/{user_id}/transfer",
             status_code=status.HTTP_204_NO_CONTENT)
def transfer_scout(
    group_id: str,
    speltak_id: str,
    user_id: str,
    body: TransferScoutRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    s = groups_svc.get_speltak(db, speltak_id)
    if not s or s.group_id != group_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Speltak not found.")
    if not groups_svc.can_manage_speltak(current_user, db, speltak_id):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Not allowed.")
    to_speltak = groups_svc.get_speltak(db, body.to_speltak_id)
    if not to_speltak or to_speltak.group_id != group_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Destination speltak not found.")
    groups_svc.transfer_scout(db, user_id=user_id,
                              from_speltak_id=speltak_id, to_speltak_id=body.to_speltak_id)


@router.post("/{group_id}/speltakken/{speltak_id}/members/{user_id}/withdraw",
             status_code=status.HTTP_204_NO_CONTENT)
def withdraw_speltak_invite(
    group_id: str,
    speltak_id: str,
    user_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    s = groups_svc.get_speltak(db, speltak_id)
    if not s or s.group_id != group_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Speltak not found.")
    if not groups_svc.can_manage_speltak(current_user, db, speltak_id):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Not allowed.")
    groups_svc.withdraw_speltak_invite(db, user_id=user_id, speltak_id=speltak_id)


@router.post("/{group_id}/speltakken/{speltak_id}/members/{user_id}/dismiss",
             status_code=status.HTTP_204_NO_CONTENT)
def dismiss_speltak_invite(
    group_id: str,
    speltak_id: str,
    user_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    s = groups_svc.get_speltak(db, speltak_id)
    if not s or s.group_id != group_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Speltak not found.")
    if current_user.id != user_id:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Not allowed.")
    groups_svc.dismiss_speltak_invite(db, user_id=user_id, speltak_id=speltak_id)


@router.post("/{group_id}/speltakken/{speltak_id}/members/{user_id}/accept",
             status_code=status.HTTP_204_NO_CONTENT)
def accept_speltak_invite(
    group_id: str,
    speltak_id: str,
    user_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    s = groups_svc.get_speltak(db, speltak_id)
    if not s or s.group_id != group_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Speltak not found.")
    if current_user.id != user_id:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Not allowed.")
    groups_svc.accept_speltak_invite(db, user_id=user_id, speltak_id=speltak_id)


@router.post("/{group_id}/speltakken/{speltak_id}/members/{user_id}/deny",
             status_code=status.HTTP_204_NO_CONTENT)
def deny_speltak_invite(
    group_id: str,
    speltak_id: str,
    user_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    s = groups_svc.get_speltak(db, speltak_id)
    if not s or s.group_id != group_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Speltak not found.")
    if current_user.id != user_id:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Not allowed.")
    groups_svc.deny_speltak_invite(db, user_id=user_id, speltak_id=speltak_id)


@router.post("/{group_id}/speltakken/{speltak_id}/scouts",
             status_code=status.HTTP_201_CREATED)
def create_emailless_scout(
    group_id: str,
    speltak_id: str,
    body: CreateEmaillessScoutRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    s = groups_svc.get_speltak(db, speltak_id)
    if not s or s.group_id != group_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Speltak not found.")
    if not groups_svc.can_manage_speltak(current_user, db, speltak_id):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Not allowed.")
    scout = groups_svc.create_emailless_scout(db, name=body.name,
                                              created_by_id=current_user.id)
    groups_svc.set_speltak_role(db, user_id=scout.id, speltak_id=speltak_id, role="scout")
    return {"id": scout.id, "name": scout.name}


@router.post("/{group_id}/speltakken/{speltak_id}/members/{user_id}/set-email",
             status_code=status.HTTP_204_NO_CONTENT)
def attach_email_to_scout(
    group_id: str,
    speltak_id: str,
    user_id: str,
    body: AttachEmailRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    s = groups_svc.get_speltak(db, speltak_id)
    if not s or s.group_id != group_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Speltak not found.")
    if not groups_svc.can_manage_speltak(current_user, db, speltak_id):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Not allowed.")
    try:
        groups_svc.attach_email_to_scout(
            db, scout_user_id=user_id, email=str(body.email),
            invited_by_id=current_user.id, speltak=s,
        )
    except ValueError as e:
        if "email_in_use" in str(e):
            raise HTTPException(status.HTTP_409_CONFLICT, "Email already in use by a pending user.")
        raise


# ── Invitations (current user) ────────────────────────────────────────────────

invitations_router = APIRouter(prefix="/invitations", tags=["invitations"])


@invitations_router.get("/me", response_model=InvitationListResponse)
def list_my_invitations(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    group_invites, speltak_invites = groups_svc.list_pending_invitations_for_user(
        db, current_user.id
    )
    return InvitationListResponse(
        group_invites=[
            GroupInvitationResponse(
                group_id=m.group_id,
                group_name=m.group.name,
                role=m.role,
                withdrawn=m.withdrawn,
                invited_by_id=m.invited_by_id,
            )
            for m in group_invites
        ],
        speltak_invites=[
            SpeltakInvitationResponse(
                speltak_id=m.speltak_id,
                speltak_name=m.speltak.name,
                group_id=m.speltak.group_id,
                group_name=m.speltak.group.name,
                role=m.role,
                withdrawn=m.withdrawn,
                invited_by_id=m.invited_by_id,
            )
            for m in speltak_invites
        ],
    )


# ── Membership requests ───────────────────────────────────────────────────────

def _req_response(r) -> MembershipRequestResponse:
    return MembershipRequestResponse(
        id=r.id, user_id=r.user_id, group_id=r.group_id,
        speltak_id=r.speltak_id, status=r.status,
        reviewed_by_id=r.reviewed_by_id,
        created_at=r.created_at,
    )


@router.post("/{group_id}/requests", response_model=MembershipRequestResponse,
             status_code=status.HTTP_201_CREATED)
def create_membership_request(
    group_id: str,
    body: CreateMembershipRequestRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    if not groups_svc.get_group(db, group_id):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Group not found.")
    try:
        req = groups_svc.create_membership_request(
            db, user_id=current_user.id, group_id=group_id, speltak_id=body.speltak_id
        )
    except ValueError as e:
        detail = {"already_member": "Already a member.", "request_exists": "Request already pending."}.get(str(e), str(e))
        raise HTTPException(status.HTTP_409_CONFLICT, detail)
    return _req_response(req)


@router.get("/{group_id}/requests", response_model=list[MembershipRequestResponse])
def list_membership_requests(
    group_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    if not groups_svc.get_group(db, group_id):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Group not found.")
    if not groups_svc.can_manage_group(current_user, db, group_id):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Not allowed.")
    return [_req_response(r) for r in groups_svc.list_pending_requests_for_group(db, group_id)]


@router.post("/{group_id}/requests/{req_id}/approve", status_code=status.HTTP_204_NO_CONTENT)
def approve_membership_request(
    group_id: str,
    req_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    if not groups_svc.get_group(db, group_id):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Group not found.")
    if not groups_svc.can_manage_group(current_user, db, group_id):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Not allowed.")
    try:
        groups_svc.approve_membership_request(db, request_id=req_id, reviewed_by_id=current_user.id)
    except ValueError:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Request not found.")


@router.post("/{group_id}/requests/{req_id}/reject", status_code=status.HTTP_204_NO_CONTENT)
def reject_membership_request(
    group_id: str,
    req_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    if not groups_svc.get_group(db, group_id):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Group not found.")
    if not groups_svc.can_manage_group(current_user, db, group_id):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Not allowed.")
    try:
        groups_svc.reject_membership_request(db, request_id=req_id, reviewed_by_id=current_user.id)
    except ValueError:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Request not found.")

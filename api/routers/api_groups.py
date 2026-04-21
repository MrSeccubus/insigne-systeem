from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from insigne import groups as groups_svc
from insigne.config import config
from insigne.database import get_db
from insigne.models import User
from deps import get_current_user
from schemas import (
    CreateEmaillessScoutRequest,
    CreateGroupRequest,
    CreateSpeltakRequest,
    GroupResponse,
    SetMemberRoleRequest,
    SetSpeltakRoleRequest,
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
    return SpeltakResponse(id=s.id, group_id=s.group_id, name=s.name, slug=s.slug)


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
    s = groups_svc.create_speltak(db, group_id=group_id, name=body.name, slug=body.slug)
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
    return _speltak_response(groups_svc.update_speltak(db, s, name=body.name, slug=body.slug))


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

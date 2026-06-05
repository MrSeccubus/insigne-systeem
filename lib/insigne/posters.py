"""Poster template persistence + access control (#132).

Scope rules:
- **personal** (`user_id`): visible to / editable by the owner only.
- **speltak** (`speltak_id`): visible to members of the speltak; editable by
  its leaders (`can_manage_speltak`).
- **group** (`group_id`): visible to members of the group; editable by its
  leaders (`can_manage_group`).

Access helpers return **data / booleans**, never ``RedirectResponse`` — the
route handler builds redirects from string literals (CLAUDE.md convention).
"""
from __future__ import annotations

from sqlalchemy.orm import Session

from insigne import groups as groups_svc
from insigne.models import (
    GroupMembership,
    PosterTemplate,
    SpeltakMembership,
    User,
)
from insigne.poster_templates import POSTER_TYPES


# ── CRUD ────────────────────────────────────────────────────────────────────

def create(
    db: Session,
    *,
    created_by_id: str,
    name: str,
    poster_type: str,
    paper_size: str,
    orientation: str,
    params: dict,
    scope: str,
    scope_id: str | None,
) -> PosterTemplate:
    """Create a poster template at the given scope. ``scope`` is one of
    ``user`` / ``speltak`` / ``group``; for ``user`` the owner is the creator."""
    poster = PosterTemplate(
        created_by_id=created_by_id,
        name=name,
        poster_type=poster_type,
        paper_size=paper_size,
        orientation=orientation,
        params=params,
        user_id=created_by_id if scope == "user" else None,
        speltak_id=scope_id if scope == "speltak" else None,
        group_id=scope_id if scope == "group" else None,
    )
    db.add(poster)
    db.commit()
    return poster


def get(db: Session, poster_id: str) -> PosterTemplate | None:
    return db.get(PosterTemplate, poster_id)


def update(
    db: Session,
    poster: PosterTemplate,
    *,
    name: str,
    paper_size: str,
    orientation: str,
    params: dict,
) -> PosterTemplate:
    poster.name = name
    poster.paper_size = paper_size
    poster.orientation = orientation
    poster.params = params
    db.commit()
    return poster


def delete(db: Session, poster: PosterTemplate) -> None:
    db.delete(poster)
    db.commit()


# ── Membership scope helpers ─────────────────────────────────────────────────

def _member_speltak_ids(db: Session, user_id: str) -> set[str]:
    return {
        m.speltak_id for m in db.query(SpeltakMembership)
        .filter_by(user_id=user_id, approved=True, withdrawn=False).all()
    }


def _member_group_ids(db: Session, user_id: str) -> set[str]:
    """Group ids the user belongs to — directly or via a speltak membership."""
    ids = {
        m.group_id for m in db.query(GroupMembership)
        .filter_by(user_id=user_id, approved=True, withdrawn=False).all()
    }
    for sid in _member_speltak_ids(db, user_id):
        sp = groups_svc.get_speltak(db, sid)
        if sp:
            ids.add(sp.group_id)
    return ids


# ── Access control ────────────────────────────────────────────────────────────

def can_view(db: Session, user: User, poster: PosterTemplate) -> bool:
    if poster.scope == "user":
        return poster.user_id == user.id
    if poster.scope == "speltak":
        return (poster.speltak_id in _member_speltak_ids(db, user.id)
                or groups_svc.can_manage_speltak(user, db, poster.speltak_id))
    return (poster.group_id in _member_group_ids(db, user.id)
            or groups_svc.can_manage_group(user, db, poster.group_id))


def can_edit(db: Session, user: User, poster: PosterTemplate) -> bool:
    if poster.scope == "user":
        return poster.user_id == user.id
    if poster.scope == "speltak":
        return groups_svc.can_manage_speltak(user, db, poster.speltak_id)
    return groups_svc.can_manage_group(user, db, poster.group_id)


def can_save_at(db: Session, user: User, scope: str, scope_id: str | None) -> bool:
    """Whether the user may create/save a template at the requested scope."""
    if scope == "user":
        return True
    if scope == "speltak":
        return bool(scope_id) and groups_svc.can_manage_speltak(user, db, scope_id)
    if scope == "group":
        return bool(scope_id) and groups_svc.can_manage_group(user, db, scope_id)
    return False


def manageable_scopes(db: Session, user: User) -> dict:
    """Scopes the user may save **at**, for the designer's scope picker:
    always personal; speltakken/groups they lead."""
    groups = [g for g in groups_svc.list_groups_for_user(db, user)
              if groups_svc.can_manage_group(user, db, g.id)]
    speltakken: list = []
    seen: set[str] = set()
    for group, speltak in groups_svc.list_my_speltakken(db, user.id):
        if speltak.id not in seen:
            speltakken.append((group, speltak))
            seen.add(speltak.id)
    for group in groups:
        for speltak in group.speltakken:
            if speltak.id not in seen:
                speltakken.append((group, speltak))
                seen.add(speltak.id)
    return {"groups": groups, "speltakken": speltakken}


def list_visible_to(db: Session, user: User) -> dict:
    """Templates the user can see, grouped by scope:
    ``{"personal": [...], "speltak": [...], "group": [...]}``."""
    personal = (
        db.query(PosterTemplate).filter_by(user_id=user.id)
        .order_by(PosterTemplate.updated_at.desc()).all()
    )
    speltak_ids = _member_speltak_ids(db, user.id)
    group_ids = _member_group_ids(db, user.id)
    speltak = (
        db.query(PosterTemplate).filter(PosterTemplate.speltak_id.in_(speltak_ids))
        .order_by(PosterTemplate.updated_at.desc()).all()
        if speltak_ids else []
    )
    group = (
        db.query(PosterTemplate).filter(PosterTemplate.group_id.in_(group_ids))
        .order_by(PosterTemplate.updated_at.desc()).all()
        if group_ids else []
    )
    return {"personal": personal, "speltak": speltak, "group": group}


def is_valid_type(poster_type: str) -> bool:
    return poster_type in POSTER_TYPES

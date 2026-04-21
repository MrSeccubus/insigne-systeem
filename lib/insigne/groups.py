import re
import unicodedata

from sqlalchemy.orm import Session

from insigne.models import (
    Group,
    GroupMembership,
    Speltak,
    SpeltakMembership,
    User,
)


# ── Slug helpers ──────────────────────────────────────────────────────────────

def name_to_slug(name: str) -> str:
    """Convert a human-readable name to a URL-safe slug."""
    nfkd = unicodedata.normalize("NFD", name)
    ascii_only = "".join(c for c in nfkd if unicodedata.category(c) != "Mn")
    slug = re.sub(r"[^a-z0-9]+", "-", ascii_only.lower()).strip("-")
    return slug or "groep"


# ── Authorization helpers ──────────────────────────────────────────────────────

def get_group_role(db: Session, user_id: str, group_id: str) -> str | None:
    m = db.query(GroupMembership).filter_by(
        user_id=user_id, group_id=group_id, approved=True
    ).first()
    return m.role if m else None


def get_speltak_role(db: Session, user_id: str, speltak_id: str) -> str | None:
    m = db.query(SpeltakMembership).filter_by(
        user_id=user_id, speltak_id=speltak_id, approved=True
    ).first()
    return m.role if m else None


def is_user_in_group(db: Session, user_id: str, group_id: str) -> bool:
    """Return True if the user has any approved membership within the group."""
    if db.query(GroupMembership).filter_by(user_id=user_id, group_id=group_id, approved=True).first():
        return True
    for speltak in db.query(Speltak).filter_by(group_id=group_id).all():
        if db.query(SpeltakMembership).filter_by(user_id=user_id, speltak_id=speltak.id, approved=True).first():
            return True
    return False


def can_manage_group(user: User, db: Session, group_id: str) -> bool:
    if user.is_admin:
        return True
    return get_group_role(db, user.id, group_id) == "groepsleider"


def can_manage_speltak(user: User, db: Session, speltak_id: str) -> bool:
    if user.is_admin:
        return True
    speltak = db.get(Speltak, speltak_id)
    if speltak and get_group_role(db, user.id, speltak.group_id) == "groepsleider":
        return True
    return get_speltak_role(db, user.id, speltak_id) == "speltakleider"


# ── Group CRUD ─────────────────────────────────────────────────────────────────

def create_group(db: Session, *, name: str, slug: str, created_by_id: str | None = None) -> Group:
    group = Group(name=name, slug=slug, created_by_id=created_by_id)
    db.add(group)
    db.flush()
    if created_by_id:
        db.add(GroupMembership(
            user_id=created_by_id, group_id=group.id,
            role="groepsleider", approved=True,
        ))
    db.commit()
    db.refresh(group)
    return group


def get_group(db: Session, group_id: str) -> Group | None:
    return db.get(Group, group_id)


def get_group_by_slug(db: Session, slug: str) -> Group | None:
    return db.query(Group).filter_by(slug=slug).first()


def unique_group_slug(db: Session, base_slug: str) -> str:
    """Return base_slug if unused, otherwise base_slug-2, -3, … until unique."""
    if not get_group_by_slug(db, base_slug):
        return base_slug
    i = 2
    while get_group_by_slug(db, f"{base_slug}-{i}"):
        i += 1
    return f"{base_slug}-{i}"


def unique_speltak_slug(db: Session, group_id: str, base_slug: str) -> str:
    """Return base_slug if unused within the group, otherwise base_slug-2, -3, …"""
    if not get_speltak_by_slug(db, group_id, base_slug):
        return base_slug
    i = 2
    while get_speltak_by_slug(db, group_id, f"{base_slug}-{i}"):
        i += 1
    return f"{base_slug}-{i}"


def list_groups(db: Session) -> list[Group]:
    return db.query(Group).order_by(Group.name).all()


def list_groups_for_user(db: Session, user: User) -> list[Group]:
    """Return groups the user can manage or has a speltakleider role in."""
    if user.is_admin:
        return list_groups(db)
    group_ids: set[str] = set()
    for m in db.query(GroupMembership).filter_by(user_id=user.id, approved=True).all():
        if m.role == "groepsleider":
            group_ids.add(m.group_id)
    for sm in db.query(SpeltakMembership).filter_by(
        user_id=user.id, role="speltakleider", approved=True
    ).all():
        speltak = db.get(Speltak, sm.speltak_id)
        if speltak:
            group_ids.add(speltak.group_id)
    if not group_ids:
        return []
    return db.query(Group).filter(Group.id.in_(group_ids)).order_by(Group.name).all()


def update_group(db: Session, group: Group, *, name: str, slug: str) -> Group:
    group.name = name
    group.slug = slug
    db.commit()
    db.refresh(group)
    return group


def delete_group(db: Session, group: Group) -> None:
    db.delete(group)
    db.commit()


# ── Speltak CRUD ───────────────────────────────────────────────────────────────

def create_speltak(db: Session, *, group_id: str, name: str, slug: str) -> Speltak:
    speltak = Speltak(group_id=group_id, name=name, slug=slug)
    db.add(speltak)
    db.commit()
    db.refresh(speltak)
    return speltak


def get_speltak(db: Session, speltak_id: str) -> Speltak | None:
    return db.get(Speltak, speltak_id)


def get_speltak_by_slug(db: Session, group_id: str, slug: str) -> Speltak | None:
    return db.query(Speltak).filter_by(group_id=group_id, slug=slug).first()


def update_speltak(db: Session, speltak: Speltak, *, name: str, slug: str) -> Speltak:
    speltak.name = name
    speltak.slug = slug
    db.commit()
    db.refresh(speltak)
    return speltak


def delete_speltak(db: Session, speltak: Speltak) -> None:
    db.delete(speltak)
    db.commit()


# ── Group membership ───────────────────────────────────────────────────────────

def list_group_members(db: Session, group_id: str) -> list[GroupMembership]:
    return (
        db.query(GroupMembership)
        .filter_by(group_id=group_id, approved=True)
        .all()
    )


def list_pending_group_members(db: Session, group_id: str) -> list[GroupMembership]:
    return (
        db.query(GroupMembership)
        .filter_by(group_id=group_id, approved=False, withdrawn=False)
        .all()
    )


def list_pending_invitations_for_user(
    db: Session, user_id: str
) -> tuple[list[GroupMembership], list[SpeltakMembership]]:
    group_invites = db.query(GroupMembership).filter_by(user_id=user_id, approved=False).all()
    speltak_invites = db.query(SpeltakMembership).filter_by(user_id=user_id, approved=False).all()
    return group_invites, speltak_invites


def accept_group_invite(db: Session, user_id: str, group_id: str) -> None:
    m = db.query(GroupMembership).filter_by(
        user_id=user_id, group_id=group_id, approved=False, withdrawn=False
    ).first()
    if m:
        m.approved = True
        db.commit()


def deny_group_invite(db: Session, user_id: str, group_id: str) -> None:
    m = db.query(GroupMembership).filter_by(user_id=user_id, group_id=group_id, approved=False).first()
    if m:
        db.delete(m)
        db.commit()


def withdraw_group_invite(db: Session, user_id: str, group_id: str) -> None:
    m = db.query(GroupMembership).filter_by(user_id=user_id, group_id=group_id, approved=False).first()
    if m:
        m.withdrawn = True
        db.commit()


def dismiss_group_invite(db: Session, user_id: str, group_id: str) -> None:
    m = db.query(GroupMembership).filter_by(user_id=user_id, group_id=group_id, approved=False).first()
    if m:
        db.delete(m)
        db.commit()


def accept_speltak_invite(db: Session, user_id: str, speltak_id: str) -> None:
    m = db.query(SpeltakMembership).filter_by(
        user_id=user_id, speltak_id=speltak_id, approved=False, withdrawn=False
    ).first()
    if m:
        m.approved = True
        db.commit()


def deny_speltak_invite(db: Session, user_id: str, speltak_id: str) -> None:
    m = db.query(SpeltakMembership).filter_by(user_id=user_id, speltak_id=speltak_id, approved=False).first()
    if m:
        db.delete(m)
        db.commit()


def withdraw_speltak_invite(db: Session, user_id: str, speltak_id: str) -> None:
    m = db.query(SpeltakMembership).filter_by(user_id=user_id, speltak_id=speltak_id, approved=False).first()
    if m:
        m.withdrawn = True
        db.commit()


def dismiss_speltak_invite(db: Session, user_id: str, speltak_id: str) -> None:
    m = db.query(SpeltakMembership).filter_by(user_id=user_id, speltak_id=speltak_id, approved=False).first()
    if m:
        db.delete(m)
        db.commit()


def set_group_role(
    db: Session, *, user_id: str, group_id: str, role: str
) -> GroupMembership:
    m = db.query(GroupMembership).filter_by(user_id=user_id, group_id=group_id).first()
    if m:
        m.role = role
        m.approved = True
    else:
        m = GroupMembership(user_id=user_id, group_id=group_id, role=role, approved=True)
        db.add(m)
    db.commit()
    db.refresh(m)
    return m


def remove_group_member(db: Session, *, user_id: str, group_id: str) -> None:
    m = db.query(GroupMembership).filter_by(user_id=user_id, group_id=group_id).first()
    if m:
        db.delete(m)
        db.commit()


# ── Speltak membership ─────────────────────────────────────────────────────────

def list_group_users_not_in_speltak(db: Session, group_id: str, speltak_id: str) -> list[User]:
    """Active users associated with the group (any speltak or group membership)
    who are not yet in the given speltak and have an email address."""
    already_in = {
        m.user_id for m in
        db.query(SpeltakMembership).filter_by(speltak_id=speltak_id, approved=True).all()
    }
    candidate_ids: set[str] = set()
    for m in db.query(GroupMembership).filter_by(group_id=group_id, approved=True).all():
        candidate_ids.add(m.user_id)
    for s in db.query(Speltak).filter_by(group_id=group_id).all():
        for m in db.query(SpeltakMembership).filter_by(speltak_id=s.id, approved=True).all():
            candidate_ids.add(m.user_id)
    candidate_ids -= already_in
    if not candidate_ids:
        return []
    return (
        db.query(User)
        .filter(User.id.in_(candidate_ids), User.email.isnot(None), User.status == "active")
        .order_by(User.name)
        .all()
    )


def list_speltak_members(db: Session, speltak_id: str) -> list[SpeltakMembership]:
    return (
        db.query(SpeltakMembership)
        .filter_by(speltak_id=speltak_id, approved=True)
        .all()
    )


def list_pending_speltak_members(db: Session, speltak_id: str) -> list[SpeltakMembership]:
    return (
        db.query(SpeltakMembership)
        .filter_by(speltak_id=speltak_id, approved=False, withdrawn=False)
        .all()
    )


def set_speltak_role(
    db: Session, *, user_id: str, speltak_id: str, role: str
) -> SpeltakMembership:
    m = db.query(SpeltakMembership).filter_by(user_id=user_id, speltak_id=speltak_id).first()
    if m:
        m.role = role
        m.approved = True
    else:
        m = SpeltakMembership(user_id=user_id, speltak_id=speltak_id, role=role, approved=True)
        db.add(m)
    db.commit()
    db.refresh(m)
    return m


def remove_speltak_member(db: Session, *, user_id: str, speltak_id: str) -> None:
    m = db.query(SpeltakMembership).filter_by(user_id=user_id, speltak_id=speltak_id).first()
    if not m:
        return
    speltak = db.query(Speltak).filter_by(id=speltak_id).first()
    db.delete(m)
    db.flush()
    if speltak:
        _cleanup_group_membership(db, user_id=user_id, group_id=speltak.group_id)
    db.commit()


def _cleanup_group_membership(db: Session, *, user_id: str, group_id: str) -> None:
    """Remove group membership if the user has no remaining ties to the group."""
    gm = db.query(GroupMembership).filter_by(user_id=user_id, group_id=group_id).first()
    if not gm:
        return
    if gm.role in ("groepsleider", "speltakleider"):
        return
    for speltak in db.query(Speltak).filter_by(group_id=group_id).all():
        if db.query(SpeltakMembership).filter_by(user_id=user_id, speltak_id=speltak.id).first():
            return
    db.delete(gm)


def transfer_scout(
    db: Session, *, user_id: str, from_speltak_id: str, to_speltak_id: str
) -> SpeltakMembership:
    remove_speltak_member(db, user_id=user_id, speltak_id=from_speltak_id)
    return set_speltak_role(db, user_id=user_id, speltak_id=to_speltak_id, role="scout")


# ── Emailless scout ────────────────────────────────────────────────────────────

def create_emailless_scout(
    db: Session, *, name: str, created_by_id: str
) -> User:
    scout = User(email=None, name=name, status="active", created_by_id=created_by_id)
    db.add(scout)
    db.commit()
    db.refresh(scout)
    return scout

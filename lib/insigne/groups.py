from sqlalchemy.orm import Session

from insigne.models import (
    Group,
    GroupMembership,
    Speltak,
    SpeltakMembership,
    User,
)


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


def list_groups(db: Session) -> list[Group]:
    return db.query(Group).order_by(Group.name).all()


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

def list_speltak_members(db: Session, speltak_id: str) -> list[SpeltakMembership]:
    return (
        db.query(SpeltakMembership)
        .filter_by(speltak_id=speltak_id, approved=True)
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
    if m:
        db.delete(m)
        db.commit()


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

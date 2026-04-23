import re
import unicodedata
from datetime import datetime, timezone

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from insigne.models import (
    ConfirmationToken,
    Group,
    GroupFavoriteBadge,
    GroupMembership,
    ProgressEntry,
    Speltak,
    SpeltakFavoriteBadge,
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
    return db.query(Group).order_by(func.lower(Group.name)).all()


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
    return db.query(Group).filter(Group.id.in_(group_ids)).order_by(func.lower(Group.name)).all()


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

def create_speltak(db: Session, *, group_id: str, name: str, slug: str, peer_signoff: bool = False) -> Speltak:
    speltak = Speltak(group_id=group_id, name=name, slug=slug, peer_signoff=peer_signoff)
    db.add(speltak)
    db.commit()
    db.refresh(speltak)
    return speltak


def get_speltak(db: Session, speltak_id: str) -> Speltak | None:
    return db.get(Speltak, speltak_id)


def get_speltak_by_slug(db: Session, group_id: str, slug: str) -> Speltak | None:
    return db.query(Speltak).filter_by(group_id=group_id, slug=slug).first()


def update_speltak(db: Session, speltak: Speltak, *, name: str, slug: str, peer_signoff: bool = False) -> Speltak:
    speltak.name = name
    speltak.slug = slug
    speltak.peer_signoff = peer_signoff
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


def list_active_memberships_for_user(
    db: Session, user_id: str
) -> tuple[list[GroupMembership], list[SpeltakMembership]]:
    groups = (
        db.query(GroupMembership)
        .filter_by(user_id=user_id, approved=True, withdrawn=False)
        .all()
    )
    speltakken = (
        db.query(SpeltakMembership)
        .filter_by(user_id=user_id, approved=True, withdrawn=False)
        .all()
    )
    return groups, speltakken


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


def withdraw_speltak_invite(db: Session, user_id: str, speltak_id: str) -> bool:
    """Withdraw a pending speltak invite. Returns True if the user was reverted to
    an emailless scout (caller should refresh the page), False if simply withdrawn."""
    m = db.query(SpeltakMembership).filter_by(user_id=user_id, speltak_id=speltak_id, approved=False).first()
    if not m:
        return False
    user = db.get(User, user_id)
    # Emailless scout with a pending email invite: revert to emailless rather than mark withdrawn
    if user and user.created_by_id is not None and user.status == "pending":
        user.email = None
        user.status = "active"
        db.query(ConfirmationToken).filter(
            ConfirmationToken.user_id == user_id,
            ConfirmationToken.used_at.is_(None),
        ).update({"used_at": datetime.now(timezone.utc)})
        m.approved = True
        m.withdrawn = False
        db.commit()
        return True
    m.withdrawn = True
    db.commit()
    return False


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
        m.withdrawn = False
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


def list_members_without_speltak(db: Session, group_id: str) -> list[GroupMembership]:
    """Group members (role=member) not in any speltak of this group."""
    in_speltak = {
        m.user_id
        for s in db.query(Speltak).filter_by(group_id=group_id).all()
        for m in db.query(SpeltakMembership).filter_by(speltak_id=s.id, approved=True).all()
    }
    return [
        m for m in
        db.query(GroupMembership).filter_by(group_id=group_id, role="member", approved=True).all()
        if m.user_id not in in_speltak
    ]


def list_speltak_members(db: Session, speltak_id: str) -> list[SpeltakMembership]:
    # Exclude emailless scouts that have a pending invite (source_scout_id points at them)
    pending_source_ids = select(SpeltakMembership.source_scout_id).where(
        SpeltakMembership.speltak_id == speltak_id,
        SpeltakMembership.approved == False,  # noqa: E712
        SpeltakMembership.withdrawn == False,  # noqa: E712
        SpeltakMembership.source_scout_id.isnot(None),
    )
    rows = (
        db.query(SpeltakMembership)
        .filter(
            SpeltakMembership.speltak_id == speltak_id,
            SpeltakMembership.approved == True,  # noqa: E712
            SpeltakMembership.user_id.not_in(pending_source_ids),
        )
        .all()
    )
    return sorted(rows, key=lambda m: (m.user.name or "").lower())


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
        m.withdrawn = False
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
    # Set destination first so _cleanup_group_membership (called during source
    # removal) sees the destination membership and keeps the group membership.
    # The upsert in set_speltak_role also handles the case where the user is
    # already a member of the destination speltak without creating a duplicate.
    result = set_speltak_role(db, user_id=user_id, speltak_id=to_speltak_id, role="scout")
    remove_speltak_member(db, user_id=user_id, speltak_id=from_speltak_id)
    return result


# ── Emailless scout ────────────────────────────────────────────────────────────

def create_emailless_scout(
    db: Session, *, name: str, created_by_id: str
) -> User:
    scout = User(email=None, name=name, status="active", created_by_id=created_by_id)
    db.add(scout)
    db.commit()
    db.refresh(scout)
    return scout


_STATUS_RANK: dict[str, int] = {
    "in_progress": 0,
    "work_done": 1,
    "pending_signoff": 2,
    "signed_off": 3,
}


def merge_scout_progress(db: Session, *, from_user_id: str, to_user_id: str) -> None:
    """Merge progress entries from one user into another, keeping the higher status per step."""
    for entry in db.query(ProgressEntry).filter_by(user_id=from_user_id).all():
        existing = db.query(ProgressEntry).filter_by(
            user_id=to_user_id,
            badge_slug=entry.badge_slug,
            level_index=entry.level_index,
            step_index=entry.step_index,
        ).first()
        if existing is None:
            entry.user_id = to_user_id
        elif _STATUS_RANK.get(entry.status, 0) > _STATUS_RANK.get(existing.status, 0):
            db.delete(existing)
            db.flush()
            entry.user_id = to_user_id
        else:
            db.delete(entry)
    db.flush()


def has_scout_progress(db: Session, user_id: str) -> bool:
    """Return True if the user has any progress entries."""
    return db.query(ProgressEntry).filter_by(user_id=user_id).first() is not None


def preview_scout_merge(db: Session, *, from_user_id: str, to_user_id: str) -> list[dict]:
    """Return changes that would result from merging from_user into to_user.
    Only entries that would actually change (added or upgraded) are included."""
    changes = []
    for entry in db.query(ProgressEntry).filter_by(user_id=from_user_id).all():
        existing = db.query(ProgressEntry).filter_by(
            user_id=to_user_id,
            badge_slug=entry.badge_slug,
            level_index=entry.level_index,
            step_index=entry.step_index,
        ).first()
        if existing is None:
            changes.append({
                "type": "added",
                "badge_slug": entry.badge_slug,
                "level_index": entry.level_index,
                "step_index": entry.step_index,
                "scout_status": entry.status,
                "existing_status": None,
            })
        elif _STATUS_RANK.get(entry.status, 0) > _STATUS_RANK.get(existing.status, 0):
            changes.append({
                "type": "upgraded",
                "badge_slug": entry.badge_slug,
                "level_index": entry.level_index,
                "step_index": entry.step_index,
                "scout_status": entry.status,
                "existing_status": existing.status,
            })
    return changes


def accept_speltak_invite_with_merge(db: Session, *, user_id: str, speltak_id: str) -> None:
    """Accept a speltak invite and merge progress from the linked emailless scout."""
    m = db.query(SpeltakMembership).filter_by(
        user_id=user_id, speltak_id=speltak_id, approved=False, withdrawn=False
    ).first()
    if not m:
        return
    if m.source_scout_id:
        merge_scout_progress(db, from_user_id=m.source_scout_id, to_user_id=user_id)
        _cleanup_group_membership(db, user_id=m.source_scout_id, group_id=m.speltak.group_id)
        scout = db.get(User, m.source_scout_id)
        if scout:
            db.delete(scout)
        db.flush()
    m.approved = True
    m.source_scout_id = None
    db.commit()


def accept_speltak_invite_without_merge(db: Session, *, user_id: str, speltak_id: str) -> None:
    """Accept a speltak invite and discard the linked emailless scout's progress."""
    m = db.query(SpeltakMembership).filter_by(
        user_id=user_id, speltak_id=speltak_id, approved=False, withdrawn=False
    ).first()
    if not m:
        return
    if m.source_scout_id:
        db.query(ProgressEntry).filter_by(user_id=m.source_scout_id).delete()
        db.flush()
        _cleanup_group_membership(db, user_id=m.source_scout_id, group_id=m.speltak.group_id)
        scout = db.get(User, m.source_scout_id)
        if scout:
            db.delete(scout)
        db.flush()
    m.approved = True
    m.source_scout_id = None
    db.commit()


def attach_email_to_scout(
    db: Session, *, scout_user_id: str, email: str, invited_by_id: str, speltak: Speltak
) -> tuple[str, User, str | None]:
    """Add an email address to an emailless scout.

    Returns ('new_user', user, code) if the email was unknown — the scout's
    own account gets the email and a registration token.
    Returns ('existing_user', user, None) if an active user already has that
    email — progress is merged into that user and they receive a pending invite.
    Raises ValueError('email_in_use') if the email belongs to a pending user.
    """
    from insigne import users as users_svc

    email = email.strip().lower()
    scout = db.get(User, scout_user_id)

    existing = db.query(User).filter(User.email == email).first()
    if existing is not None and existing.status != "active":
        raise ValueError("email_in_use")

    if existing is None:
        # Unknown email: assign email, put account in pending, issue registration token
        scout.email = email
        scout.status = "pending"
        sm = db.query(SpeltakMembership).filter_by(user_id=scout_user_id, speltak_id=speltak.id, approved=True).first()
        if sm:
            sm.approved = False
            sm.invited_by_id = invited_by_id
        db.flush()
        code, _, _ = users_svc.start_registration(db, email)
        return "new_user", scout, code

    # Active user found: create a pending speltak invite linked to the emailless scout.
    # The scout record is left untouched; the existing user will decide whether to merge
    # their progress when they accept the invite.
    m = db.query(SpeltakMembership).filter_by(user_id=existing.id, speltak_id=speltak.id).first()
    if m:
        m.approved = False
        m.withdrawn = False
        m.invited_by_id = invited_by_id
        m.source_scout_id = scout_user_id
    else:
        db.add(SpeltakMembership(
            user_id=existing.id, speltak_id=speltak.id,
            role="scout", approved=False, invited_by_id=invited_by_id,
            source_scout_id=scout_user_id,
        ))
    db.commit()
    return "existing_user", existing, None


# ── Membership requests ────────────────────────────────────────────────────────

def search_groups(db: Session, query: str) -> list[Group]:
    """Case-insensitive name search, max 20 results."""
    q = f"%{query.strip().lower()}%"
    return (
        db.query(Group)
        .filter(func.lower(Group.name).like(q))
        .order_by(func.lower(Group.name))
        .limit(20)
        .all()
    )


def create_membership_request(
    db: Session, *, user_id: str, group_id: str, speltak_id: str | None = None
) -> "MembershipRequest":
    """Create a pending membership request.

    Raises ValueError('already_member') if the user is already an approved member.
    Raises ValueError('request_exists') if a pending request already exists.
    """
    from insigne.models import MembershipRequest

    if speltak_id:
        existing_m = db.query(SpeltakMembership).filter_by(
            user_id=user_id, speltak_id=speltak_id, approved=True
        ).first()
        if existing_m:
            raise ValueError("already_member")
    else:
        existing_m = db.query(GroupMembership).filter_by(
            user_id=user_id, group_id=group_id, approved=True
        ).first()
        if existing_m:
            raise ValueError("already_member")

    existing_r = db.query(MembershipRequest).filter_by(
        user_id=user_id, group_id=group_id, speltak_id=speltak_id, status="pending"
    ).first()
    if existing_r:
        raise ValueError("request_exists")

    req = MembershipRequest(
        user_id=user_id, group_id=group_id, speltak_id=speltak_id
    )
    db.add(req)
    db.commit()
    db.refresh(req)
    return req


def list_pending_requests_for_group(db: Session, group_id: str) -> list["MembershipRequest"]:
    """All pending requests for a group (group-level and speltak-level)."""
    from insigne.models import MembershipRequest
    return (
        db.query(MembershipRequest)
        .filter_by(group_id=group_id, status="pending")
        .order_by(MembershipRequest.created_at)
        .all()
    )


def list_my_membership_requests(db: Session, user_id: str) -> list["MembershipRequest"]:
    """All non-pending requests for a user (pending shown separately on home)."""
    from insigne.models import MembershipRequest
    return (
        db.query(MembershipRequest)
        .filter_by(user_id=user_id)
        .order_by(MembershipRequest.created_at.desc())
        .all()
    )


def cancel_membership_request(db: Session, *, request_id: str, user_id: str) -> None:
    """Delete a membership request, only if it belongs to user_id."""
    from insigne.models import MembershipRequest
    req = db.query(MembershipRequest).filter_by(id=request_id, user_id=user_id).first()
    if req:
        db.delete(req)
        db.commit()


def cancel_all_membership_requests(db: Session, *, user_id: str) -> None:
    """Delete all membership requests for a user."""
    from insigne.models import MembershipRequest
    db.query(MembershipRequest).filter_by(user_id=user_id).delete()
    db.commit()


def list_all_pending_requests_for_leader(db: Session, user_id: str) -> list:
    """All pending requests across every group the user manages, ordered by creation date."""
    from insigne.models import MembershipRequest

    managed_group_ids = {
        m.group_id for m in
        db.query(GroupMembership).filter_by(user_id=user_id, approved=True, role="groepsleider").all()
    }
    if not managed_group_ids:
        return []
    return (
        db.query(MembershipRequest)
        .filter(
            MembershipRequest.group_id.in_(managed_group_ids),
            MembershipRequest.status == "pending",
        )
        .order_by(MembershipRequest.created_at)
        .all()
    )


def group_pending_requests(pending: list) -> list[dict]:
    """Return pending requests grouped as [{group, speltakken: [{speltak, requests}]}]."""
    groups: dict = {}
    for req in pending:
        gid = req.group_id
        if gid not in groups:
            groups[gid] = {"group": req.group, "speltakken": {}}
        sid = req.speltak_id
        if sid not in groups[gid]["speltakken"]:
            groups[gid]["speltakken"][sid] = {"speltak": req.speltak, "requests": []}
        groups[gid]["speltakken"][sid]["requests"].append(req)

    result = []
    for g in sorted(groups.values(), key=lambda x: x["group"].name):
        speltakken = sorted(
            g["speltakken"].values(),
            key=lambda x: (x["speltak"] is not None, x["speltak"].name if x["speltak"] else ""),
        )
        result.append({"group": g["group"], "speltakken": speltakken})
    return result


def count_pending_requests_for_leader(db: Session, user_id: str) -> int:
    """Total pending requests across all groups/speltakken the user can manage."""
    from insigne.models import MembershipRequest

    managed_group_ids = {
        m.group_id for m in
        db.query(GroupMembership).filter_by(user_id=user_id, approved=True, role="groepsleider").all()
    }
    if not managed_group_ids:
        return 0
    return (
        db.query(MembershipRequest)
        .filter(
            MembershipRequest.group_id.in_(managed_group_ids),
            MembershipRequest.status == "pending",
        )
        .count()
    )


def approve_membership_request(
    db: Session, *, request_id: str, reviewed_by_id: str
) -> "MembershipRequest":
    """Approve a pending request; creates the appropriate membership record(s)."""
    from insigne.models import MembershipRequest

    req = db.query(MembershipRequest).filter_by(id=request_id, status="pending").first()
    if req is None:
        raise ValueError("not_found")

    if req.speltak_id:
        set_speltak_role(db, user_id=req.user_id, speltak_id=req.speltak_id, role="scout")
    else:
        set_group_role(db, user_id=req.user_id, group_id=req.group_id, role="member")

    req.status = "approved"
    req.reviewed_by_id = reviewed_by_id
    db.commit()
    db.refresh(req)
    return req


def reject_membership_request(
    db: Session, *, request_id: str, reviewed_by_id: str
) -> "MembershipRequest":
    """Reject a pending request."""
    from insigne.models import MembershipRequest

    req = db.query(MembershipRequest).filter_by(id=request_id, status="pending").first()
    if req is None:
        raise ValueError("not_found")

    req.status = "rejected"
    req.reviewed_by_id = reviewed_by_id
    db.commit()
    db.refresh(req)
    return req


# ── Leider progress management ────────────────────────────────────────────────

def list_my_speltakken(db: Session, user_id: str) -> list[tuple[Group, Speltak]]:
    """Return (group, speltak) pairs where user is explicitly a speltakleider.
    Does NOT include speltakken where user is merely groepsleider or admin."""
    memberships = (
        db.query(SpeltakMembership)
        .filter_by(user_id=user_id, role="speltakleider", approved=True, withdrawn=False)
        .all()
    )
    return [(m.speltak.group, m.speltak) for m in memberships]


def get_speltak_favorite_slugs(db: Session, speltak_id: str) -> set[str]:
    rows = db.query(SpeltakFavoriteBadge).filter_by(speltak_id=speltak_id).all()
    return {r.badge_slug for r in rows}


def toggle_speltak_favorite_badge(db: Session, speltak_id: str, badge_slug: str) -> bool:
    existing = db.query(SpeltakFavoriteBadge).filter_by(
        speltak_id=speltak_id, badge_slug=badge_slug
    ).first()
    if existing:
        db.delete(existing)
        db.commit()
        return False
    db.add(SpeltakFavoriteBadge(speltak_id=speltak_id, badge_slug=badge_slug))
    db.commit()
    return True


def get_group_favorite_slugs(db: Session, group_id: str) -> set[str]:
    rows = db.query(GroupFavoriteBadge).filter_by(group_id=group_id).all()
    return {r.badge_slug for r in rows}


def toggle_group_favorite_badge(db: Session, group_id: str, badge_slug: str) -> bool:
    existing = db.query(GroupFavoriteBadge).filter_by(
        group_id=group_id, badge_slug=badge_slug
    ).first()
    if existing:
        db.delete(existing)
        db.commit()
        return False
    db.add(GroupFavoriteBadge(group_id=group_id, badge_slug=badge_slug))
    db.commit()
    return True

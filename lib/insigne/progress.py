from datetime import datetime, timezone

from sqlalchemy.orm import Session

from .models import ProgressEntry, SignoffRejection, SignoffRequest, User


class NotFound(Exception):
    pass


class Forbidden(Exception):
    pass


class Conflict(Exception):
    pass


def list_progress(
    db: Session,
    user_id: str,
    *,
    badge_slug: str | None = None,
    status: str | None = None,
) -> list[ProgressEntry]:
    q = db.query(ProgressEntry).filter(ProgressEntry.user_id == user_id)
    if badge_slug:
        q = q.filter(ProgressEntry.badge_slug == badge_slug)
    if status:
        q = q.filter(ProgressEntry.status == status)
    return q.order_by(ProgressEntry.created_at.desc()).all()


def log_progress(
    db: Session,
    user_id: str,
    *,
    badge_slug: str,
    level_index: int,
    step_index: int,
    status: str,
    notes: str | None = None,
) -> ProgressEntry:
    """Create or update a progress entry.

    status must be 'in_progress' or 'work_done'.
    Raises Conflict if the entry is already pending_signoff or signed_off.
    """
    if status not in ("in_progress", "work_done"):
        raise ValueError(f"Invalid status: {status}")

    existing = db.query(ProgressEntry).filter(
        ProgressEntry.user_id == user_id,
        ProgressEntry.badge_slug == badge_slug,
        ProgressEntry.level_index == level_index,
        ProgressEntry.step_index == step_index,
    ).first()

    if existing:
        if existing.status in ("pending_signoff", "signed_off"):
            raise Conflict(existing.status)
        existing.status = status
        existing.notes = notes
        db.commit()
        return existing

    entry = ProgressEntry(
        user_id=user_id,
        badge_slug=badge_slug,
        level_index=level_index,
        step_index=step_index,
        status=status,
        notes=notes,
    )
    db.add(entry)
    db.commit()
    return entry


def create_progress(
    db: Session,
    user_id: str,
    *,
    badge_slug: str,
    level_index: int,
    step_index: int,
    notes: str | None = None,
) -> ProgressEntry:
    """JSON API compatibility wrapper — creates an in_progress entry."""
    return log_progress(
        db, user_id,
        badge_slug=badge_slug,
        level_index=level_index,
        step_index=step_index,
        status="in_progress",
        notes=notes,
    )


def get_progress(db: Session, user_id: str, entry_id: str) -> ProgressEntry:
    entry = db.query(ProgressEntry).filter(
        ProgressEntry.id == entry_id,
        ProgressEntry.user_id == user_id,
    ).first()
    if entry is None:
        raise NotFound("entry_not_found")
    return entry


def update_progress(db: Session, user_id: str, entry_id: str, *, notes: str | None) -> ProgressEntry:
    entry = get_progress(db, user_id, entry_id)
    if entry.status == "signed_off":
        raise Forbidden("entry_signed_off")
    entry.notes = notes
    db.commit()
    return entry


def delete_progress(db: Session, user_id: str, entry_id: str) -> None:
    entry = get_progress(db, user_id, entry_id)
    if entry.status == "signed_off":
        raise Forbidden("entry_signed_off")
    db.delete(entry)
    db.commit()


def cancel_signoff_requests(db: Session, user_id: str, entry_id: str) -> ProgressEntry:
    """Cancel all pending sign-off requests, reverting entry to work_done."""
    entry = db.query(ProgressEntry).filter(
        ProgressEntry.id == entry_id,
        ProgressEntry.user_id == user_id,
    ).first()
    if entry is None:
        raise NotFound("entry_not_found")
    if entry.status == "signed_off":
        raise Forbidden("entry_signed_off")
    if entry.status != "pending_signoff":
        raise Conflict("not_pending_signoff")

    db.query(SignoffRequest).filter(
        SignoffRequest.progress_entry_id == entry_id
    ).delete()
    entry.status = "work_done"
    db.commit()
    db.refresh(entry)
    return entry


def request_signoff(
    db: Session, scout_id: str, entry_id: str, mentor_email: str
) -> tuple[ProgressEntry, User, bool]:
    """Invite a mentor to sign off a progress entry.

    Only allowed when the entry status is 'work_done' or already 'pending_signoff'.
    Raises NotFound, Conflict("not_work_done"), Conflict("already_invited"),
    Conflict("already_signed_off").
    """
    entry = db.query(ProgressEntry).filter(
        ProgressEntry.id == entry_id,
        ProgressEntry.user_id == scout_id,
    ).first()
    if entry is None:
        raise NotFound("entry_not_found")
    if entry.status == "signed_off":
        raise Conflict("already_signed_off")
    if entry.status not in ("work_done", "pending_signoff"):
        raise Conflict("not_work_done")

    mentor_email = mentor_email.strip().lower()

    scout = db.get(User, scout_id)
    if scout and scout.email and scout.email.lower() == mentor_email:
        raise Forbidden("self_signoff")

    mentor = db.query(User).filter(User.email == mentor_email).first()
    created = False
    if mentor is None:
        mentor = User(email=mentor_email)
        db.add(mentor)
        db.flush()
        created = True

    already_invited = db.query(SignoffRequest).filter(
        SignoffRequest.progress_entry_id == entry_id,
        SignoffRequest.mentor_id == mentor.id,
    ).first()
    if already_invited:
        raise Conflict("already_invited")

    db.add(SignoffRequest(progress_entry_id=entry_id, mentor_id=mentor.id))
    entry.status = "pending_signoff"
    db.commit()
    return entry, mentor, created


def confirm_signoff(db: Session, mentor_id: str, entry_id: str, comment: str | None = None) -> ProgressEntry:
    """Confirm sign-off as the authenticated mentor."""
    entry = db.query(ProgressEntry).filter(ProgressEntry.id == entry_id).first()
    if entry is None:
        raise NotFound("entry_not_found")
    if entry.status == "signed_off":
        raise Conflict("already_signed_off")
    if mentor_id == entry.user_id:
        raise Forbidden("self_signoff")

    request = db.query(SignoffRequest).filter(
        SignoffRequest.progress_entry_id == entry_id,
        SignoffRequest.mentor_id == mentor_id,
    ).first()
    if request is None:
        raise Forbidden("not_invited")

    entry.status = "signed_off"
    entry.signed_off_by_id = mentor_id
    entry.signed_off_at = datetime.now(timezone.utc)
    entry.mentor_comment = comment or None

    db.query(SignoffRequest).filter(
        SignoffRequest.progress_entry_id == entry_id
    ).delete()

    db.commit()
    db.refresh(entry)
    return entry


def reject_signoff(db: Session, mentor_id: str, entry_id: str, message: str) -> ProgressEntry:
    """Reject a sign-off request as the authenticated mentor."""
    entry = db.query(ProgressEntry).filter(ProgressEntry.id == entry_id).first()
    if entry is None:
        raise NotFound("entry_not_found")
    if entry.status == "signed_off":
        raise Conflict("already_signed_off")

    request = db.query(SignoffRequest).filter(
        SignoffRequest.progress_entry_id == entry_id,
        SignoffRequest.mentor_id == mentor_id,
    ).first()
    if request is None:
        raise Forbidden("not_invited")

    mentor = db.query(User).filter(User.id == mentor_id).first()
    db.add(SignoffRejection(
        progress_entry_id=entry_id,
        mentor_name=mentor.name or mentor.email,
        message=message,
    ))
    db.delete(request)
    db.flush()
    remaining = db.query(SignoffRequest).filter_by(progress_entry_id=entry_id).count()
    if remaining == 0:
        entry.status = "work_done"

    db.commit()
    db.refresh(entry)
    return entry


def request_signoff_for_speltak(
    db: Session, scout_id: str, entry_id: str, speltak_id: str
) -> tuple[ProgressEntry, list[User]]:
    """Request sign-off from all speltakleiders of a non-peer speltak.

    Raises NotFound("entry_not_found"), Conflict("already_signed_off"),
    Conflict("not_work_done"), NotFound("no_eligible_mentors").
    """
    from insigne import groups as groups_svc

    entry = db.query(ProgressEntry).filter(
        ProgressEntry.id == entry_id,
        ProgressEntry.user_id == scout_id,
    ).first()
    if entry is None:
        raise NotFound("entry_not_found")
    if entry.status == "signed_off":
        raise Conflict("already_signed_off")
    if entry.status not in ("work_done", "pending_signoff"):
        raise Conflict("not_work_done")

    leiders = [u for u in groups_svc.list_speltakleiders_for_speltak(db, speltak_id) if u.id != scout_id]
    if not leiders:
        raise NotFound("no_eligible_mentors")

    invited: list[User] = []
    for leider in leiders:
        already = db.query(SignoffRequest).filter_by(
            progress_entry_id=entry_id, mentor_id=leider.id
        ).first()
        if already:
            continue
        db.add(SignoffRequest(progress_entry_id=entry_id, mentor_id=leider.id))
        invited.append(leider)

    entry.status = "pending_signoff"
    db.commit()
    db.refresh(entry)
    return entry, invited


def request_signoff_from_members(
    db: Session, scout_id: str, entry_id: str, mentor_ids: list[str]
) -> tuple[ProgressEntry, list[User]]:
    """Request sign-off from selected members (peer sign-off path).

    Raises NotFound("entry_not_found"), Conflict("already_signed_off"),
    Conflict("not_work_done"), NotFound("no_eligible_mentors").
    """
    entry = db.query(ProgressEntry).filter(
        ProgressEntry.id == entry_id,
        ProgressEntry.user_id == scout_id,
    ).first()
    if entry is None:
        raise NotFound("entry_not_found")
    if entry.status == "signed_off":
        raise Conflict("already_signed_off")
    if entry.status not in ("work_done", "pending_signoff"):
        raise Conflict("not_work_done")

    eligible_ids = [mid for mid in mentor_ids if mid != scout_id]
    if not eligible_ids:
        raise NotFound("no_eligible_mentors")

    invited: list[User] = []
    for mentor_id in eligible_ids:
        already = db.query(SignoffRequest).filter_by(
            progress_entry_id=entry_id, mentor_id=mentor_id
        ).first()
        if already:
            continue
        mentor = db.get(User, mentor_id)
        if mentor is None:
            continue
        db.add(SignoffRequest(progress_entry_id=entry_id, mentor_id=mentor_id))
        invited.append(mentor)

    if not invited:
        raise NotFound("no_eligible_mentors")

    entry.status = "pending_signoff"
    db.commit()
    db.refresh(entry)
    return entry, invited


def list_signoff_requests(db: Session, mentor_id: str) -> list[SignoffRequest]:
    return (
        db.query(SignoffRequest)
        .filter(SignoffRequest.mentor_id == mentor_id)
        .join(SignoffRequest.progress_entry)
        .filter(ProgressEntry.status != "signed_off")
        .all()
    )


def list_previous_mentors(db: Session, user_id: str) -> list[User]:
    entries = (
        db.query(ProgressEntry)
        .filter(
            ProgressEntry.user_id == user_id,
            ProgressEntry.signed_off_by_id.isnot(None),
        )
        .order_by(ProgressEntry.signed_off_at.desc())
        .all()
    )
    seen: set[str] = set()
    mentors: list[User] = []
    for entry in entries:
        if entry.signed_off_by_id not in seen:
            seen.add(entry.signed_off_by_id)
            mentors.append(entry.signed_off_by)
    return mentors


# ── Leider progress management ────────────────────────────────────────────────

def list_progress_for_scouts(
    db: Session, scout_ids: list[str]
) -> dict[str, dict[tuple[str, int, int], ProgressEntry]]:
    """Bulk-fetch progress for multiple scouts.
    Returns {user_id: {(badge_slug, level_index, step_index): entry}}.
    """
    if not scout_ids:
        return {}
    entries = db.query(ProgressEntry).filter(
        ProgressEntry.user_id.in_(scout_ids)
    ).all()
    result: dict[str, dict[tuple[str, int, int], ProgressEntry]] = {uid: {} for uid in scout_ids}
    for entry in entries:
        result.setdefault(entry.user_id, {})[(entry.badge_slug, entry.level_index, entry.step_index)] = entry
    return result


def set_scout_progress(
    db: Session,
    *,
    leider_id: str,
    scout_id: str,
    speltak_id: str,
    badge_slug: str,
    level_index: int,
    step_index: int,
    status: str,
    message: str = "",
) -> ProgressEntry | None:
    """Set or clear a scout's progress step on behalf of a leider.

    status must be 'none', 'in_progress', or 'work_done'.
    signed_off entries are editable (clears attribution) to allow leiders to
    correct mistakes. pending_signoff entries raise Conflict.
    """
    from insigne import groups as groups_svc
    from insigne.models import SpeltakMembership

    if status not in ("none", "in_progress", "work_done", "signed_off"):
        raise ValueError("invalid_status")

    leider = db.get(User, leider_id)
    if leider is None or not groups_svc.can_manage_speltak(leider, db, speltak_id):
        raise Forbidden("not_authorized")

    if leider_id == scout_id:
        raise Forbidden("self_edit")

    scout_membership = db.query(SpeltakMembership).filter_by(
        user_id=scout_id, speltak_id=speltak_id, withdrawn=False,
    ).first()
    if scout_membership is None:
        raise Forbidden("scout_not_in_speltak")

    existing = db.query(ProgressEntry).filter_by(
        user_id=scout_id,
        badge_slug=badge_slug,
        level_index=level_index,
        step_index=step_index,
    ).first()

    if status == "none":
        if existing is None:
            return None
        if existing.status == "pending_signoff":
            raise Conflict("pending_signoff")
        db.delete(existing)
        db.commit()
        return None

    if existing:
        if existing.status == "pending_signoff":
            raise Conflict("pending_signoff")
        if existing.status == "signed_off" and status != "signed_off":
            existing.signed_off_by_id = None
            existing.signed_off_at = None
            existing.mentor_comment = None
            leider = db.get(User, leider_id)
            db.add(SignoffRejection(
                progress_entry_id=existing.id,
                mentor_name=leider.name or leider.email,
                message=message,
            ))
        existing.status = status
        if status == "signed_off":
            existing.signed_off_by_id = leider_id
            existing.signed_off_at = datetime.now(timezone.utc)
        db.commit()
        return existing

    entry = ProgressEntry(
        user_id=scout_id,
        badge_slug=badge_slug,
        level_index=level_index,
        step_index=step_index,
        status=status,
        signed_off_by_id=leider_id if status == "signed_off" else None,
        signed_off_at=datetime.now(timezone.utc) if status == "signed_off" else None,
    )
    db.add(entry)
    db.commit()
    return entry

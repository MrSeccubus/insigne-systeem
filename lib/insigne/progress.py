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
    db.query(SignoffRequest).filter(
        SignoffRequest.progress_entry_id == entry_id
    ).delete()
    entry.status = "work_done"

    db.commit()
    db.refresh(entry)
    return entry


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

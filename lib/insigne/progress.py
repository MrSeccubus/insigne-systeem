from datetime import datetime, timezone

from sqlalchemy.orm import Session

from .models import ProgressEntry, SignoffRequest, User


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


def create_progress(
    db: Session,
    user_id: str,
    *,
    badge_slug: str,
    level_index: int,
    step_index: int,
    notes: str | None = None,
) -> ProgressEntry:
    """Log a completed step. Raises Conflict if the step is already completed."""
    existing = db.query(ProgressEntry).filter(
        ProgressEntry.user_id == user_id,
        ProgressEntry.badge_slug == badge_slug,
        ProgressEntry.level_index == level_index,
        ProgressEntry.step_index == step_index,
        ProgressEntry.status == "completed",
    ).first()
    if existing:
        raise Conflict("already_completed")

    entry = ProgressEntry(
        user_id=user_id,
        badge_slug=badge_slug,
        level_index=level_index,
        step_index=step_index,
        notes=notes,
    )
    db.add(entry)
    db.commit()
    return entry


def get_progress(db: Session, user_id: str, entry_id: str) -> ProgressEntry:
    """Raises NotFound if the entry doesn't exist or isn't owned by user_id."""
    entry = db.query(ProgressEntry).filter(
        ProgressEntry.id == entry_id,
        ProgressEntry.user_id == user_id,
    ).first()
    if entry is None:
        raise NotFound("entry_not_found")
    return entry


def update_progress(db: Session, user_id: str, entry_id: str, *, notes: str | None) -> ProgressEntry:
    """Update notes. Raises Forbidden if the entry is already completed."""
    entry = get_progress(db, user_id, entry_id)
    if entry.status == "completed":
        raise Forbidden("entry_completed")
    entry.notes = notes
    db.commit()
    return entry


def delete_progress(db: Session, user_id: str, entry_id: str) -> None:
    """Delete entry. Raises Forbidden if the entry is already completed."""
    entry = get_progress(db, user_id, entry_id)
    if entry.status == "completed":
        raise Forbidden("entry_completed")
    db.delete(entry)
    db.commit()


def request_signoff(
    db: Session, scout_id: str, entry_id: str, mentor_email: str
) -> tuple[ProgressEntry, User, bool]:
    """Invite a mentor to sign off a progress entry.

    Returns (entry, mentor, created) where created=True means the mentor had
    no account and was just created as a pending user.
    Raises NotFound, Conflict("already_completed"), Conflict("already_invited").
    """
    entry = db.query(ProgressEntry).filter(
        ProgressEntry.id == entry_id,
        ProgressEntry.user_id == scout_id,
    ).first()
    if entry is None:
        raise NotFound("entry_not_found")
    if entry.status == "completed":
        raise Conflict("already_completed")

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


def confirm_signoff(db: Session, mentor_id: str, entry_id: str) -> ProgressEntry:
    """Confirm sign-off as the authenticated mentor.

    Marks the entry completed, records the mentor, and removes all pending
    sign-off requests for this entry.
    Raises NotFound, Forbidden("not_invited"), Conflict("already_completed").
    """
    entry = db.query(ProgressEntry).filter(ProgressEntry.id == entry_id).first()
    if entry is None:
        raise NotFound("entry_not_found")
    if entry.status == "completed":
        raise Conflict("already_completed")

    request = db.query(SignoffRequest).filter(
        SignoffRequest.progress_entry_id == entry_id,
        SignoffRequest.mentor_id == mentor_id,
    ).first()
    if request is None:
        raise Forbidden("not_invited")

    entry.status = "completed"
    entry.signed_off_by_id = mentor_id
    entry.signed_off_at = datetime.now(timezone.utc)

    # Remove all sign-off requests for this entry — no longer pending
    db.query(SignoffRequest).filter(
        SignoffRequest.progress_entry_id == entry_id
    ).delete()

    db.commit()
    db.refresh(entry)
    return entry


def list_signoff_requests(db: Session, mentor_id: str) -> list[SignoffRequest]:
    """Return open sign-off requests for the authenticated mentor."""
    return (
        db.query(SignoffRequest)
        .filter(SignoffRequest.mentor_id == mentor_id)
        .join(SignoffRequest.progress_entry)
        .filter(ProgressEntry.status != "completed")
        .all()
    )


def list_previous_mentors(db: Session, user_id: str) -> list[User]:
    """Return deduplicated mentors who signed off this scout, most recent first."""
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

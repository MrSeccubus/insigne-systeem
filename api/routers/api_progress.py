from pathlib import Path

from fastapi import APIRouter, Depends, Response
from fastapi import HTTPException
from sqlalchemy.orm import Session

from insigne import progress as progress_svc
from insigne.badges import get_badge
from insigne.database import get_db
from insigne.email import send_mentor_signoff_invite_email, send_mentor_signoff_request_email
from insigne.models import ProgressEntry, SignoffRequest, User

_DATA_DIR = Path(__file__).parent.parent / "data"

from deps import get_current_user
from schemas import (
    CreateProgressRequest,
    MentorResponse,
    ProgressEntryResponse,
    RequestSignoffRequest,
    SignoffRequestResponse,
    UpdateProgressRequest,
    UserRefResponse,
)

router = APIRouter(tags=["progress"])


def _entry_response(entry: ProgressEntry) -> ProgressEntryResponse:
    return ProgressEntryResponse(
        id=entry.id,
        badge_slug=entry.badge_slug,
        level_index=entry.level_index,
        step_index=entry.step_index,
        notes=entry.notes,
        status=entry.status,
        pending_mentors=[
            UserRefResponse(user_id=sr.mentor.id, name=sr.mentor.name)
            for sr in entry.signoff_requests
        ],
        signed_off_by=(
            UserRefResponse(user_id=entry.signed_off_by.id, name=entry.signed_off_by.name)
            if entry.signed_off_by else None
        ),
        signed_off_at=entry.signed_off_at,
        created_at=entry.created_at,
    )


# Must be defined before /progress/{id} to avoid route shadowing
@router.get("/progress/mentors", response_model=list[MentorResponse])
async def get_previous_mentors(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    mentors = progress_svc.list_previous_mentors(db, current_user.id)
    return [MentorResponse(user_id=m.id, name=m.name) for m in mentors]


@router.get("/progress", response_model=list[ProgressEntryResponse])
async def list_progress(
    badge_slug: str | None = None,
    status: str | None = None,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    entries = progress_svc.list_progress(db, current_user.id, badge_slug=badge_slug, status=status)
    return [_entry_response(e) for e in entries]


@router.post("/progress", response_model=ProgressEntryResponse, status_code=201)
async def create_progress(
    body: CreateProgressRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    try:
        entry = progress_svc.create_progress(
            db, current_user.id,
            badge_slug=body.badge_slug,
            level_index=body.level_index,
            step_index=body.step_index,
            notes=body.notes,
        )
    except progress_svc.Conflict:
        raise HTTPException(status_code=409, detail="This step is already completed.")
    return _entry_response(entry)


@router.get("/progress/{entry_id}", response_model=ProgressEntryResponse)
async def get_progress(
    entry_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    try:
        entry = progress_svc.get_progress(db, current_user.id, entry_id)
    except progress_svc.NotFound:
        raise HTTPException(status_code=404, detail="Progress entry not found.")
    return _entry_response(entry)


@router.put("/progress/{entry_id}", response_model=ProgressEntryResponse)
async def update_progress(
    entry_id: str,
    body: UpdateProgressRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    try:
        entry = progress_svc.update_progress(db, current_user.id, entry_id, notes=body.notes)
    except progress_svc.NotFound:
        raise HTTPException(status_code=404, detail="Progress entry not found.")
    except progress_svc.Forbidden:
        raise HTTPException(status_code=403, detail="Completed entries cannot be edited.")
    return _entry_response(entry)


@router.delete("/progress/{entry_id}", status_code=204)
async def delete_progress(
    entry_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    try:
        progress_svc.delete_progress(db, current_user.id, entry_id)
    except progress_svc.NotFound:
        raise HTTPException(status_code=404, detail="Progress entry not found.")
    except progress_svc.Forbidden:
        raise HTTPException(status_code=403, detail="Completed entries cannot be deleted.")
    return Response(status_code=204)


@router.post("/progress/{entry_id}/signoff", status_code=202)
async def request_signoff(
    entry_id: str,
    body: RequestSignoffRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    try:
        entry, mentor, created = progress_svc.request_signoff(
            db, current_user.id, entry_id, body.mentor_email
        )
    except progress_svc.NotFound:
        raise HTTPException(status_code=404, detail="Progress entry not found.")
    except progress_svc.Conflict as exc:
        detail = (
            "This step is already completed."
            if str(exc) == "already_signed_off"
            else "This mentor has already been invited."
        )
        raise HTTPException(status_code=409, detail=detail)

    badge = get_badge(_DATA_DIR, entry.badge_slug)
    level = badge["levels"][entry.level_index]
    step_text = level["steps"][entry.step_index]["text"]
    scout_name = current_user.name or current_user.email.split("@")[0]
    if created:
        send_mentor_signoff_invite_email(mentor.email, scout_name, badge["title"], entry.step_index + 1, step_text, notes=entry.notes)
    else:
        send_mentor_signoff_request_email(mentor.email, scout_name, badge["title"], entry.step_index + 1, step_text, notes=entry.notes)
    return {"detail": "Sign-off request sent."}


@router.post("/progress/{entry_id}/signoff/confirm", response_model=ProgressEntryResponse)
async def confirm_signoff(
    entry_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    try:
        entry = progress_svc.confirm_signoff(db, current_user.id, entry_id)
    except progress_svc.NotFound:
        raise HTTPException(status_code=404, detail="Progress entry not found.")
    except progress_svc.Forbidden:
        raise HTTPException(status_code=403, detail="You have not been invited to sign off this entry.")
    except progress_svc.Conflict:
        raise HTTPException(status_code=409, detail="This entry has already been signed off.")
    return _entry_response(entry)


@router.get("/signoff-requests", response_model=list[SignoffRequestResponse])
async def list_signoff_requests(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    requests = progress_svc.list_signoff_requests(db, current_user.id)
    return [
        SignoffRequestResponse(
            id=sr.progress_entry.id,
            scout=UserRefResponse(user_id=sr.progress_entry.user.id, name=sr.progress_entry.user.name),
            badge_slug=sr.progress_entry.badge_slug,
            level_index=sr.progress_entry.level_index,
            step_index=sr.progress_entry.step_index,
            notes=sr.progress_entry.notes,
            status=sr.progress_entry.status,
            created_at=sr.progress_entry.created_at,
        )
        for sr in requests
    ]

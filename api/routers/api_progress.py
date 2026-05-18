from pathlib import Path

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Response
from sqlalchemy.orm import Session

from insigne import jaarinsigne_2026 as jaarinsigne_2026_svc
from insigne import progress as progress_svc
from insigne.badges import BadgeCatalogue
from insigne.database import get_db
from insigne.email import (
    send_mentor_jaarinsigne_signoff_invite_email,
    send_mentor_jaarinsigne_signoff_request_email,
    send_mentor_signoff_invite_email,
    send_mentor_signoff_request_email,
    send_scout_jaarinsigne_rejected_email,
    send_scout_jaarinsigne_signed_off_email,
)
from insigne.models import ProgressEntry, SignoffRequest, User

_CATALOGUE = BadgeCatalogue(Path(__file__).parent.parent / "data")

from deps import get_current_user
from schemas import (
    CreateProgressRequest,
    Jaarinsigne2026ConfirmSignoffRequest,
    Jaarinsigne2026InclusionRefResponse,
    Jaarinsigne2026InclusionResponse,
    Jaarinsigne2026RejectSignoffRequest,
    Jaarinsigne2026RequestSignoffMembersRequest,
    Jaarinsigne2026RequestSignoffRequest,
    Jaarinsigne2026RequestSignoffSpeltakRequest,
    Jaarinsigne2026ScoreDetailResponse,
    Jaarinsigne2026ScoreSummaryResponse,
    Jaarinsigne2026ToggleInclusionRequest,
    Jaarinsigne2026ToggleInclusionResponse,
    MentorResponse,
    ProgressEntryResponse,
    RequestSignoffMembersRequest,
    RequestSignoffRequest,
    RequestSignoffSpeltakRequest,
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
    background_tasks: BackgroundTasks,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    try:
        entry, mentor, created = progress_svc.request_signoff(
            db, current_user.id, entry_id, body.mentor_email
        )
    except progress_svc.NotFound:
        raise HTTPException(status_code=404, detail="Progress entry not found.")
    except progress_svc.Forbidden as exc:
        if str(exc) == "self_signoff":
            raise HTTPException(status_code=403, detail="You cannot invite yourself to sign off.")
        raise HTTPException(status_code=403, detail="Forbidden.")
    except progress_svc.Conflict as exc:
        if str(exc) == "already_signed_off":
            detail = "This step is already completed."
        elif str(exc) == "invalid_email":
            raise HTTPException(status_code=422, detail="Invalid e-mail address.")
        else:
            detail = "This mentor has already been invited."
        raise HTTPException(status_code=409, detail=detail)

    badge = _CATALOGUE.get(entry.badge_slug)
    level = badge["levels"][entry.level_index]
    step_text = level["steps"][entry.step_index]["text"]
    scout_name = current_user.name or current_user.email.split("@")[0]
    if created:
        background_tasks.add_task(send_mentor_signoff_invite_email, mentor.email, scout_name, badge["title"], entry.step_index + 1, step_text, notes=entry.notes)
    else:
        background_tasks.add_task(send_mentor_signoff_request_email, mentor.email, scout_name, badge["title"], entry.step_index + 1, step_text, notes=entry.notes)
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


@router.post("/progress/{entry_id}/signoff-speltak", status_code=202)
async def request_signoff_speltak(
    entry_id: str,
    body: RequestSignoffSpeltakRequest,
    background_tasks: BackgroundTasks,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    try:
        entry, invited = progress_svc.request_signoff_for_speltak(
            db, current_user.id, entry_id, body.speltak_id
        )
    except progress_svc.NotFound as exc:
        detail = "No eligible mentors found." if str(exc) == "no_eligible_mentors" else "Progress entry not found."
        raise HTTPException(status_code=404, detail=detail)
    except progress_svc.Forbidden:
        raise HTTPException(status_code=403, detail="You are not a member of that speltak.")
    except progress_svc.Conflict as exc:
        detail = "This step is already completed." if str(exc) == "already_signed_off" else "Entry is not in work_done status."
        raise HTTPException(status_code=409, detail=detail)

    badge = _CATALOGUE.get(entry.badge_slug)
    level = badge["levels"][entry.level_index]
    step_text = level["steps"][entry.step_index]["text"]
    scout_name = current_user.name or current_user.email.split("@")[0]
    for mentor in invited:
        background_tasks.add_task(send_mentor_signoff_request_email, mentor.email, scout_name, badge["title"], entry.step_index + 1, step_text, notes=entry.notes)
    return {"detail": "Sign-off requests sent."}


@router.post("/progress/{entry_id}/signoff-members", status_code=202)
async def request_signoff_members(
    entry_id: str,
    body: RequestSignoffMembersRequest,
    background_tasks: BackgroundTasks,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    try:
        entry, invited = progress_svc.request_signoff_from_members(
            db, current_user.id, entry_id, body.mentor_ids
        )
    except progress_svc.NotFound as exc:
        detail = "No eligible mentors found." if str(exc) == "no_eligible_mentors" else "Progress entry not found."
        raise HTTPException(status_code=404, detail=detail)
    except progress_svc.Conflict as exc:
        detail = "This step is already completed." if str(exc) == "already_signed_off" else "Entry is not in work_done status."
        raise HTTPException(status_code=409, detail=detail)

    badge = _CATALOGUE.get(entry.badge_slug)
    level = badge["levels"][entry.level_index]
    step_text = level["steps"][entry.step_index]["text"]
    scout_name = current_user.name or current_user.email.split("@")[0]
    for mentor in invited:
        background_tasks.add_task(send_mentor_signoff_request_email, mentor.email, scout_name, badge["title"], entry.step_index + 1, step_text, notes=entry.notes)
    return {"detail": "Sign-off requests sent."}


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


# ── Per-scout progress (leider view) ─────────────────────────────────────────

from insigne import groups as groups_svc
from schemas import JaarinsigneLevelResponse, SetScoutProgressRequest, UserResponse


@router.get("/scouts/{scout_id}/progress", response_model=list[ProgressEntryResponse])
async def get_scout_progress(
    scout_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """List all progress entries for a scout. Requires view access."""
    if scout_id == current_user.id:
        raise HTTPException(status_code=400, detail="Use /api/progress to view your own progress.")
    scout = db.get(User, scout_id)
    if scout is None:
        raise HTTPException(status_code=404, detail="Scout not found.")
    if not groups_svc.can_view_scout_progress(current_user, db, scout_id):
        raise HTTPException(status_code=403, detail="Not authorized to view this scout's progress.")
    entries = progress_svc.list_progress(db, scout_id)
    return [_entry_response(e) for e in entries]


@router.post("/scouts/{scout_id}/set-progress", response_model=ProgressEntryResponse | None)
async def api_scout_set_progress(
    scout_id: str,
    body: SetScoutProgressRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Set progress for a scout. Requires speltakleider edit rights (not groepsleider/admin)."""
    if scout_id == current_user.id:
        raise HTTPException(status_code=400, detail="Cannot edit your own progress via this endpoint.")
    edit_speltak_id = groups_svc.get_edit_speltak_for_scout(db, current_user.id, scout_id)
    if edit_speltak_id is None:
        raise HTTPException(status_code=403, detail="Not authorized to edit this scout's progress.")
    try:
        entry = progress_svc.set_scout_progress(
            db, leider_id=current_user.id, scout_id=scout_id,
            speltak_id=edit_speltak_id, badge_slug=body.badge_slug,
            level_index=body.level_index, step_index=body.step_index,
            status=body.status, message=body.message.strip(),
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    except progress_svc.Forbidden as exc:
        raise HTTPException(status_code=403, detail=str(exc))
    except progress_svc.Conflict as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    return _entry_response(entry) if entry else None


# ── Jaarinsigne level ─────────────────────────────────────────────────────────

_VALID_SPELTAK_SLUGS = {"bevers", "welpen", "scouts", "explorers", "roverscouts", "plusscouts"}


def _level_response(jl) -> JaarinsigneLevelResponse:
    return JaarinsigneLevelResponse(
        user_id=jl.user_id,
        badge_slug=jl.badge_slug,
        speltak_slug=jl.speltak_slug,
        set_by_user_id=jl.set_by_user_id,
    )


@router.post("/badges/{slug}/set-level", response_model=JaarinsigneLevelResponse)
async def api_set_own_jaarinsigne_level(
    slug: str,
    speltak_slug: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Set the jaarinsigne level (speltak variant) for the current user.

    Only allowed when the user's primary speltak is peer_signoff or the user
    is speltakleider of their primary speltak.
    """
    badge = _CATALOGUE.get(slug)
    if badge is None or badge.get("type") != "jaarinsigne":
        raise HTTPException(status_code=404, detail="Jaarinsigne badge not found.")
    valid_slugs = {lvl["slug"] for lvl in badge["levels"]}
    if speltak_slug not in valid_slugs:
        raise HTTPException(status_code=422, detail="Invalid speltak_slug for this badge.")
    if not groups_svc.can_user_set_own_jaarinsigne_level(db, current_user.id):
        raise HTTPException(status_code=403, detail="Not allowed to set own jaarinsigne level.")
    jl = progress_svc.set_jaarinsigne_level(db, current_user.id, slug, speltak_slug, current_user.id)
    return _level_response(jl)


@router.post("/scouts/{scout_id}/badges/{slug}/set-level", response_model=JaarinsigneLevelResponse)
async def api_set_scout_jaarinsigne_level(
    scout_id: str,
    slug: str,
    speltak_slug: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Set the jaarinsigne level (speltak variant) for a scout. Requires speltakleider edit rights."""
    if scout_id == current_user.id:
        raise HTTPException(status_code=400, detail="Use /api/badges/{slug}/set-level for your own level.")
    scout = db.get(User, scout_id)
    if scout is None:
        raise HTTPException(status_code=404, detail="Scout not found.")
    if not groups_svc.get_edit_speltak_for_scout(db, current_user.id, scout_id):
        raise HTTPException(status_code=403, detail="Not authorized to edit this scout's jaarinsigne level.")
    badge = _CATALOGUE.get(slug)
    if badge is None or badge.get("type") != "jaarinsigne":
        raise HTTPException(status_code=404, detail="Jaarinsigne badge not found.")
    valid_slugs = {lvl["slug"] for lvl in badge["levels"]}
    if speltak_slug not in valid_slugs:
        raise HTTPException(status_code=422, detail="Invalid speltak_slug for this badge.")
    jl = progress_svc.set_jaarinsigne_level(db, scout_id, slug, speltak_slug, current_user.id)
    return _level_response(jl)


# ── Jaarinsigne 2026 (meta-insigne) ───────────────────────────────────────────


def _ji26_inclusion_response(item: dict) -> Jaarinsigne2026InclusionResponse:
    return Jaarinsigne2026InclusionResponse(
        badge_slug=item["badge_slug"],
        badge_title=item["badge_title"],
        level_index=item["level_index"],
        step_index=item["step_index"],
        punten=item["punten"],
        groen=item["groen"],
        step_text=item["step_text"],
    )


def _ji26_score_response(summary: dict) -> Jaarinsigne2026ScoreSummaryResponse:
    score = summary["score"]
    return Jaarinsigne2026ScoreSummaryResponse(
        speltak_slug=summary.get("speltak_slug"),
        speltak_min_punten=summary.get("speltak_min_punten", 3),
        score=Jaarinsigne2026ScoreDetailResponse(
            total_punten=score["total_punten"],
            total_groen=score["total_groen"],
            total_niveau2=score["total_niveau2"],
            total_niveau3=score["total_niveau3"],
            distinct_insignes=score["distinct_insignes"],
            inclusions=[
                Jaarinsigne2026InclusionRefResponse(**inc)
                for inc in score.get("inclusions", [])
            ],
        ),
        eis_statuses=summary.get("eis_statuses", {}),
        available_punten=summary.get("available_punten", 0),
    )


def _ji26_jaarinsigne_eisen(level: dict | None, entries: list[ProgressEntry]) -> list[dict]:
    """Build the per-eis dict list for the jaarinsigne_2026 e-mail templates."""
    if not level:
        return []
    sorted_entries = sorted(entries, key=lambda e: e.step_index)
    out: list[dict] = []
    for e in sorted_entries:
        if e.step_index >= len(level["steps"]):
            continue
        step = level["steps"][e.step_index]
        out.append({
            "number": e.step_index + 1,
            "titel": step.get("titel", ""),
            "text": step.get("text", ""),
        })
    return out


@router.get(
    "/users/me/jaarinsigne_2026/score",
    response_model=Jaarinsigne2026ScoreSummaryResponse,
)
async def jaarinsigne_2026_get_score(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Score summary for the current user against their jaarinsigne_2026 speltak drempels."""
    speltak_slug, speltak_min_punten = jaarinsigne_2026_svc.resolve_user_level(db, current_user.id)
    if speltak_slug is None:
        raise HTTPException(status_code=404, detail="No speltak level resolved for this user.")
    summary = jaarinsigne_2026_svc.get_score_summary(
        db, current_user.id, speltak_slug, speltak_min_punten,
    )
    return _ji26_score_response(summary)


@router.get(
    "/users/me/jaarinsigne_2026/inclusions",
    response_model=list[Jaarinsigne2026InclusionResponse],
)
async def jaarinsigne_2026_list_inclusions(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Current user's selected jaarinsigne_2026 inclusions, sorted by badges.yml order."""
    details = jaarinsigne_2026_svc.get_included_details(db, current_user.id)
    return [_ji26_inclusion_response(item) for item in details]


@router.get(
    "/users/me/jaarinsigne_2026/inclusions/available",
    response_model=list[Jaarinsigne2026InclusionResponse],
)
async def jaarinsigne_2026_list_available(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Signed-off eisen of eligible (gewoon/buitengewoon) badges not yet included."""
    items = jaarinsigne_2026_svc.get_available_to_include(db, current_user.id)
    return [_ji26_inclusion_response(item) for item in items]


@router.post(
    "/users/me/jaarinsigne_2026/inclusions/toggle",
    response_model=Jaarinsigne2026ToggleInclusionResponse,
)
async def jaarinsigne_2026_toggle_inclusion(
    body: Jaarinsigne2026ToggleInclusionRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Flip an inclusion on or off. Refuses while a signoff request is pending."""
    eligible_slugs = {b["slug"] for b in jaarinsigne_2026_svc.get_eligible_badges()}
    if body.badge_slug not in eligible_slugs:
        raise HTTPException(status_code=422, detail="badge_slug is not in eligible categories")

    entry = db.query(ProgressEntry).filter_by(
        user_id=current_user.id,
        badge_slug=body.badge_slug,
        level_index=body.level_index,
        step_index=body.step_index,
    ).first()
    if entry is None or entry.status != "signed_off":
        raise HTTPException(
            status_code=409,
            detail="Eis is not signed_off; cannot toggle inclusion.",
        )

    speltak_slug, speltak_min_punten = jaarinsigne_2026_svc.resolve_user_level(db, current_user.id)
    badge = _CATALOGUE.get("jaarinsigne_2026")
    level = next((lv for lv in badge["levels"] if lv["slug"] == speltak_slug), None) \
        if (badge and speltak_slug) else None
    from routers.html_badges import _jaarinsigne_2026_signoff_state
    if _jaarinsigne_2026_signoff_state(db, current_user.id, level) == "pending":
        raise HTTPException(
            status_code=409,
            detail="Cannot edit inclusions while a sign-off request is pending. Revoke first.",
        )

    included = jaarinsigne_2026_svc.toggle_inclusion(
        db, current_user.id, body.badge_slug, body.level_index, body.step_index,
    )
    if speltak_slug:
        jaarinsigne_2026_svc.update_progress_entries(
            db, current_user.id, speltak_slug, speltak_min_punten,
        )

    return Jaarinsigne2026ToggleInclusionResponse(
        badge_slug=body.badge_slug,
        level_index=body.level_index,
        step_index=body.step_index,
        included=included,
    )


def _ji26_send_request_emails(
    background_tasks: BackgroundTasks,
    invited: list[User],
    created_mentor: User | None,
    scout_name: str,
    badge: dict | None,
    level: dict | None,
    eisen: list[dict],
):
    if badge is None or level is None or not eisen:
        return
    speltak_name = level.get("name", "")
    speltak_leeftijd = level.get("leeftijd", "")
    for mentor in invited:
        if not mentor.email:
            continue
        fn = (send_mentor_jaarinsigne_signoff_invite_email
              if created_mentor is not None and mentor.id == created_mentor.id
              else send_mentor_jaarinsigne_signoff_request_email)
        background_tasks.add_task(
            fn, mentor.email, scout_name, badge["slug"], badge["title"],
            speltak_name, speltak_leeftijd, eisen, None,
        )


@router.post(
    "/users/me/jaarinsigne_2026/signoff/speltak",
    response_model=list[ProgressEntryResponse],
    status_code=202,
)
async def jaarinsigne_2026_request_signoff_speltak(
    body: Jaarinsigne2026RequestSignoffSpeltakRequest,
    background_tasks: BackgroundTasks,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Request batch sign-off from every leider of the given speltak."""
    try:
        entries, invited = progress_svc.request_jaarinsigne_2026_signoff_speltak(
            db, current_user.id, body.speltak_id,
        )
    except progress_svc.NotFound as exc:
        if str(exc) == "no_eligible_mentors":
            raise HTTPException(status_code=404, detail="No eligible mentors for that speltak.")
        raise HTTPException(status_code=409, detail="No eisen ready for sign-off.")
    except progress_svc.Forbidden:
        raise HTTPException(status_code=403, detail="Forbidden.")
    except progress_svc.Conflict:
        raise HTTPException(status_code=409, detail="Conflict.")

    badge = _CATALOGUE.get("jaarinsigne_2026")
    speltak_slug, _ = jaarinsigne_2026_svc.resolve_user_level(db, current_user.id)
    level = next((lv for lv in badge["levels"] if lv["slug"] == speltak_slug), None) \
        if (badge and speltak_slug) else None
    _ji26_send_request_emails(
        background_tasks, invited, None,
        current_user.name or current_user.email.split("@")[0],
        badge, level, _ji26_jaarinsigne_eisen(level, entries),
    )
    return [_entry_response(e) for e in entries]


@router.post(
    "/users/me/jaarinsigne_2026/signoff/members",
    response_model=list[ProgressEntryResponse],
    status_code=202,
)
async def jaarinsigne_2026_request_signoff_members(
    body: Jaarinsigne2026RequestSignoffMembersRequest,
    background_tasks: BackgroundTasks,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Request batch sign-off from selected peer members."""
    try:
        entries, invited = progress_svc.request_jaarinsigne_2026_signoff_members(
            db, current_user.id, body.mentor_ids,
        )
    except progress_svc.NotFound as exc:
        if str(exc) == "no_eligible_mentors":
            raise HTTPException(status_code=404, detail="No eligible mentors.")
        raise HTTPException(status_code=409, detail="No eisen ready for sign-off.")
    except progress_svc.Forbidden:
        raise HTTPException(status_code=403, detail="Forbidden.")
    except progress_svc.Conflict:
        raise HTTPException(status_code=409, detail="Conflict.")

    badge = _CATALOGUE.get("jaarinsigne_2026")
    speltak_slug, _ = jaarinsigne_2026_svc.resolve_user_level(db, current_user.id)
    level = next((lv for lv in badge["levels"] if lv["slug"] == speltak_slug), None) \
        if (badge and speltak_slug) else None
    _ji26_send_request_emails(
        background_tasks, invited, None,
        current_user.name or current_user.email.split("@")[0],
        badge, level, _ji26_jaarinsigne_eisen(level, entries),
    )
    return [_entry_response(e) for e in entries]


@router.post(
    "/users/me/jaarinsigne_2026/signoff",
    response_model=list[ProgressEntryResponse],
    status_code=202,
)
async def jaarinsigne_2026_request_signoff_direct(
    body: Jaarinsigne2026RequestSignoffRequest,
    background_tasks: BackgroundTasks,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Request batch sign-off from a single mentor by e-mail (auto-creates the User if absent)."""
    try:
        entries, mentor, created = progress_svc.request_jaarinsigne_2026_signoff(
            db, current_user.id, body.mentor_email,
        )
    except progress_svc.Forbidden as exc:
        if str(exc) == "self_signoff":
            raise HTTPException(status_code=403, detail="You cannot invite yourself.")
        raise HTTPException(status_code=403, detail="Forbidden.")
    except progress_svc.NotFound:
        raise HTTPException(status_code=409, detail="No eisen ready for sign-off.")
    except progress_svc.Conflict as exc:
        if str(exc) == "invalid_email":
            raise HTTPException(status_code=422, detail="Invalid e-mail address.")
        raise HTTPException(status_code=409, detail="Conflict.")

    badge = _CATALOGUE.get("jaarinsigne_2026")
    speltak_slug, _ = jaarinsigne_2026_svc.resolve_user_level(db, current_user.id)
    level = next((lv for lv in badge["levels"] if lv["slug"] == speltak_slug), None) \
        if (badge and speltak_slug) else None
    _ji26_send_request_emails(
        background_tasks, [mentor], mentor if created else None,
        current_user.name or current_user.email.split("@")[0],
        badge, level, _ji26_jaarinsigne_eisen(level, entries),
    )
    return [_entry_response(e) for e in entries]


@router.delete(
    "/users/me/jaarinsigne_2026/signoff",
    response_model=list[ProgressEntryResponse],
)
async def jaarinsigne_2026_cancel_signoff(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Revoke every pending jaarinsigne_2026 sign-off request for the current user."""
    affected = progress_svc.cancel_jaarinsigne_2026_signoff_requests(db, current_user.id)
    return [_entry_response(e) for e in affected]


@router.post(
    "/scouts/{scout_id}/jaarinsigne_2026/confirm-signoff",
    response_model=list[ProgressEntryResponse],
)
async def jaarinsigne_2026_confirm_signoff(
    scout_id: str,
    body: Jaarinsigne2026ConfirmSignoffRequest,
    background_tasks: BackgroundTasks,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Mentor confirms every jaarinsigne_2026 eis the scout invited them for."""
    try:
        affected = progress_svc.confirm_jaarinsigne_2026_signoff(
            db, current_user.id, scout_id, comment=(body.comment or None),
        )
    except progress_svc.Forbidden as exc:
        if str(exc) == "self_signoff":
            raise HTTPException(status_code=403, detail="Cannot sign off your own jaarinsigne.")
        raise HTTPException(status_code=403, detail="Not invited.")
    except progress_svc.Conflict:
        raise HTTPException(status_code=409, detail="Already signed off.")
    except progress_svc.NotFound:
        raise HTTPException(status_code=404, detail="Not found.")

    scout = db.get(User, scout_id)
    badge = _CATALOGUE.get("jaarinsigne_2026")
    if scout and scout.email and affected and badge:
        level = badge["levels"][affected[0].level_index]
        eisen = _ji26_jaarinsigne_eisen(level, affected)
        mentor_comment = next((e.mentor_comment for e in affected if e.mentor_comment), None)
        background_tasks.add_task(
            send_scout_jaarinsigne_signed_off_email,
            scout.email, scout.name or scout.email,
            badge["slug"], badge["title"],
            level.get("name", ""), level.get("leeftijd", ""),
            eisen,
            current_user.name or current_user.email,
            mentor_comment,
        )
    return [_entry_response(e) for e in affected]


@router.post(
    "/scouts/{scout_id}/jaarinsigne_2026/reject-signoff",
    response_model=list[ProgressEntryResponse],
)
async def jaarinsigne_2026_reject_signoff(
    scout_id: str,
    body: Jaarinsigne2026RejectSignoffRequest,
    background_tasks: BackgroundTasks,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Mentor rejects every jaarinsigne_2026 eis the scout invited them for."""
    try:
        affected = progress_svc.reject_jaarinsigne_2026_signoff(
            db, current_user.id, scout_id, body.message.strip(),
        )
    except progress_svc.Forbidden as exc:
        if str(exc) == "self_signoff":
            raise HTTPException(status_code=403, detail="Cannot reject your own jaarinsigne.")
        raise HTTPException(status_code=403, detail="Not invited.")
    except progress_svc.NotFound:
        raise HTTPException(status_code=404, detail="Not found.")

    scout = db.get(User, scout_id)
    badge = _CATALOGUE.get("jaarinsigne_2026")
    if scout and scout.email and affected and badge:
        level = badge["levels"][affected[0].level_index]
        eisen = _ji26_jaarinsigne_eisen(level, affected)
        background_tasks.add_task(
            send_scout_jaarinsigne_rejected_email,
            scout.email, scout.name or scout.email,
            badge["slug"], badge["title"],
            level.get("name", ""), level.get("leeftijd", ""),
            eisen,
            current_user.name or current_user.email,
            body.message.strip(),
        )
    return [_entry_response(e) for e in affected]

from pathlib import Path

from fastapi import APIRouter, BackgroundTasks, Depends, Form, Query, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.orm import Session

from insigne import progress as progress_svc
from insigne.badges import get_badge
from insigne.database import get_db
from insigne.email import (
    send_mentor_signoff_invite_email,
    send_mentor_signoff_request_email,
    send_scout_niveau_completed_email,
    send_scout_rejected_email,
    send_scout_signed_off_email,
)
from insigne.models import ProgressEntry

from routers.users import _get_current_user
from templates import templates as _TEMPLATES

router = APIRouter()

_DATA_DIR = Path(__file__).parent.parent / "data"


def _partial(request: Request, name: str, **ctx):
    return _TEMPLATES.TemplateResponse(request=request, name=f"partials/{name}", context=ctx)


def _step_card(request, slug, level_index, level_name, step_index, step_text, entry, previous_mentors=None, error="", current_user=None):
    response = _partial(
        request, "step_card.html",
        slug=slug,
        level_index=level_index,
        level_name=level_name,
        step_index=step_index,
        step_text=step_text,
        entry=entry,
        previous_mentors=previous_mentors or [],
        error=error,
        current_user=current_user,
    )
    response.headers["HX-Trigger"] = "niveau-updated"
    return response


# ── Niveau progress checks (HTMX partial) ────────────────────────────────────

@router.get("/badges/{slug}/niveau-checks/{niveau_index}", response_class=HTMLResponse)
async def niveau_checks(request: Request, slug: str, niveau_index: int, db: Session = Depends(get_db)):
    current_user = _get_current_user(request, db)
    badge = get_badge(_DATA_DIR, slug)
    if badge is None:
        return HTMLResponse("")

    progress_map: dict[tuple[int, int], ProgressEntry] = {}
    if current_user:
        for entry in progress_svc.list_progress(db, current_user.id, badge_slug=slug):
            progress_map[(entry.level_index, entry.step_index)] = entry

    return _partial(
        request, "niveau_checks.html",
        slug=slug,
        niveau_index=niveau_index,
        n_eisen=len(badge["levels"]),
        progress_map=progress_map,
        style=None,
    )


# ── Badge detail ──────────────────────────────────────────────────────────────

@router.get("/badges/{slug}", response_class=HTMLResponse)
async def badge_detail(request: Request, slug: str, niveau: int | None = Query(None), db: Session = Depends(get_db)):
    current_user = _get_current_user(request, db)
    badge = get_badge(_DATA_DIR, slug)
    if badge is None:
        return RedirectResponse(url="/", status_code=303)

    progress_map: dict[tuple[int, int], ProgressEntry] = {}
    previous_mentors = []
    level_stats = []

    if current_user:
        for entry in progress_svc.list_progress(db, current_user.id, badge_slug=slug):
            progress_map[(entry.level_index, entry.step_index)] = entry
        previous_mentors = progress_svc.list_previous_mentors(db, current_user.id)

    n_eisen = len(badge["levels"])
    for i, level in enumerate(badge["levels"]):
        total = len(level["steps"])
        completed = sum(
            1 for step in level["steps"]
            if progress_map.get((i, step["index"])) and
               progress_map[(i, step["index"])].status == "signed_off"
        )
        level_stats.append({"completed": completed, "total": total})

    # Per-niveau: how many of the 5 eisen are completed at each niveau
    niveau_stats = [
        {
            "completed": sum(
                1 for eis_idx in range(n_eisen)
                if progress_map.get((eis_idx, niveau_idx)) and
                   progress_map[(eis_idx, niveau_idx)].status == "signed_off"
            ),
            "total": n_eisen,
        }
        for niveau_idx in range(3)
    ]

    return _TEMPLATES.TemplateResponse(
        request=request,
        name="badge.html",
        context={
            "current_user": current_user,
            "badge": badge,
            "progress_map": progress_map,
            "previous_mentors": previous_mentors,
            "level_stats": level_stats,
            "niveau_stats": niveau_stats,
            "selected_niveaus": [niveau - 1] if niveau in (1, 2, 3) else [0, 1, 2],
        },
    )


# ── Log a step ────────────────────────────────────────────────────────────────

@router.post("/badges/{slug}/log", response_class=HTMLResponse)
async def log_step(
    request: Request,
    slug: str,
    level_index: int = Form(...),
    step_index: int = Form(...),
    status: str = Form("in_progress"),
    notes: str = Form(""),
    db: Session = Depends(get_db),
):
    current_user = _get_current_user(request, db)
    if current_user is None:
        return RedirectResponse(url="/login", status_code=303)

    badge = get_badge(_DATA_DIR, slug)
    if (badge is None
            or not (0 <= level_index < len(badge["levels"]))
            or not (0 <= step_index < len(badge["levels"][level_index]["steps"]))):
        return RedirectResponse(url="/", status_code=303)
    level = badge["levels"][level_index]
    step_text = level["steps"][step_index]["text"]
    previous_mentors = progress_svc.list_previous_mentors(db, current_user.id)

    if status not in ("in_progress", "work_done"):
        status = "in_progress"

    try:
        entry = progress_svc.log_progress(
            db, current_user.id,
            badge_slug=slug,
            level_index=level_index,
            step_index=step_index,
            status=status,
            notes=notes.strip() or None,
        )
    except progress_svc.Conflict:
        entry = db.query(ProgressEntry).filter(
            ProgressEntry.user_id == current_user.id,
            ProgressEntry.badge_slug == slug,
            ProgressEntry.level_index == level_index,
            ProgressEntry.step_index == step_index,
        ).first()

    return _step_card(request, slug, level_index, level["name"], step_index, step_text, entry, previous_mentors, current_user=current_user)


# ── Request sign-off ──────────────────────────────────────────────────────────

@router.post("/progress/{entry_id}/request-signoff", response_class=HTMLResponse)
async def request_signoff(
    request: Request,
    entry_id: str,
    background_tasks: BackgroundTasks,
    mentor_email: str = Form(...),
    notes: str = Form(""),
    db: Session = Depends(get_db),
):
    current_user = _get_current_user(request, db)
    if current_user is None:
        return RedirectResponse(url="/login", status_code=303)

    entry = db.query(ProgressEntry).filter(
        ProgressEntry.id == entry_id,
        ProgressEntry.user_id == current_user.id,
    ).first()
    if entry is None:
        return RedirectResponse(url="/", status_code=303)

    if entry.status not in ("pending_signoff", "signed_off"):
        entry.notes = notes.strip() or None
        db.commit()

    badge = get_badge(_DATA_DIR, entry.badge_slug)
    level = badge["levels"][entry.level_index]
    step_text = level["steps"][entry.step_index]["text"]
    previous_mentors = progress_svc.list_previous_mentors(db, current_user.id)

    error = ""
    try:
        entry, mentor, created = progress_svc.request_signoff(db, current_user.id, entry_id, mentor_email)
        scout_name = current_user.name or current_user.email.split("@")[0]
        if created:
            background_tasks.add_task(send_mentor_signoff_invite_email, mentor.email, scout_name, badge["title"], entry.step_index + 1, step_text, notes=entry.notes)
        else:
            background_tasks.add_task(send_mentor_signoff_request_email, mentor.email, scout_name, badge["title"], entry.step_index + 1, step_text, notes=entry.notes)
    except progress_svc.Conflict as exc:
        if str(exc) == "already_signed_off":
            error = "Deze stap is al afgetekend."
        elif str(exc) == "not_work_done":
            error = "Je kunt pas aftekening aanvragen als je de stap als 'Klaar' hebt gemeld."
        else:
            error = "Dit e-mailadres is al uitgenodigd."
        db.refresh(entry)
    except progress_svc.NotFound:
        return RedirectResponse(url="/", status_code=303)

    return _step_card(request, entry.badge_slug, entry.level_index, level["name"], entry.step_index, step_text, entry, previous_mentors, error=error, current_user=current_user)


# ── Cancel sign-off requests ─────────────────────────────────────────────────

@router.post("/progress/{entry_id}/cancel-signoff", response_class=HTMLResponse)
async def cancel_signoff(
    request: Request,
    entry_id: str,
    db: Session = Depends(get_db),
):
    current_user = _get_current_user(request, db)
    if current_user is None:
        return RedirectResponse(url="/login", status_code=303)

    entry = db.query(ProgressEntry).filter(
        ProgressEntry.id == entry_id,
        ProgressEntry.user_id == current_user.id,
    ).first()
    if entry is None:
        return RedirectResponse(url="/", status_code=303)

    badge = get_badge(_DATA_DIR, entry.badge_slug)
    level = badge["levels"][entry.level_index]
    step_text = level["steps"][entry.step_index]["text"]
    previous_mentors = progress_svc.list_previous_mentors(db, current_user.id)

    try:
        entry = progress_svc.cancel_signoff_requests(db, current_user.id, entry_id)
    except (progress_svc.NotFound, progress_svc.Forbidden, progress_svc.Conflict):
        db.refresh(entry)

    return _step_card(request, entry.badge_slug, entry.level_index, level["name"], entry.step_index, step_text, entry, previous_mentors, current_user=current_user)


# ── Delete entry ──────────────────────────────────────────────────────────────

@router.post("/progress/{entry_id}/delete", response_class=HTMLResponse)
async def delete_progress(
    request: Request,
    entry_id: str,
    db: Session = Depends(get_db),
):
    current_user = _get_current_user(request, db)
    if current_user is None:
        return RedirectResponse(url="/login", status_code=303)

    entry = db.query(ProgressEntry).filter(
        ProgressEntry.id == entry_id,
        ProgressEntry.user_id == current_user.id,
    ).first()
    if entry is None:
        return HTMLResponse("")

    badge = get_badge(_DATA_DIR, entry.badge_slug)
    level = badge["levels"][entry.level_index]
    step_text = level["steps"][entry.step_index]["text"]
    slug, level_index, level_name, step_index = entry.badge_slug, entry.level_index, level["name"], entry.step_index
    previous_mentors = progress_svc.list_previous_mentors(db, current_user.id)

    try:
        progress_svc.delete_progress(db, current_user.id, entry_id)
        entry = None
    except (progress_svc.NotFound, progress_svc.Forbidden):
        db.refresh(entry)

    return _step_card(request, slug, level_index, level_name, step_index, step_text, entry, previous_mentors, current_user=current_user)


# ── Sign-off requests (mentor view) ──────────────────────────────────────────

@router.get("/signoff-requests/count", response_class=HTMLResponse)
async def signoff_requests_count(request: Request, db: Session = Depends(get_db)):
    current_user = _get_current_user(request, db)
    if current_user is None:
        return HTMLResponse("")
    count = len(progress_svc.list_signoff_requests(db, current_user.id))
    if count == 0:
        return HTMLResponse("")
    return HTMLResponse(f'<span class="nav-badge">({count})</span>')


@router.get("/signoff-requests", response_class=HTMLResponse)
async def signoff_requests_page(request: Request, db: Session = Depends(get_db)):
    current_user = _get_current_user(request, db)
    if current_user is None:
        return RedirectResponse(url="/login", status_code=303)

    raw_requests = progress_svc.list_signoff_requests(db, current_user.id)

    _nl_months = ["januari","februari","maart","april","mei","juni",
                  "juli","augustus","september","oktober","november","december"]

    enriched = []
    for sr in raw_requests:
        pe = sr.progress_entry
        badge = get_badge(_DATA_DIR, pe.badge_slug)
        if badge is None:
            continue
        level = badge["levels"][pe.level_index]
        step = level["steps"][pe.step_index]
        _dt = sr.created_at
        requested_at = f"{_dt.day} {_nl_months[_dt.month - 1]} {_dt.year} om {_dt.strftime('%H:%M')}"
        enriched.append({
            "entry_id": pe.id,
            "scout_name": pe.user.name or pe.user.email,
            "badge_title": badge["title"],
            "niveau_number": pe.step_index + 1,
            "level_number": pe.level_index + 1,
            "level_name": level["name"],
            "step_text": step["text"],
            "notes": pe.notes,
            "requested_at": requested_at,
        })

    return _TEMPLATES.TemplateResponse(
        request=request,
        name="signoff_requests.html",
        context={"current_user": current_user, "requests": enriched},
    )


@router.post("/progress/{entry_id}/confirm-signoff", response_class=HTMLResponse)
async def confirm_signoff(
    request: Request,
    entry_id: str,
    background_tasks: BackgroundTasks,
    comment: str = Form(""),
    db: Session = Depends(get_db),
):
    current_user = _get_current_user(request, db)
    if current_user is None:
        return RedirectResponse(url="/login", status_code=303)

    try:
        entry = progress_svc.confirm_signoff(db, current_user.id, entry_id, comment=comment.strip() or None)
        confirmed = True
        error = ""

        scout = entry.user
        badge = get_badge(_DATA_DIR, entry.badge_slug)
        level = badge["levels"][entry.level_index]
        step_text = level["steps"][entry.step_index]["text"]
        mentor_name = current_user.name or current_user.email

        background_tasks.add_task(
            send_scout_signed_off_email,
            scout.email,
            scout.name or scout.email,
            entry.badge_slug,
            badge["title"],
            entry.step_index + 1,
            level["name"],
            step_text,
            mentor_name,
            mentor_comment=entry.mentor_comment,
        )

        n_eisen = len(badge["levels"])
        signed_count = db.query(ProgressEntry).filter(
            ProgressEntry.user_id == entry.user_id,
            ProgressEntry.badge_slug == entry.badge_slug,
            ProgressEntry.step_index == entry.step_index,
            ProgressEntry.status == "signed_off",
        ).count()
        if signed_count == n_eisen:
            background_tasks.add_task(
                send_scout_niveau_completed_email,
                scout.email,
                scout.name or scout.email,
                badge["title"],
                entry.step_index + 1,
                entry.badge_slug,
            )

    except (progress_svc.NotFound, progress_svc.Forbidden, progress_svc.Conflict) as exc:
        confirmed = False
        error = "Kon niet aftekenen." if not isinstance(exc, progress_svc.Conflict) else "Al afgetekend."

    return _partial(request, "signoff_request_item.html", entry_id=entry_id, confirmed=confirmed, error=error)


@router.post("/progress/{entry_id}/reject-signoff", response_class=HTMLResponse)
async def reject_signoff(
    request: Request,
    entry_id: str,
    background_tasks: BackgroundTasks,
    message: str = Form(""),
    db: Session = Depends(get_db),
):
    current_user = _get_current_user(request, db)
    if current_user is None:
        return RedirectResponse(url="/login", status_code=303)

    try:
        entry = progress_svc.reject_signoff(db, current_user.id, entry_id, message.strip())

        scout = entry.user
        badge = get_badge(_DATA_DIR, entry.badge_slug)
        level = badge["levels"][entry.level_index]
        step_text = level["steps"][entry.step_index]["text"]
        mentor_name = current_user.name or current_user.email

        background_tasks.add_task(
            send_scout_rejected_email,
            scout.email,
            scout.name or scout.email,
            badge["title"],
            entry.step_index + 1,
            level["name"],
            step_text,
            mentor_name,
            message.strip(),
        )

        return _partial(request, "signoff_request_item.html", entry_id=entry_id, confirmed=False, error="", rejected=True)
    except (progress_svc.NotFound, progress_svc.Forbidden) as exc:
        error = "Kon niet afwijzen."
        return _partial(request, "signoff_request_item.html", entry_id=entry_id, confirmed=False, error=error)

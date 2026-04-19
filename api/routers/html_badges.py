from pathlib import Path

from fastapi import APIRouter, Depends, Form, Query, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from insigne import progress as progress_svc
from insigne.badges import get_badge
from insigne.database import get_db
from insigne.models import ProgressEntry

from routers.users import _get_current_user

router = APIRouter()

_DATA_DIR = Path(__file__).parent.parent / "data"
_TEMPLATES = Jinja2Templates(directory=Path(__file__).parent.parent.parent / "frontend" / "templates")
_TEMPLATES.env.globals["current_user"] = None


def _partial(request: Request, name: str, **ctx):
    return _TEMPLATES.TemplateResponse(request=request, name=f"partials/{name}", context=ctx)


def _step_card(request, slug, level_index, level_name, step_index, step_text, entry, previous_mentors=None, error=""):
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

    return _step_card(request, slug, level_index, level["name"], step_index, step_text, entry, previous_mentors)


# ── Request sign-off ──────────────────────────────────────────────────────────

@router.post("/progress/{entry_id}/request-signoff", response_class=HTMLResponse)
async def request_signoff(
    request: Request,
    entry_id: str,
    mentor_email: str = Form(...),
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

    error = ""
    try:
        entry, mentor, created = progress_svc.request_signoff(db, current_user.id, entry_id, mentor_email)
        print(
            f"\n[DEV] {'Invitation' if created else 'Sign-off request'} → {mentor.email} for entry {entry.id}\n",
            flush=True,
        )
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

    return _step_card(request, entry.badge_slug, entry.level_index, level["name"], entry.step_index, step_text, entry, previous_mentors, error=error)


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

    return _step_card(request, slug, level_index, level_name, step_index, step_text, entry, previous_mentors)


# ── Sign-off requests (mentor view) ──────────────────────────────────────────

@router.get("/signoff-requests", response_class=HTMLResponse)
async def signoff_requests_page(request: Request, db: Session = Depends(get_db)):
    current_user = _get_current_user(request, db)
    if current_user is None:
        return RedirectResponse(url="/login", status_code=303)

    raw_requests = progress_svc.list_signoff_requests(db, current_user.id)

    enriched = []
    for sr in raw_requests:
        pe = sr.progress_entry
        badge = get_badge(_DATA_DIR, pe.badge_slug)
        if badge is None:
            continue
        level = badge["levels"][pe.level_index]
        step = level["steps"][pe.step_index]
        enriched.append({
            "entry_id": pe.id,
            "scout_name": pe.user.name or pe.user.email,
            "badge_title": badge["title"],
            "level_name": level["name"],
            "step_text": step["text"],
            "notes": pe.notes,
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
    db: Session = Depends(get_db),
):
    current_user = _get_current_user(request, db)
    if current_user is None:
        return RedirectResponse(url="/login", status_code=303)

    try:
        progress_svc.confirm_signoff(db, current_user.id, entry_id)
        confirmed = True
        error = ""
    except (progress_svc.NotFound, progress_svc.Forbidden, progress_svc.Conflict) as exc:
        confirmed = False
        error = "Kon niet aftekenen." if not isinstance(exc, progress_svc.Conflict) else "Al afgetekend."

    return _partial(request, "signoff_request_item.html", entry_id=entry_id, confirmed=confirmed, error=error)

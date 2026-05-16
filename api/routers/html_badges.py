from pathlib import Path

from fastapi import APIRouter, BackgroundTasks, Depends, Form, Query, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.orm import Session

from insigne import groups as groups_svc
from insigne import jaarinsigne_2026 as jaarinsigne_2026_svc
from insigne import progress as progress_svc
from datetime import datetime

from insigne.badges import BadgeCatalogue
from insigne.database import get_db
from insigne.email import (
    send_mentor_signoff_invite_email,
    send_mentor_signoff_request_email,
    send_scout_niveau_completed_email,
    send_scout_rejected_email,
    send_scout_signed_off_email,
)
from insigne.models import ProgressEntry, SpeltakMembership, User

import re as _re

from routers.users import _get_current_user
from templates import templates as _TEMPLATES

_UUID_RE = _re.compile(r'^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$', _re.I)

router = APIRouter()


def _mobile_default_niveau(progress_map: dict, badge: dict) -> int:
    """Return the highest niveau/jaar (1-3) with any progress, falling back to 1."""
    n_eisen = len(badge["levels"])
    for niveau_idx in reversed(range(3)):
        for eis_idx in range(n_eisen):
            entry = progress_map.get((eis_idx, niveau_idx))
            if entry and entry.status != "none":
                return niveau_idx + 1
    return 1

_CATALOGUE = BadgeCatalogue(Path(__file__).parent.parent / "data")


def _partial(request: Request, name: str, **ctx):
    return _TEMPLATES.TemplateResponse(request=request, name=f"partials/{name}", context=ctx)


def _step_card(request, slug, level_index, level_name, step_index, step_text, entry, previous_mentors=None, error="", current_user=None, scout_signoff_options=None):
    _badge = _CATALOGUE.get(slug)
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
        scout_signoff_options=scout_signoff_options or [],
        niveau_label_kort=_badge.get("niveau_label_kort", "N") if _badge else "N",
    )
    response.headers["HX-Trigger"] = "niveau-updated"
    return response


def _build_signoff_options(db, current_user):
    """Build the list of speltak sign-off path options for a scout."""
    memberships = groups_svc.list_scout_speltakken(db, current_user.id)
    options = []
    for group, speltak, role in memberships:
        if speltak.peer_signoff:
            members = [m.user for m in groups_svc.list_speltak_members(db, speltak.id)
                       if m.user_id != current_user.id]
            if members:
                options.append({
                    "type": "speltak_members",
                    "speltak_id": speltak.id,
                    "speltak_name": speltak.name,
                    "group_name": group.name,
                    "label_prefix": "Vraag een mede-lid van de",
                    "label_suffix": "om af te tekenen",
                    "members": members,
                })
        elif role != "speltakleider":
            options.append({
                "type": "speltak_leiders",
                "speltak_id": speltak.id,
                "speltak_name": speltak.name,
                "group_name": group.name,
                "label_prefix": "Aftekenen door leiding van",
                "label_suffix": "",
            })
    return options


# ── Niveau progress checks (HTMX partial) ────────────────────────────────────

@router.get("/badges/{slug}/niveau-checks/{niveau_index}", response_class=HTMLResponse)
async def niveau_checks(request: Request, slug: str, niveau_index: int, db: Session = Depends(get_db)):
    current_user = _get_current_user(request, db)
    if not current_user:
        return HTMLResponse("<p>Niet ingelogd.</p>", status_code=401)
    badge = _CATALOGUE.get(slug)
    if badge is None:
        return HTMLResponse("")

    progress_map: dict[tuple[int, int], ProgressEntry] = {}
    for entry in progress_svc.list_progress(db, current_user.id, badge_slug=slug):
        progress_map[(entry.level_index, entry.step_index)] = entry

    return _partial(
        request, "niveau_checks.html",
        slug=slug,
        niveau_index=niveau_index,
        n_eisen=len(badge["levels"]),
        is_jaarbadge=False,
        progress_map=progress_map,
        style=None,
    )


# ── Badge detail ──────────────────────────────────────────────────────────────

@router.get("/badges/{slug}", response_class=HTMLResponse)
async def badge_detail(request: Request, slug: str, niveau: int | None = Query(None), speltak: str | None = Query(None), db: Session = Depends(get_db)):
    current_user = _get_current_user(request, db)
    badge = _CATALOGUE.get(slug)
    if badge is None:
        return RedirectResponse(url="/", status_code=303)

    progress_map: dict[tuple[int, int], ProgressEntry] = {}
    previous_mentors = []
    scout_signoff_options = []

    if current_user:
        for entry in progress_svc.list_progress(db, current_user.id, badge_slug=slug):
            progress_map[(entry.level_index, entry.step_index)] = entry
        previous_mentors = progress_svc.list_previous_mentors(db, current_user.id)
        scout_signoff_options = _build_signoff_options(db, current_user)

    if badge.get("type") == "jaarinsigne":
        jl = progress_svc.get_jaarinsigne_level(db, current_user.id, slug) if current_user else None
        if jl:
            speltak_slug = jl.speltak_slug
        elif current_user:
            speltak_slug = groups_svc.get_user_primary_speltak_type(db, current_user.id)
        else:
            speltak_slug = None
        resolved_level_index = _CATALOGUE.resolve_jaarinsigne_level_index(badge, speltak_slug)
        can_set_own_level = (
            groups_svc.can_user_set_own_jaarinsigne_level(db, current_user.id)
            if current_user else False
        )
        # ?speltak= allows viewing other levels (read-only)
        if speltak:
            view_level = next((l for l in badge["levels"] if l["slug"] == speltak), None)
            selected_level_index = view_level["level_index"] if view_level else resolved_level_index
        else:
            selected_level_index = resolved_level_index

        # jaarinsigne_2026-specific include/exclude editor data
        score_summary = None
        available_to_include = []
        included_details = []
        if slug == "jaarinsigne_2026" and current_user and speltak_slug:
            speltak_min_punten = 3
            for m in db.query(SpeltakMembership).filter_by(
                user_id=current_user.id, approved=True, withdrawn=False
            ).all():
                if m.speltak and m.speltak.speltak_type == speltak_slug:
                    if m.speltak.jaarinsigne_2026_min_punten is not None:
                        speltak_min_punten = m.speltak.jaarinsigne_2026_min_punten
                    break
            score_summary = jaarinsigne_2026_svc.get_score_summary(
                db, current_user.id, speltak_slug, speltak_min_punten
            )
            available_to_include = jaarinsigne_2026_svc.get_available_to_include(db, current_user.id)
            included_details = jaarinsigne_2026_svc.get_included_details(db, current_user.id)

        return _TEMPLATES.TemplateResponse(
            request=request,
            name="badge.html",
            context={
                "current_user": current_user,
                "badge": badge,
                "progress_map": progress_map,
                "previous_mentors": previous_mentors,
                "scout_signoff_options": scout_signoff_options,
                "resolved_level_index": resolved_level_index,
                "selected_level_index": selected_level_index,
                "can_set_own_level": can_set_own_level,
                "selected_niveaus": [],
                "niveau_stats": [],
                "level_stats": [],
                "mobile_default_niveau": 1,
                "score_summary": score_summary,
                "available_to_include": available_to_include,
                "included_details": included_details,
            },
        )

    level_stats = []
    for i, level in enumerate(badge["levels"]):
        total = len(level["steps"])
        completed = sum(
            1 for step in level["steps"]
            if progress_map.get((i, step["index"])) and
               progress_map[(i, step["index"])].status == "signed_off"
        )
        level_stats.append({"completed": completed, "total": total})

    n_eisen = len(badge["levels"])
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
            "scout_signoff_options": scout_signoff_options,
            "level_stats": level_stats,
            "niveau_stats": niveau_stats,
            "selected_niveaus": [niveau - 1] if niveau in (1, 2, 3) else [0, 1, 2],
            "mobile_default_niveau": _mobile_default_niveau(progress_map, badge),
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

    badge = _CATALOGUE.get(slug)
    if (badge is None
            or not (0 <= level_index < len(badge["levels"]))
            or not (0 <= step_index < len(badge["levels"][level_index]["steps"]))):
        return RedirectResponse(url="/", status_code=303)
    level = badge["levels"][level_index]
    step_text = level["steps"][step_index]["text"]
    previous_mentors = progress_svc.list_previous_mentors(db, current_user.id)
    scout_signoff_options = _build_signoff_options(db, current_user)

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

    return _step_card(request, slug, level_index, level["name"], step_index, step_text, entry, previous_mentors, current_user=current_user, scout_signoff_options=scout_signoff_options)


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

    badge = _CATALOGUE.get(entry.badge_slug)
    level = badge["levels"][entry.level_index]
    step_text = level["steps"][entry.step_index]["text"]
    previous_mentors = progress_svc.list_previous_mentors(db, current_user.id)
    scout_signoff_options = _build_signoff_options(db, current_user)

    error = ""
    scout_name = current_user.name or current_user.email.split("@")[0]
    try:
        if _UUID_RE.match(mentor_email.strip()):
            entry, invited = progress_svc.request_signoff_from_members(db, current_user.id, entry_id, [mentor_email.strip()])
            for mentor in invited:
                background_tasks.add_task(send_mentor_signoff_request_email, mentor.email, scout_name, badge["title"], entry.step_index + 1, step_text, notes=entry.notes)
        else:
            entry, mentor, created = progress_svc.request_signoff(db, current_user.id, entry_id, mentor_email)
            if created:
                background_tasks.add_task(send_mentor_signoff_invite_email, mentor.email, scout_name, badge["title"], entry.step_index + 1, step_text, notes=entry.notes)
            else:
                background_tasks.add_task(send_mentor_signoff_request_email, mentor.email, scout_name, badge["title"], entry.step_index + 1, step_text, notes=entry.notes)
    except progress_svc.Forbidden as exc:
        if str(exc) == "self_signoff":
            error = "Je kunt jezelf niet uitnodigen om af te tekenen."
        db.refresh(entry)
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

    return _step_card(request, entry.badge_slug, entry.level_index, level["name"], entry.step_index, step_text, entry, previous_mentors, error=error, current_user=current_user, scout_signoff_options=scout_signoff_options)


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

    badge = _CATALOGUE.get(entry.badge_slug)
    level = badge["levels"][entry.level_index]
    step_text = level["steps"][entry.step_index]["text"]
    previous_mentors = progress_svc.list_previous_mentors(db, current_user.id)
    scout_signoff_options = _build_signoff_options(db, current_user)

    try:
        entry = progress_svc.cancel_signoff_requests(db, current_user.id, entry_id)
    except (progress_svc.NotFound, progress_svc.Forbidden, progress_svc.Conflict):
        db.refresh(entry)

    return _step_card(request, entry.badge_slug, entry.level_index, level["name"], entry.step_index, step_text, entry, previous_mentors, current_user=current_user, scout_signoff_options=scout_signoff_options)


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

    badge = _CATALOGUE.get(entry.badge_slug)
    level = badge["levels"][entry.level_index]
    step_text = level["steps"][entry.step_index]["text"]
    slug, level_index, level_name, step_index = entry.badge_slug, entry.level_index, level["name"], entry.step_index
    previous_mentors = progress_svc.list_previous_mentors(db, current_user.id)
    scout_signoff_options = _build_signoff_options(db, current_user)

    try:
        progress_svc.delete_progress(db, current_user.id, entry_id)
        entry = None
    except (progress_svc.NotFound, progress_svc.Forbidden):
        db.refresh(entry)

    return _step_card(request, slug, level_index, level_name, step_index, step_text, entry, previous_mentors, current_user=current_user, scout_signoff_options=scout_signoff_options)


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
        badge = _CATALOGUE.get(pe.badge_slug)
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
        badge = _CATALOGUE.get(entry.badge_slug)
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
        badge = _CATALOGUE.get(entry.badge_slug)
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


# ── Request sign-off via speltak leiders ──────────────────────────────────────

@router.post("/progress/{entry_id}/request-signoff-speltak", response_class=HTMLResponse)
async def request_signoff_speltak(
    request: Request,
    entry_id: str,
    background_tasks: BackgroundTasks,
    speltak_id: str = Form(...),
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

    badge = _CATALOGUE.get(entry.badge_slug)
    level = badge["levels"][entry.level_index]
    step_text = level["steps"][entry.step_index]["text"]
    previous_mentors = progress_svc.list_previous_mentors(db, current_user.id)
    scout_signoff_options = _build_signoff_options(db, current_user)

    error = ""
    try:
        entry, invited = progress_svc.request_signoff_for_speltak(db, current_user.id, entry_id, speltak_id)
        scout_name = current_user.name or current_user.email.split("@")[0]
        for mentor in invited:
            background_tasks.add_task(
                send_mentor_signoff_request_email, mentor.email, scout_name,
                badge["title"], entry.step_index + 1, step_text, notes=entry.notes,
            )
    except progress_svc.NotFound as exc:
        if str(exc) == "no_eligible_mentors":
            error = "Er zijn geen leiders gevonden die kunnen aftekenen."
        else:
            return RedirectResponse(url="/", status_code=303)
    except progress_svc.Conflict as exc:
        if str(exc) == "already_signed_off":
            error = "Deze stap is al afgetekend."
        else:
            error = "Je kunt pas aftekening aanvragen als je de stap als 'Klaar' hebt gemeld."
        db.refresh(entry)

    return _step_card(request, entry.badge_slug, entry.level_index, level["name"], entry.step_index, step_text, entry, previous_mentors, error=error, current_user=current_user, scout_signoff_options=scout_signoff_options)


# ── Request sign-off from selected members (peer speltak) ────────────────────

@router.post("/progress/{entry_id}/request-signoff-members", response_class=HTMLResponse)
async def request_signoff_members(
    request: Request,
    entry_id: str,
    background_tasks: BackgroundTasks,
    mentor_ids: list[str] = Form(default=[]),
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

    badge = _CATALOGUE.get(entry.badge_slug)
    level = badge["levels"][entry.level_index]
    step_text = level["steps"][entry.step_index]["text"]
    previous_mentors = progress_svc.list_previous_mentors(db, current_user.id)
    scout_signoff_options = _build_signoff_options(db, current_user)

    error = ""
    try:
        entry, invited = progress_svc.request_signoff_from_members(db, current_user.id, entry_id, mentor_ids)
        scout_name = current_user.name or current_user.email.split("@")[0]
        for mentor in invited:
            background_tasks.add_task(
                send_mentor_signoff_request_email, mentor.email, scout_name,
                badge["title"], entry.step_index + 1, step_text, notes=entry.notes,
            )
    except progress_svc.NotFound as exc:
        if str(exc) == "no_eligible_mentors":
            error = "Selecteer minimaal één medelid om aftekening te vragen."
        else:
            return RedirectResponse(url="/", status_code=303)
    except progress_svc.Conflict as exc:
        if str(exc) == "already_signed_off":
            error = "Deze stap is al afgetekend."
        else:
            error = "Je kunt pas aftekening aanvragen als je de stap als 'Klaar' hebt gemeld."
        db.refresh(entry)

    return _step_card(request, entry.badge_slug, entry.level_index, level["name"], entry.step_index, step_text, entry, previous_mentors, error=error, current_user=current_user, scout_signoff_options=scout_signoff_options)


# ── Per-scout progress (leider view) ─────────────────────────────────────────

def _build_badge_catalogue(all_progress: dict, db=None, scout_id: str | None = None) -> tuple[dict, list]:
    """Return (all_badges_enriched, signed_off_niveaus) for the given progress map."""
    all_badges = _CATALOGUE.list()
    for badges in all_badges.values():
        for badge in badges:
            detail = _CATALOGUE.get(badge["slug"])
            badge["dedicated_api"] = detail.get("dedicated_api", False)
            badge["type"] = detail.get("type", "gewoon")
            if badge["dedicated_api"]:
                badge["level_cards"] = []
                continue
            if detail.get("type") == "jaarinsigne":
                jl = progress_svc.get_jaarinsigne_level(db, scout_id, badge["slug"]) if db and scout_id else None
                if jl:
                    speltak_slug = jl.speltak_slug
                elif db and scout_id:
                    speltak_slug = groups_svc.get_user_primary_speltak_type(db, scout_id)
                else:
                    speltak_slug = None
                resolved_level_index = _CATALOGUE.resolve_jaarinsigne_level_index(detail, speltak_slug)
                level = next((l for l in detail["levels"] if l["level_index"] == resolved_level_index), None)
                if level:
                    slug_progress = all_progress.get(badge["slug"], {})
                    n_steps = len(level["steps"])
                    badge["level_cards"] = [{
                        "index": resolved_level_index,
                        "name": level["name"],
                        "short_name": level["kort"],
                        "image": f"/images/{badge['slug']}.png",
                        "total": n_steps,
                        "completed": sum(
                            1 for step_idx in range(n_steps)
                            if slug_progress.get((resolved_level_index, step_idx))
                            and slug_progress[(resolved_level_index, step_idx)].status == "signed_off"
                        ),
                        "completed_at": None,
                    }]
                else:
                    badge["level_cards"] = []
                continue
            niveau_label = detail.get("niveau_label", "Niveau")
            niveau_label_kort = detail.get("niveau_label_kort", "N")
            badge["niveau_label"] = niveau_label
            slug_progress = all_progress.get(badge["slug"], {})
            badge["level_cards"] = [
                {
                    "index": niveau_idx,
                    "name": f"{niveau_label} {niveau_idx + 1}",
                    "short_name": f"{niveau_label_kort}{niveau_idx + 1}",
                    "image": f"/images/{badge['slug']}.{niveau_idx + 1}.png",
                    "total": sum(
                        1 for group in detail["levels"]
                        if group["steps"][niveau_idx]["text"].strip()
                    ),
                    "completed": sum(
                        1 for eis_idx, group in enumerate(detail["levels"])
                        if group["steps"][niveau_idx]["text"].strip()
                        and slug_progress.get((eis_idx, niveau_idx))
                        and slug_progress[(eis_idx, niveau_idx)].status == "signed_off"
                    ),
                    "completed_at": max(
                        (slug_progress[(eis_idx, niveau_idx)].signed_off_at
                         for eis_idx, group in enumerate(detail["levels"])
                         if group["steps"][niveau_idx]["text"].strip()
                         and slug_progress.get((eis_idx, niveau_idx))
                         and slug_progress[(eis_idx, niveau_idx)].status == "signed_off"
                         and slug_progress[(eis_idx, niveau_idx)].signed_off_at),
                        default=None,
                    ),
                }
                for niveau_idx in range(3)
            ]
    signed_off_niveaus = sorted(
        [
            {
                "slug": badge["slug"],
                "title": badge["title"],
                "niveau_number": card["index"] + 1,
                "image": card["image"],
                "completed_at": card["completed_at"],
            }
            for badges in all_badges.values()
            for badge in badges
            for card in badge["level_cards"]
            if card["completed"] == card["total"] and card["total"] > 0
        ],
        key=lambda n: n["completed_at"] or datetime.min,
    )
    return all_badges, signed_off_niveaus


def _require_scout_access(request: Request, scout_id: str, db: Session):
    """Return (current_user, scout) or (None, redirect) on auth/access failure."""
    current_user = _get_current_user(request, db)
    if current_user is None:
        return None, RedirectResponse("/login", status_code=303)
    if scout_id == current_user.id:
        return None, RedirectResponse("/", status_code=303)
    scout = db.get(User, scout_id)
    if scout is None or not groups_svc.can_view_scout_progress(current_user, db, scout_id):
        return None, RedirectResponse("/", status_code=303)
    return current_user, scout


@router.get("/scouts/{scout_id}", response_class=HTMLResponse)
async def scout_progress_home(scout_id: str, request: Request, only_in_progress: int = Query(0), db: Session = Depends(get_db)):
    current_user, scout_or_redirect = _require_scout_access(request, scout_id, db)
    if current_user is None:
        return scout_or_redirect
    scout = scout_or_redirect

    edit_speltak_id = groups_svc.get_edit_speltak_for_scout(db, current_user.id, scout_id)
    all_progress: dict[str, dict] = {}
    for entry in progress_svc.list_progress(db, scout_id):
        all_progress.setdefault(entry.badge_slug, {})[(entry.level_index, entry.step_index)] = entry

    all_badges, signed_off_niveaus = _build_badge_catalogue(all_progress, db=db, scout_id=scout_id)
    response = _TEMPLATES.TemplateResponse(
        request=request,
        name="scout_progress.html",
        context={
            "current_user": current_user,
            "scout": scout,
            "can_edit": edit_speltak_id is not None,
            "edit_speltak_id": edit_speltak_id,
            "all_badges": all_badges,
            "all_progress": all_progress,
            "signed_off_niveaus": signed_off_niveaus,
            "progress_slugs": set(all_progress.keys()),
            "only_in_progress": bool(only_in_progress),
            "category_labels": _CATALOGUE.category_labels,
        },
    )
    response.headers["Cache-Control"] = "no-store"
    return response


@router.get("/scouts/{scout_id}/badges/{slug}", response_class=HTMLResponse)
async def scout_badge_detail(
    scout_id: str, slug: str,
    request: Request,
    niveau: int | None = Query(None),
    speltak: str | None = Query(None),
    db: Session = Depends(get_db),
):
    current_user, scout_or_redirect = _require_scout_access(request, scout_id, db)
    if current_user is None:
        return scout_or_redirect
    scout = scout_or_redirect

    badge = _CATALOGUE.get(slug)
    if badge is None:
        return RedirectResponse(f"/scouts/{scout.id}", status_code=303)

    edit_speltak_id = groups_svc.get_edit_speltak_for_scout(db, current_user.id, scout_id)
    can_edit = edit_speltak_id is not None
    progress_map: dict[tuple[int, int], ProgressEntry] = {}
    for entry in progress_svc.list_progress(db, scout_id, badge_slug=slug):
        progress_map[(entry.level_index, entry.step_index)] = entry

    if badge.get("type") == "jaarinsigne":
        jl = progress_svc.get_jaarinsigne_level(db, scout_id, slug)
        if jl:
            speltak_slug = jl.speltak_slug
        else:
            speltak_slug = groups_svc.get_user_primary_speltak_type(db, scout_id)
        resolved_level_index = _CATALOGUE.resolve_jaarinsigne_level_index(badge, speltak_slug)
        if speltak:
            view_level = next((l for l in badge["levels"] if l["slug"] == speltak), None)
            selected_level_index = view_level["level_index"] if view_level else resolved_level_index
        else:
            selected_level_index = resolved_level_index
        return _TEMPLATES.TemplateResponse(
            request=request,
            name="scout_badge.html",
            context={
                "current_user": current_user,
                "scout": scout,
                "badge": badge,
                "progress_map": progress_map,
                "can_edit": can_edit,
                "edit_speltak_id": edit_speltak_id,
                "resolved_level_index": resolved_level_index,
                "selected_level_index": selected_level_index,
                "selected_niveaus": [],
                "niveau_stats": [],
                "mobile_default_niveau": 1,
                "_post_url": f"/scouts/{scout_id}/set-progress",
            },
        )

    n_eisen = len(badge["levels"])
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
        name="scout_badge.html",
        context={
            "current_user": current_user,
            "scout": scout,
            "badge": badge,
            "progress_map": progress_map,
            "can_edit": can_edit,
            "edit_speltak_id": edit_speltak_id,
            "niveau_stats": niveau_stats,
            "selected_niveaus": [niveau - 1] if niveau in (1, 2, 3) else [0, 1, 2],
            "mobile_default_niveau": _mobile_default_niveau(progress_map, badge),
            "_post_url": f"/scouts/{scout_id}/set-progress",
        },
    )


@router.post("/badges/{slug}/set-level", response_class=HTMLResponse)
async def badge_set_jaarinsigne_level(
    slug: str, request: Request,
    speltak_slug: str = Form(...),
    db: Session = Depends(get_db),
):
    current_user = _get_current_user(request, db)
    if not current_user:
        return RedirectResponse("/login", status_code=303)
    badge = _CATALOGUE.get(slug)
    valid_slugs = {l["slug"] for l in badge["levels"]} if badge and badge.get("type") == "jaarinsigne" else set()
    if speltak_slug not in valid_slugs or not groups_svc.can_user_set_own_jaarinsigne_level(db, current_user.id):
        return RedirectResponse(f"/badges/{slug}" if badge else "/", status_code=303)
    progress_svc.set_jaarinsigne_level(db, current_user.id, slug, speltak_slug, current_user.id)
    return RedirectResponse(f"/badges/{slug}", status_code=303)


@router.post("/scouts/{scout_id}/badges/{slug}/set-level", response_class=HTMLResponse)
async def scout_set_jaarinsigne_level(
    scout_id: str, slug: str, request: Request,
    speltak_slug: str = Form(...),
    db: Session = Depends(get_db),
):
    current_user, scout_or_redirect = _require_scout_access(request, scout_id, db)
    if current_user is None:
        return scout_or_redirect
    if not groups_svc.get_edit_speltak_for_scout(db, current_user.id, scout_id):
        return RedirectResponse(f"/scouts/{scout_id}", status_code=303)
    badge = _CATALOGUE.get(slug)
    valid_slugs = {l["slug"] for l in badge["levels"]} if badge and badge.get("type") == "jaarinsigne" else set()
    if speltak_slug not in valid_slugs:
        return RedirectResponse(f"/scouts/{scout_id}/badges/{slug}", status_code=303)
    progress_svc.set_jaarinsigne_level(db, scout_id, slug, speltak_slug, current_user.id)
    return RedirectResponse(f"/scouts/{scout_id}/badges/{slug}", status_code=303)


@router.post("/badges/jaarinsigne_2026/toggle-inclusion", response_class=HTMLResponse)
async def jaarinsigne_2026_toggle_inclusion(
    request: Request,
    badge_slug: str = Form(...),
    level_index: int = Form(...),
    step_index: int = Form(...),
    db: Session = Depends(get_db),
):
    current_user = _get_current_user(request, db)
    if current_user is None:
        return RedirectResponse(url="/login", status_code=303)

    # Validate badge_slug is in eligible categories
    eligible_slugs = {b["slug"] for b in jaarinsigne_2026_svc.get_eligible_badges()}
    if badge_slug not in eligible_slugs:
        return RedirectResponse(url="/badges/jaarinsigne_2026", status_code=303)

    # Validate the ProgressEntry exists with status signed_off
    entry = db.query(ProgressEntry).filter_by(
        user_id=current_user.id,
        badge_slug=badge_slug,
        level_index=level_index,
        step_index=step_index,
    ).first()
    if entry is None or entry.status != "signed_off":
        return RedirectResponse(url="/badges/jaarinsigne_2026", status_code=303)

    jaarinsigne_2026_svc.toggle_inclusion(db, current_user.id, badge_slug, level_index, step_index)

    # Get user's speltak_slug and speltak_min_punten
    speltak_slug = groups_svc.get_user_primary_speltak_type(db, current_user.id)
    speltak_min_punten = 3
    if speltak_slug:
        memberships = db.query(SpeltakMembership).filter_by(
            user_id=current_user.id, approved=True, withdrawn=False
        ).all()
        for m in memberships:
            if m.speltak and m.speltak.speltak_type == speltak_slug:
                if m.speltak.jaarinsigne_2026_min_punten is not None:
                    speltak_min_punten = m.speltak.jaarinsigne_2026_min_punten
                break

    if speltak_slug:
        jaarinsigne_2026_svc.update_progress_entries(db, current_user.id, speltak_slug, speltak_min_punten)

    return RedirectResponse(url="/badges/jaarinsigne_2026", status_code=303)


@router.get("/scouts/{scout_id}/badges/{slug}/niveau-checks/{niveau_index}", response_class=HTMLResponse)
async def scout_niveau_checks(
    scout_id: str, slug: str, niveau_index: int,
    request: Request,
    db: Session = Depends(get_db),
):
    current_user, scout_or_redirect = _require_scout_access(request, scout_id, db)
    if current_user is None:
        return scout_or_redirect

    badge = _CATALOGUE.get(slug)
    if badge is None:
        return HTMLResponse("")

    progress_map: dict[tuple[int, int], ProgressEntry] = {}
    for entry in progress_svc.list_progress(db, scout_id, badge_slug=slug):
        progress_map[(entry.level_index, entry.step_index)] = entry

    return _partial(
        request, "scout_niveau_checks.html",
        scout_id=scout_id,
        slug=slug,
        niveau_index=niveau_index,
        n_eisen=len(badge["levels"]),
        is_jaarbadge=False,
        progress_map=progress_map,
        style=None,
    )


@router.post("/scouts/{scout_id}/set-progress", response_class=HTMLResponse)
async def scout_set_progress(
    scout_id: str,
    request: Request,
    badge_slug: str = Form(...),
    level_index: int = Form(...),
    step_index: int = Form(...),
    status: str = Form(...),
    message: str = Form(""),
    db: Session = Depends(get_db),
):
    current_user = _get_current_user(request, db)
    if current_user is None:
        return RedirectResponse("/login", status_code=303)

    edit_speltak_id = groups_svc.get_edit_speltak_for_scout(db, current_user.id, scout_id)
    badge = _CATALOGUE.get(badge_slug)
    if edit_speltak_id is None or badge is None:
        return HTMLResponse("", status_code=403)

    _post_url = f"/scouts/{scout_id}/set-progress"
    entry = None
    try:
        entry = progress_svc.set_scout_progress(
            db, leider_id=current_user.id, scout_id=scout_id,
            speltak_id=edit_speltak_id, badge_slug=badge_slug,
            level_index=level_index, step_index=step_index,
            status=status, message=message.strip(),
        )
        scout = db.get(User, scout_id)
        if entry and entry.status == "signed_off" and scout and scout.email:
            level = badge["levels"][level_index]
            step_text = level["steps"][step_index]["text"]
            send_scout_signed_off_email(
                scout.email, scout.name or scout.email,
                badge["title"], step_index + 1, step_text,
            )
    except ValueError:
        entry = db.query(ProgressEntry).filter_by(
            user_id=scout_id, badge_slug=badge_slug,
            level_index=level_index, step_index=step_index,
        ).first()
        entry_status = entry.status if entry else "none"
        return _partial(
            request, "leider_step_check.html",
            scout_id=scout_id, badge_slug=badge_slug,
            level_index=level_index, step_index=step_index,
            entry_status=entry_status, entry=entry,
            can_edit_cell=entry_status != "pending_signoff",
            can_review_cell=entry_status == "pending_signoff",
            _post_url=_post_url,
        )
    except (progress_svc.Forbidden, progress_svc.Conflict):
        return HTMLResponse("", status_code=403)

    entry_status = entry.status if entry else "none"
    partial_response = _partial(
        request, "leider_step_check.html",
        scout_id=scout_id, badge_slug=badge_slug,
        level_index=level_index, step_index=step_index,
        entry_status=entry_status, entry=entry,
        can_edit_cell=entry_status != "pending_signoff",
        can_review_cell=entry_status == "pending_signoff",
        _post_url=_post_url,
    )
    partial_response.headers["HX-Trigger"] = "niveau-updated"
    return partial_response

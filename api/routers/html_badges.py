from pathlib import Path

from fastapi import APIRouter, BackgroundTasks, Depends, Form, Query, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.orm import Session

from insigne import groups as groups_svc
from insigne import jaarinsigne_2026 as jaarinsigne_2026_svc
from insigne import progress as progress_svc
from datetime import datetime

from insigne.badges import BadgeCatalogue, jaarinsigne_levels_for_scout
from insigne.database import get_db
from insigne.email import (
    send_mentor_jaarinsigne_signoff_invite_email,
    send_mentor_jaarinsigne_signoff_request_email,
    send_mentor_signoff_invite_email,
    send_mentor_signoff_request_email,
    send_scout_jaarinsigne_rejected_email,
    send_scout_jaarinsigne_signed_off_email,
    send_scout_niveau_completed_email,
    send_scout_rejected_email,
    send_scout_signed_off_email,
)
from insigne.models import ProgressEntry, SignoffRequest, SpeltakMembership, User

import re as _re

from routers._query import lenient_int
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


# ── E-mail dispatch helpers ───────────────────────────────────────────────────
# For jaarinsigne badges, level_index = speltak and step_index = eis. We use
# dedicated jaarinsigne e-mail templates that use the correct labels.

def _emit_request_email(
    background_tasks: BackgroundTasks, *,
    mentor_email: str, scout_name: str,
    badge: dict, level: dict, entry: ProgressEntry, notes: str | None,
    is_invite: bool = False,
):
    """Queue the appropriate sign-off-request e-mail for a single eis."""
    if badge.get("type") == "jaarinsigne":
        step = level["steps"][entry.step_index]
        eisen = [{
            "number": entry.step_index + 1,
            "titel": step.get("titel", ""),
            "text": step.get("text", ""),
        }]
        fn = (send_mentor_jaarinsigne_signoff_invite_email if is_invite
              else send_mentor_jaarinsigne_signoff_request_email)
        background_tasks.add_task(
            fn, mentor_email, scout_name, badge["slug"], badge["title"],
            level.get("name", ""), level.get("leeftijd", ""), eisen, notes,
        )
    else:
        step_text = level["steps"][entry.step_index]["text"]
        fn = (send_mentor_signoff_invite_email if is_invite
              else send_mentor_signoff_request_email)
        background_tasks.add_task(
            fn, mentor_email, scout_name, badge["title"], entry.step_index + 1,
            step_text, notes=notes,
        )


def _emit_signed_off_email(
    background_tasks: BackgroundTasks, *,
    scout_email: str, scout_name: str, mentor_name: str,
    badge: dict, level: dict, entry: ProgressEntry, mentor_comment: str | None,
):
    if badge.get("type") == "jaarinsigne":
        step = level["steps"][entry.step_index]
        eisen = [{
            "number": entry.step_index + 1,
            "titel": step.get("titel", ""),
        }]
        background_tasks.add_task(
            send_scout_jaarinsigne_signed_off_email,
            scout_email, scout_name, badge["slug"], badge["title"],
            level.get("name", ""), level.get("leeftijd", ""), eisen,
            mentor_name, mentor_comment,
        )
    else:
        step_text = level["steps"][entry.step_index]["text"]
        background_tasks.add_task(
            send_scout_signed_off_email,
            scout_email, scout_name, badge["slug"], badge["title"],
            entry.step_index + 1, level["name"], step_text,
            mentor_name, mentor_comment=mentor_comment,
        )


def _emit_rejected_email(
    background_tasks: BackgroundTasks, *,
    scout_email: str, scout_name: str, mentor_name: str,
    badge: dict, level: dict, entry: ProgressEntry, message: str,
):
    if badge.get("type") == "jaarinsigne":
        step = level["steps"][entry.step_index]
        eisen = [{
            "number": entry.step_index + 1,
            "titel": step.get("titel", ""),
        }]
        background_tasks.add_task(
            send_scout_jaarinsigne_rejected_email,
            scout_email, scout_name, badge["slug"], badge["title"],
            level.get("name", ""), level.get("leeftijd", ""), eisen,
            mentor_name, message,
        )
    else:
        step_text = level["steps"][entry.step_index]["text"]
        background_tasks.add_task(
            send_scout_rejected_email,
            scout_email, scout_name, badge["title"],
            entry.step_index + 1, level["name"], step_text,
            mentor_name, message,
        )


def _step_card(request, slug, level_index, level_name, step_index, step_text, entry, previous_mentors=None, error="", current_user=None, scout_signoff_options=None):
    _badge = _CATALOGUE.get(slug)
    step_green = False
    if _badge:
        try:
            step_green = bool(_badge["levels"][level_index]["steps"][step_index].get("green", False))
        except (IndexError, KeyError):
            pass
    response = _partial(
        request, "step_card.html",
        slug=slug,
        level_index=level_index,
        level_name=level_name,
        step_index=step_index,
        step_text=step_text,
        step_green=step_green,
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
async def badge_detail(
    request: Request,
    slug: str,
    niveau: str | None = Query(None),
    speltak: str | None = Query(None),
    db: Session = Depends(get_db),
):
    niveau = lenient_int(niveau)
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
        included_summary = None
        available_summary = None
        signoff_state = "not_ready"
        pending_mentors: list[User] = []
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
            included_summary = jaarinsigne_2026_svc.summarize_items(included_details)
            available_summary = jaarinsigne_2026_svc.summarize_additional(
                available_to_include, included_details
            )
            user_level = next(
                (lv for lv in badge["levels"] if lv["slug"] == speltak_slug), None
            )
            signoff_state = _jaarinsigne_2026_signoff_state(db, current_user.id, user_level)
            if signoff_state == "pending":
                pending_mentors = _jaarinsigne_2026_pending_mentors(
                    db, current_user.id, user_level
                )

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
                "included_summary": included_summary,
                "available_summary": available_summary,
                "signoff_state": signoff_state,
                "pending_mentors": pending_mentors,
                "signoff_error": "",
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
                _emit_request_email(
                    background_tasks, mentor_email=mentor.email, scout_name=scout_name,
                    badge=badge, level=level, entry=entry, notes=entry.notes,
                )
        else:
            entry, mentor, created = progress_svc.request_signoff(db, current_user.id, entry_id, mentor_email)
            _emit_request_email(
                background_tasks, mentor_email=mentor.email, scout_name=scout_name,
                badge=badge, level=level, entry=entry, notes=entry.notes,
                is_invite=created,
            )
    except progress_svc.Forbidden as exc:
        if str(exc) == "self_signoff":
            error = "Je kunt jezelf niet uitnodigen om af te tekenen."
        db.refresh(entry)
    except progress_svc.Conflict as exc:
        if str(exc) == "already_signed_off":
            error = "Deze stap is al afgetekend."
        elif str(exc) == "not_work_done":
            error = "Je kunt pas aftekening aanvragen als je de stap als 'Klaar' hebt gemeld."
        elif str(exc) == "invalid_email":
            error = "Geef een geldig e-mailadres op."
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

    items = progress_svc.list_signoff_requests_grouped(db, current_user.id)

    _nl_months = ["januari","februari","maart","april","mei","juni",
                  "juli","augustus","september","oktober","november","december"]

    def _fmt_date(dt):
        return f"{dt.day} {_nl_months[dt.month - 1]} {dt.year} om {dt.strftime('%H:%M')}"

    enriched = []
    for item in items:
        if isinstance(item, dict) and item.get("type") == "jaarinsigne_2026_group":
            badge = _CATALOGUE.get("jaarinsigne_2026")
            if badge is None:
                continue
            scout = item["scout"]
            requests = item["requests"]
            requests.sort(key=lambda sr: sr.created_at)
            level_index = requests[0].progress_entry.level_index
            if level_index >= len(badge["levels"]):
                continue
            speltak_level = badge["levels"][level_index]
            _, scout_min_punten = _jaarinsigne_2026_resolve_level(db, scout.id)
            scout_score = jaarinsigne_2026_svc.compute_score(db, scout.id)
            eisen = []
            for sr in requests:
                pe = sr.progress_entry
                if pe.step_index >= len(speltak_level["steps"]):
                    continue
                step = speltak_level["steps"][pe.step_index]
                eisen.append({
                    "entry_id": pe.id,
                    "step_titel": step.get("titel", ""),
                    "step_text": step.get("text", ""),
                    "step_index": pe.step_index,
                    "score_line": _jaarinsigne_2026_drempel_score_line(
                        step.get("drempel"), scout_score, scout_min_punten,
                    ),
                })
            eisen.sort(key=lambda e: e["step_index"])
            included_details = jaarinsigne_2026_svc.get_included_details(db, scout.id)
            enriched.append({
                "type": "jaarinsigne_2026_group",
                "scout_id": scout.id,
                "scout_name": scout.name or scout.email,
                "badge_title": badge["title"],
                "speltak_slug": speltak_level.get("slug"),
                "speltak_name": speltak_level.get("name", ""),
                "speltak_leeftijd": speltak_level.get("leeftijd", ""),
                "eisen": eisen,
                "included_details": included_details,
                "requested_at": _fmt_date(requests[0].created_at),
            })
        else:
            sr = item
            pe = sr.progress_entry
            badge = _CATALOGUE.get(pe.badge_slug)
            if badge is None:
                continue
            level = badge["levels"][pe.level_index]
            step = level["steps"][pe.step_index]
            enriched.append({
                "type": "single",
                "entry_id": pe.id,
                "scout_name": pe.user.name or pe.user.email,
                "badge_title": badge["title"],
                "niveau_number": pe.step_index + 1,
                "level_number": pe.level_index + 1,
                "level_name": level["name"],
                "step_text": step["text"],
                "notes": pe.notes,
                "requested_at": _fmt_date(sr.created_at),
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
        mentor_name = current_user.name or current_user.email

        _emit_signed_off_email(
            background_tasks,
            scout_email=scout.email,
            scout_name=scout.name or scout.email,
            mentor_name=mentor_name,
            badge=badge, level=level, entry=entry,
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
        mentor_name = current_user.name or current_user.email

        _emit_rejected_email(
            background_tasks,
            scout_email=scout.email,
            scout_name=scout.name or scout.email,
            mentor_name=mentor_name,
            badge=badge, level=level, entry=entry,
            message=message.strip(),
        )

        return _partial(request, "signoff_request_item.html", entry_id=entry_id, confirmed=False, error="", rejected=True)
    except (progress_svc.NotFound, progress_svc.Forbidden) as exc:
        error = "Kon niet afwijzen."
        return _partial(request, "signoff_request_item.html", entry_id=entry_id, confirmed=False, error=error)


# ── Batch confirm / reject for jaarinsigne_2026 ──────────────────────────────

@router.post(
    "/scouts/{scout_id}/jaarinsigne_2026/confirm-signoff",
    response_class=HTMLResponse,
)
async def jaarinsigne_2026_confirm_signoff(
    request: Request,
    scout_id: str,
    background_tasks: BackgroundTasks,
    comment: str = Form(""),
    db: Session = Depends(get_db),
):
    current_user = _get_current_user(request, db)
    if current_user is None:
        return RedirectResponse(url="/login", status_code=303)

    badge = _CATALOGUE.get("jaarinsigne_2026")
    confirmed = False
    error = ""
    try:
        affected = progress_svc.confirm_jaarinsigne_2026_signoff(
            db, current_user.id, scout_id, comment=comment.strip() or None
        )
        confirmed = True
        scout = db.get(User, scout_id)
        if scout and scout.email and affected and badge is not None:
            level = badge["levels"][affected[0].level_index]
            eisen = _jaarinsigne_eisen_for_entries(level, affected)
            mentor_comment = next(
                (e.mentor_comment for e in affected if e.mentor_comment), None,
            )
            background_tasks.add_task(
                send_scout_jaarinsigne_signed_off_email,
                scout.email,
                scout.name or scout.email,
                badge["slug"], badge["title"],
                level.get("name", ""), level.get("leeftijd", ""),
                eisen,
                current_user.name or current_user.email,
                mentor_comment,
            )
    except (progress_svc.NotFound, progress_svc.Forbidden, progress_svc.Conflict) as exc:
        error = "Kon niet aftekenen." if not isinstance(exc, progress_svc.Conflict) else "Al afgetekend."

    return _partial(
        request,
        "signoff_request_jaarinsigne_2026_item.html",
        scout_id=scout_id,
        confirmed=confirmed,
        error=error,
    )


@router.post(
    "/scouts/{scout_id}/jaarinsigne_2026/reject-signoff",
    response_class=HTMLResponse,
)
async def jaarinsigne_2026_reject_signoff(
    request: Request,
    scout_id: str,
    background_tasks: BackgroundTasks,
    message: str = Form(""),
    db: Session = Depends(get_db),
):
    current_user = _get_current_user(request, db)
    if current_user is None:
        return RedirectResponse(url="/login", status_code=303)

    badge = _CATALOGUE.get("jaarinsigne_2026")
    try:
        affected = progress_svc.reject_jaarinsigne_2026_signoff(
            db, current_user.id, scout_id, message.strip()
        )
        scout = db.get(User, scout_id)
        if scout and scout.email and affected and badge is not None:
            level = badge["levels"][affected[0].level_index]
            eisen = _jaarinsigne_eisen_for_entries(level, affected)
            background_tasks.add_task(
                send_scout_jaarinsigne_rejected_email,
                scout.email,
                scout.name or scout.email,
                badge["slug"], badge["title"],
                level.get("name", ""), level.get("leeftijd", ""),
                eisen,
                current_user.name or current_user.email,
                message.strip(),
            )
        return _partial(
            request,
            "signoff_request_jaarinsigne_2026_item.html",
            scout_id=scout_id,
            confirmed=False,
            error="",
            rejected=True,
        )
    except (progress_svc.NotFound, progress_svc.Forbidden):
        return _partial(
            request,
            "signoff_request_jaarinsigne_2026_item.html",
            scout_id=scout_id,
            confirmed=False,
            error="Kon niet afwijzen.",
        )


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
            _emit_request_email(
                background_tasks, mentor_email=mentor.email, scout_name=scout_name,
                badge=badge, level=level, entry=entry, notes=entry.notes,
            )
    except progress_svc.NotFound as exc:
        if str(exc) == "no_eligible_mentors":
            error = "Er zijn geen leiders gevonden die kunnen aftekenen."
        else:
            return RedirectResponse(url="/", status_code=303)
    except progress_svc.Forbidden:
        error = "Je bent geen lid van die speltak."
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
            _emit_request_email(
                background_tasks, mentor_email=mentor.email, scout_name=scout_name,
                badge=badge, level=level, entry=entry, notes=entry.notes,
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
            badge["type"] = detail.get("type", "gewoon")
            if detail.get("type") == "jaarinsigne":
                slug_progress = all_progress.get(badge["slug"], {})
                jl = progress_svc.get_jaarinsigne_level(db, scout_id, badge["slug"]) if db and scout_id else None
                if jl:
                    speltak_slug = jl.speltak_slug
                elif db and scout_id:
                    speltak_slug = groups_svc.get_user_primary_speltak_type(db, scout_id)
                else:
                    speltak_slug = None
                resolved_level_index = _CATALOGUE.resolve_jaarinsigne_level_index(detail, speltak_slug)
                levels_to_show = jaarinsigne_levels_for_scout(detail, slug_progress, resolved_level_index)
                if levels_to_show:
                    cards = []
                    for level in levels_to_show:
                        li = level["level_index"]
                        n_steps = len(level["steps"])
                        cards.append({
                            "index": li,
                            "name": level["name"],
                            "short_name": level["kort"],
                            "image": f"/images/{badge['slug']}.png",
                            "total": n_steps,
                            "completed": sum(
                                1 for step_idx in range(n_steps)
                                if slug_progress.get((li, step_idx))
                                and slug_progress[(li, step_idx)].status == "signed_off"
                            ),
                            "completed_at": None,
                        })
                    badge["level_cards"] = cards
                else:
                    # Render a placeholder card so the leader can navigate to
                    # the scout's badge page and override the level if needed.
                    badge["level_cards"] = [{
                        "index": -1,
                        "name": "Niet beschikbaar voor de speltak van deze scout",
                        "short_name": "—",
                        "image": f"/images/{badge['slug']}.png",
                        "total": 0,
                        "completed": 0,
                        "completed_at": None,
                        "unavailable": True,
                    }]
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


def _require_scout_access(
    request: Request, scout_id: str, db: Session,
) -> tuple[User | None, User | None]:
    """Return ``(current_user, scout)``.

    - ``(User, User)`` — caller may proceed.
    - ``(None, None)`` — request is unauthenticated; caller should redirect to
      ``"/login"``.
    - ``(User, None)`` — authenticated but the access check failed (bad
      ``scout_id`` format, self-access, missing scout, or no view permission);
      caller should redirect to ``"/"``.

    The helper never returns a :class:`RedirectResponse` itself — keeping the
    response construction in the caller (with string-literal URLs) prevents
    user-controlled ``scout_id`` data from flowing into the response body and
    silences CodeQL's ``py/reflective-xss`` taint analysis.

    ``scout_id`` is validated against ``_UUID_RE`` up-front. UUIDs in this
    project are generated server-side via ``uuid4``, so a well-formed value
    is the only legitimate input here — rejecting garbage early avoids a
    DB lookup with a tainted string (CodeQL ``py/url-redirection`` defence
    in depth).
    """
    current_user = _get_current_user(request, db)
    if current_user is None:
        return None, None
    if not _UUID_RE.match(scout_id):
        return current_user, None
    if scout_id == current_user.id:
        return current_user, None
    scout = db.get(User, scout_id)
    if scout is None or not groups_svc.can_view_scout_progress(current_user, db, scout_id):
        return current_user, None
    return current_user, scout


@router.get("/scouts/{scout_id}", response_class=HTMLResponse)
async def scout_progress_home(scout_id: str, request: Request, only_in_progress: str | None = Query(None), db: Session = Depends(get_db)):
    only_in_progress = lenient_int(only_in_progress) or 0
    current_user, scout = _require_scout_access(request, scout_id, db)
    if scout is None:
        return RedirectResponse("/login" if current_user is None else "/", status_code=303)

    edit_speltak_id = groups_svc.get_edit_speltak_for_scout(db, current_user.id, scout.id)
    all_progress: dict[str, dict] = {}
    for entry in progress_svc.list_progress(db, scout.id):
        all_progress.setdefault(entry.badge_slug, {})[(entry.level_index, entry.step_index)] = entry

    all_badges, signed_off_niveaus = _build_badge_catalogue(all_progress, db=db, scout_id=scout.id)
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
    niveau: str | None = Query(None),
    speltak: str | None = Query(None),
    db: Session = Depends(get_db),
):
    niveau = lenient_int(niveau)
    current_user, scout = _require_scout_access(request, scout_id, db)
    if scout is None:
        return RedirectResponse("/login" if current_user is None else "/", status_code=303)

    badge = _CATALOGUE.get(slug)
    if badge is None:
        return RedirectResponse(f"/scouts/{scout.id}", status_code=303)
    badge_slug = badge["slug"]

    edit_speltak_id = groups_svc.get_edit_speltak_for_scout(db, current_user.id, scout.id)
    can_edit = edit_speltak_id is not None
    progress_map: dict[tuple[int, int], ProgressEntry] = {}
    for entry in progress_svc.list_progress(db, scout.id, badge_slug=badge_slug):
        progress_map[(entry.level_index, entry.step_index)] = entry

    if badge.get("type") == "jaarinsigne":
        jl = progress_svc.get_jaarinsigne_level(db, scout.id, badge_slug)
        if jl:
            speltak_slug = jl.speltak_slug
        else:
            speltak_slug = groups_svc.get_user_primary_speltak_type(db, scout.id)
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
                "_post_url": f"/scouts/{scout.id}/set-progress",
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
            "_post_url": f"/scouts/{scout.id}/set-progress",
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
    if not badge:
        return RedirectResponse("/", status_code=303)
    badge_slug = badge["slug"]
    valid_slugs = {l["slug"] for l in badge["levels"]} if badge.get("type") == "jaarinsigne" else set()
    if speltak_slug not in valid_slugs or not groups_svc.can_user_set_own_jaarinsigne_level(db, current_user.id):
        return RedirectResponse(f"/badges/{badge_slug}", status_code=303)
    progress_svc.set_jaarinsigne_level(db, current_user.id, badge_slug, speltak_slug, current_user.id)
    return RedirectResponse(f"/badges/{badge_slug}", status_code=303)


@router.post("/scouts/{scout_id}/badges/{slug}/set-level", response_class=HTMLResponse)
async def scout_set_jaarinsigne_level(
    scout_id: str, slug: str, request: Request,
    speltak_slug: str = Form(...),
    db: Session = Depends(get_db),
):
    current_user, scout = _require_scout_access(request, scout_id, db)
    if scout is None:
        return RedirectResponse("/login" if current_user is None else "/", status_code=303)
    if not groups_svc.get_edit_speltak_for_scout(db, current_user.id, scout.id):
        return RedirectResponse(f"/scouts/{scout.id}", status_code=303)
    badge = _CATALOGUE.get(slug)
    if not badge:
        return RedirectResponse(f"/scouts/{scout.id}", status_code=303)
    badge_slug = badge["slug"]
    valid_slugs = {l["slug"] for l in badge["levels"]} if badge.get("type") == "jaarinsigne" else set()
    if speltak_slug not in valid_slugs:
        return RedirectResponse(f"/scouts/{scout.id}/badges/{badge_slug}", status_code=303)
    progress_svc.set_jaarinsigne_level(db, scout.id, badge_slug, speltak_slug, current_user.id)
    return RedirectResponse(f"/scouts/{scout.id}/badges/{badge_slug}", status_code=303)


_jaarinsigne_2026_resolve_level = jaarinsigne_2026_svc.resolve_user_level


def _jaarinsigne_2026_signoff_state(
    db: Session, user_id: str, level: dict | None
) -> str:
    """Return one of ``'not_ready'``, ``'ready'``, ``'pending'``, ``'done'``."""
    if not level:
        return "not_ready"
    statuses: list[str] = []
    for step in level["steps"]:
        e = db.query(ProgressEntry).filter_by(
            user_id=user_id,
            badge_slug="jaarinsigne_2026",
            level_index=level["level_index"],
            step_index=step["index"],
        ).first()
        statuses.append(e.status if e else "none")
    if statuses and all(s == "signed_off" for s in statuses):
        return "done"
    if any(s == "pending_signoff" for s in statuses):
        return "pending"
    if statuses and all(s in ("work_done", "signed_off") for s in statuses):
        return "ready"
    return "not_ready"


def _jaarinsigne_2026_pending_mentors(
    db: Session, user_id: str, level: dict | None
) -> list[User]:
    """Return the de-duplicated list of mentors currently invited to sign off any
    jaarinsigne_2026 eis for this scout at the given level."""
    if not level:
        return []
    seen: set[str] = set()
    out: list[User] = []
    entry_ids = []
    for step in level["steps"]:
        e = db.query(ProgressEntry).filter_by(
            user_id=user_id,
            badge_slug="jaarinsigne_2026",
            level_index=level["level_index"],
            step_index=step["index"],
        ).first()
        if e:
            entry_ids.append(e.id)
    if not entry_ids:
        return []
    for sr in db.query(SignoffRequest).filter(
        SignoffRequest.progress_entry_id.in_(entry_ids)
    ).all():
        if sr.mentor_id and sr.mentor_id not in seen:
            seen.add(sr.mentor_id)
            mentor = db.get(User, sr.mentor_id)
            if mentor is not None:
                out.append(mentor)
    return out


def _build_jaarinsigne_2026_body_context(
    db: Session, current_user: User, signoff_error: str = "",
) -> dict:
    """Re-compute every piece of context the jaarinsigne_2026 body partial needs."""
    badge = _CATALOGUE.get("jaarinsigne_2026")
    speltak_slug, speltak_min_punten = _jaarinsigne_2026_resolve_level(db, current_user.id)
    level = next((lv for lv in badge["levels"] if lv["slug"] == speltak_slug), None) \
        if (badge and speltak_slug) else None

    progress_map: dict[tuple[int, int], ProgressEntry] = {}
    for e in progress_svc.list_progress(db, current_user.id, badge_slug="jaarinsigne_2026"):
        progress_map[(e.level_index, e.step_index)] = e
    previous_mentors = progress_svc.list_previous_mentors(db, current_user.id)
    scout_signoff_options = _build_signoff_options(db, current_user)

    score_summary = jaarinsigne_2026_svc.get_score_summary(
        db, current_user.id, speltak_slug, speltak_min_punten
    ) if speltak_slug else None
    available_to_include = jaarinsigne_2026_svc.get_available_to_include(db, current_user.id)
    included_details = jaarinsigne_2026_svc.get_included_details(db, current_user.id)
    included_summary = jaarinsigne_2026_svc.summarize_items(included_details)
    available_summary = jaarinsigne_2026_svc.summarize_additional(
        available_to_include, included_details
    )

    signoff_state = _jaarinsigne_2026_signoff_state(db, current_user.id, level)
    pending_mentors = _jaarinsigne_2026_pending_mentors(db, current_user.id, level) \
        if signoff_state == "pending" else []

    return {
        "current_user": current_user,
        "badge": badge,
        "level": level,
        "progress_map": progress_map,
        "previous_mentors": previous_mentors,
        "scout_signoff_options": scout_signoff_options,
        "score_summary": score_summary,
        "available_to_include": available_to_include,
        "included_details": included_details,
        "included_summary": included_summary,
        "available_summary": available_summary,
        "signoff_state": signoff_state,
        "pending_mentors": pending_mentors,
        "signoff_error": signoff_error,
    }


def _jaarinsigne_2026_body_response(
    request: Request, db: Session, current_user: User, signoff_error: str = "",
):
    """Render the jaarinsigne_2026 body partial with a fresh context."""
    return _TEMPLATES.TemplateResponse(
        request=request,
        name="partials/jaarinsigne_2026_body.html",
        context=_build_jaarinsigne_2026_body_context(db, current_user, signoff_error),
    )


def _translate_signoff_exc(exc: Exception) -> str:
    """Map a service-layer exception to a Dutch error string for the UI."""
    msg = str(exc)
    if msg == "self_signoff":
        return "Je kunt jezelf niet uitnodigen om af te tekenen."
    if msg == "no_entries":
        return "Er zijn geen eisen die klaar staan voor aftekening."
    if msg == "no_eligible_mentors":
        return "Geen geschikte (bege-)leider gevonden om af te tekenen."
    if msg == "already_signed_off":
        return "Deze stap is al afgetekend."
    if msg == "invalid_email":
        return "Geef een geldig e-mailadres op."
    if msg == "not_member":
        return "Je bent geen lid van die speltak."
    return "Aanvraag aftekening mislukt."


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

    # Block editing while a signoff request is pending.
    speltak_slug, speltak_min_punten = _jaarinsigne_2026_resolve_level(db, current_user.id)
    badge = _CATALOGUE.get("jaarinsigne_2026")
    level = next((lv for lv in badge["levels"] if lv["slug"] == speltak_slug), None) \
        if (badge and speltak_slug) else None
    if _jaarinsigne_2026_signoff_state(db, current_user.id, level) == "pending":
        if request.headers.get("HX-Request"):
            return _jaarinsigne_2026_body_response(request, db, current_user)
        return RedirectResponse(url="/badges/jaarinsigne_2026", status_code=303)

    jaarinsigne_2026_svc.toggle_inclusion(db, current_user.id, badge_slug, level_index, step_index)

    if speltak_slug:
        jaarinsigne_2026_svc.update_progress_entries(db, current_user.id, speltak_slug, speltak_min_punten)

    if request.headers.get("HX-Request"):
        return _jaarinsigne_2026_body_response(request, db, current_user)

    return RedirectResponse(url="/badges/jaarinsigne_2026", status_code=303)


# ── Batch sign-off endpoints for jaarinsigne_2026 ─────────────────────────────


def _jaarinsigne_2026_drempel_score_line(
    drempel: dict | None, score: dict, speltak_min_punten: int,
) -> str:
    """Return a Dutch sentence describing how the scout scored against this drempel.

    Returns an empty string when the drempel is missing or unknown.
    """
    if not drempel:
        return ""
    t = drempel.get("type")
    if t == "punten":
        return f'{score["total_punten"]} punten behaald (minimaal {drempel["minimum"]})'
    if t == "leiding_bepaald":
        return (
            f'{score["total_punten"]} punten behaald '
            f'(minimaal {speltak_min_punten}, bepaald door leiding)'
        )
    if t == "groen":
        return (
            f'{score["total_groen"]} "groene" eisen behaald '
            f'(minimaal {drempel["minimum"]})'
        )
    if t == "niveau2":
        return (
            f'{score["total_niveau2"]} eisen op niveau 2 behaald '
            f'(minimaal {drempel["minimum"]})'
        )
    if t == "niveau3":
        return (
            f'{score["total_niveau3"]} eisen op niveau 3 behaald '
            f'(minimaal {drempel["minimum"]})'
        )
    if t == "insignes":
        return (
            f'{score["distinct_insignes"]} verschillende insignes behaald '
            f'(minimaal {drempel["minimum"]})'
        )
    return ""


def _jaarinsigne_eisen_for_entries(level: dict, entries) -> list[dict]:
    """Build the ``eisen`` list (number/titel/text) the jaarinsigne e-mail
    templates expect, given a sequence of ProgressEntry rows at this level.

    Entries are sorted by ``step_index`` so the e-mail reads 1, 2, 3.
    """
    out: list[dict] = []
    sorted_entries = sorted(entries, key=lambda e: e.step_index)
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


def _send_jaarinsigne_2026_mentor_emails(
    background_tasks: BackgroundTasks,
    invited: list,
    created_mentor: User | None,
    scout_name: str,
    badge: dict | None,
    level: dict | None,
    eisen: list,
):
    """Send one batched e-mail per invited mentor.

    Mentors freshly created via ``request_jaarinsigne_2026_signoff`` receive
    the "invite" variant (CTA points at /register); existing users receive the
    plain request variant (CTA points at /signoff-requests).
    """
    if badge is None or level is None or not eisen:
        return
    speltak_name = level.get("name", "")
    speltak_leeftijd = level.get("leeftijd", "")
    for mentor in invited:
        if not mentor.email:
            continue
        if created_mentor is not None and mentor.id == created_mentor.id:
            background_tasks.add_task(
                send_mentor_jaarinsigne_signoff_invite_email,
                mentor.email, scout_name, badge["slug"], badge["title"],
                speltak_name, speltak_leeftijd, eisen, None,
            )
        else:
            background_tasks.add_task(
                send_mentor_jaarinsigne_signoff_request_email,
                mentor.email, scout_name, badge["slug"], badge["title"],
                speltak_name, speltak_leeftijd, eisen, None,
            )


@router.post("/badges/jaarinsigne_2026/request-signoff-speltak", response_class=HTMLResponse)
async def jaarinsigne_2026_request_signoff_speltak(
    request: Request,
    background_tasks: BackgroundTasks,
    speltak_id: str = Form(...),
    db: Session = Depends(get_db),
):
    current_user = _get_current_user(request, db)
    if current_user is None:
        return RedirectResponse(url="/login", status_code=303)

    speltak_slug, _ = _jaarinsigne_2026_resolve_level(db, current_user.id)
    badge = _CATALOGUE.get("jaarinsigne_2026")
    level = next((lv for lv in badge["levels"] if lv["slug"] == speltak_slug), None) \
        if (badge and speltak_slug) else None
    eisen = [
        {"number": i + 1, "titel": step.get("titel", ""), "text": step.get("text", "")}
        for i, step in enumerate(level["steps"])
    ] if level else []
    scout_name = current_user.name or current_user.email.split("@")[0]

    signoff_error = ""
    try:
        _, invited = progress_svc.request_jaarinsigne_2026_signoff_speltak(
            db, current_user.id, speltak_id
        )
        _send_jaarinsigne_2026_mentor_emails(
            background_tasks, invited, None, scout_name, badge, level, eisen,
        )
    except (progress_svc.NotFound, progress_svc.Forbidden, progress_svc.Conflict) as exc:
        signoff_error = _translate_signoff_exc(exc)

    if request.headers.get("HX-Request"):
        return _jaarinsigne_2026_body_response(request, db, current_user, signoff_error)
    return RedirectResponse(url="/badges/jaarinsigne_2026", status_code=303)


@router.post("/badges/jaarinsigne_2026/request-signoff-members", response_class=HTMLResponse)
async def jaarinsigne_2026_request_signoff_members(
    request: Request,
    background_tasks: BackgroundTasks,
    mentor_ids: list[str] = Form(default=[]),
    db: Session = Depends(get_db),
):
    current_user = _get_current_user(request, db)
    if current_user is None:
        return RedirectResponse(url="/login", status_code=303)

    speltak_slug, _ = _jaarinsigne_2026_resolve_level(db, current_user.id)
    badge = _CATALOGUE.get("jaarinsigne_2026")
    level = next((lv for lv in badge["levels"] if lv["slug"] == speltak_slug), None) \
        if (badge and speltak_slug) else None
    eisen = [
        {"number": i + 1, "titel": step.get("titel", ""), "text": step.get("text", "")}
        for i, step in enumerate(level["steps"])
    ] if level else []
    scout_name = current_user.name or current_user.email.split("@")[0]

    signoff_error = ""
    try:
        _, invited = progress_svc.request_jaarinsigne_2026_signoff_members(
            db, current_user.id, mentor_ids
        )
        _send_jaarinsigne_2026_mentor_emails(
            background_tasks, invited, None, scout_name, badge, level, eisen,
        )
    except (progress_svc.NotFound, progress_svc.Forbidden, progress_svc.Conflict) as exc:
        signoff_error = _translate_signoff_exc(exc)

    if request.headers.get("HX-Request"):
        return _jaarinsigne_2026_body_response(request, db, current_user, signoff_error)
    return RedirectResponse(url="/badges/jaarinsigne_2026", status_code=303)


@router.post("/badges/jaarinsigne_2026/request-signoff", response_class=HTMLResponse)
async def jaarinsigne_2026_request_signoff_direct(
    request: Request,
    background_tasks: BackgroundTasks,
    mentor_email: str = Form(...),
    db: Session = Depends(get_db),
):
    current_user = _get_current_user(request, db)
    if current_user is None:
        return RedirectResponse(url="/login", status_code=303)

    speltak_slug, _ = _jaarinsigne_2026_resolve_level(db, current_user.id)
    badge = _CATALOGUE.get("jaarinsigne_2026")
    level = next((lv for lv in badge["levels"] if lv["slug"] == speltak_slug), None) \
        if (badge and speltak_slug) else None
    eisen = [
        {"number": i + 1, "titel": step.get("titel", ""), "text": step.get("text", "")}
        for i, step in enumerate(level["steps"])
    ] if level else []
    scout_name = current_user.name or current_user.email.split("@")[0]

    signoff_error = ""
    try:
        if _UUID_RE.match(mentor_email.strip()):
            _, invited = progress_svc.request_jaarinsigne_2026_signoff_members(
                db, current_user.id, [mentor_email.strip()]
            )
            _send_jaarinsigne_2026_mentor_emails(
                background_tasks, invited, None, scout_name, badge, level, eisen,
            )
        else:
            _, mentor, created = progress_svc.request_jaarinsigne_2026_signoff(
                db, current_user.id, mentor_email
            )
            _send_jaarinsigne_2026_mentor_emails(
                background_tasks, [mentor], mentor if created else None,
                scout_name, badge, level, eisen,
            )
    except (progress_svc.NotFound, progress_svc.Forbidden, progress_svc.Conflict) as exc:
        signoff_error = _translate_signoff_exc(exc)

    if request.headers.get("HX-Request"):
        return _jaarinsigne_2026_body_response(request, db, current_user, signoff_error)
    return RedirectResponse(url="/badges/jaarinsigne_2026", status_code=303)


@router.post("/badges/jaarinsigne_2026/cancel-signoff", response_class=HTMLResponse)
async def jaarinsigne_2026_cancel_signoff(
    request: Request,
    db: Session = Depends(get_db),
):
    current_user = _get_current_user(request, db)
    if current_user is None:
        return RedirectResponse(url="/login", status_code=303)

    progress_svc.cancel_jaarinsigne_2026_signoff_requests(db, current_user.id)

    if request.headers.get("HX-Request"):
        return _jaarinsigne_2026_body_response(request, db, current_user)
    return RedirectResponse(url="/badges/jaarinsigne_2026", status_code=303)


@router.get("/scouts/{scout_id}/badges/{slug}/niveau-checks/{niveau_index}", response_class=HTMLResponse)
async def scout_niveau_checks(
    scout_id: str, slug: str, niveau_index: int,
    request: Request,
    db: Session = Depends(get_db),
):
    current_user, scout = _require_scout_access(request, scout_id, db)
    if scout is None:
        return RedirectResponse("/login" if current_user is None else "/", status_code=303)

    badge = _CATALOGUE.get(slug)
    if badge is None:
        return HTMLResponse("")
    badge_slug = badge["slug"]

    progress_map: dict[tuple[int, int], ProgressEntry] = {}
    for entry in progress_svc.list_progress(db, scout.id, badge_slug=badge_slug):
        progress_map[(entry.level_index, entry.step_index)] = entry

    return _partial(
        request, "scout_niveau_checks.html",
        scout_id=scout.id,
        slug=badge_slug,
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

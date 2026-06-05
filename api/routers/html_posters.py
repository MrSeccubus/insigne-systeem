"""Poster designer routes (#132, Phase 1: mechanism + persistence).

A poster's body is one Jinja partial (``partials/poster_body.html``) rendered
from the poster's params; both the live preview iframe and the print window load
``GET /posters/render`` so preview == print. State-changing routes are POST
(covered by the app-wide SameSite + Origin/Referer CSRF layers). Redirects use
server-derived ids; access helpers return data only.
"""
import re as _re
from pathlib import Path

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.orm import Session

from insigne import groups as groups_svc
from insigne import posters as posters_svc
from insigne import poster_templates as pt
from insigne import progress as progress_svc
from insigne import users as users_svc
from insigne.badges import BadgeCatalogue
from insigne.database import get_db
from insigne.models import User as UserModel
from routers.users import _get_current_user
from templates import templates as _TEMPLATES

_CATALOGUE = BadgeCatalogue(Path(__file__).parent.parent / "data")

router = APIRouter()

_UUID_RE = _re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$", _re.I
)


def _require_user(request: Request, db: Session) -> UserModel | None:
    """Authenticated user or None (data only; caller builds the redirect)."""
    return _get_current_user(request, db)


def _page(request: Request, name: str, db: Session, **ctx):
    ctx.setdefault("current_user", _get_current_user(request, db))
    return _TEMPLATES.TemplateResponse(request=request, name=name, context=ctx)


def _clean_paper(paper_size: str | None, orientation: str | None) -> tuple[str, str]:
    ps = paper_size if paper_size in pt.PAPER_SIZES_MM else "A4"
    orient = orientation if orientation in pt.ORIENTATIONS else "portrait"
    return ps, orient


def _clean_slugs(slugs: list[str]) -> list[str]:
    """Keep only real catalogue slugs, de-duplicated, preserving order."""
    seen: set[str] = set()
    out: list[str] = []
    for s in slugs:
        if s not in seen and _CATALOGUE.get(s) is not None:
            seen.add(s)
            out.append(s)
    return out


def _badge_image(badge: dict, niveau: int) -> str | None:
    """Image URL for a badge at a given niveau (1–3). Jaarinsigne badges have a
    single image; regular badges have one per niveau."""
    imgs = badge.get("images") or []
    if not imgs:
        return None
    if badge.get("type") == "jaarinsigne":
        return imgs[0]
    return imgs[min(max(niveau - 1, 0), len(imgs) - 1)]


def _params_from(poster_type: str, mapping) -> dict:
    """Parse + clean all params for a poster type from a form/query mapping."""
    params = pt.parse_all_params(poster_type, mapping)
    if poster_type == "badges":
        params["badge_slugs"] = _clean_slugs(params.get("badge_slugs", []))
    return params


def _poster_badges(params: dict) -> list[dict]:
    """Resolve the selected slugs to {title, image} for the badge-grid body."""
    niveau = params.get("niveau", 1)
    out: list[dict] = []
    for slug in params.get("badge_slugs", []):
        b = _CATALOGUE.get(slug)
        if b:
            out.append({"title": b["title"], "image": _badge_image(b, niveau)})
    return out


def _picker_context(db: Session, user: UserModel, poster) -> dict:
    """Badge picker data for the designer: the full catalogue (grouped) plus the
    quick-select filter sets (your favourites / progress, and — for a
    speltak-scoped poster — the speltak's favourites / progress)."""
    fav = users_svc.get_user_favorite_slugs(db, user.id)
    prog = {e.badge_slug for e in progress_svc.list_progress(db, user.id)}
    speltak_fav: set[str] = set()
    speltak_prog: set[str] = set()
    if poster is not None and poster.speltak_id:
        speltak_fav = groups_svc.get_speltak_favorite_slugs(db, poster.speltak_id)
        for m in groups_svc.list_speltak_members(db, poster.speltak_id):
            speltak_prog |= {e.badge_slug for e in progress_svc.list_progress(db, m.user_id)}
    return {
        "badge_catalogue": _CATALOGUE.list(),
        "category_labels": _CATALOGUE.category_labels,
        "filter_sets": {
            "all": [info["slug"] for items in _CATALOGUE.list().values() for info in items],
            "favorites": sorted(fav),
            "progress": sorted(prog),
            "speltak_favorites": sorted(speltak_fav),
            "speltak_progress": sorted(speltak_prog),
        },
    }


# ── List ────────────────────────────────────────────────────────────────────

@router.get("/posters", response_class=HTMLResponse)
def posters_list(request: Request, db: Session = Depends(get_db)):
    user = _require_user(request, db)
    if user is None:
        return RedirectResponse("/login", status_code=303)
    visible = posters_svc.list_visible_to(db, user)
    return _page(
        request, "posters/list.html", db,
        current_user=user,
        visible=visible,
        poster_types=pt.POSTER_TYPES,
    )


# ── Designer (new + existing) — static paths declared before /{poster_id} ─────

@router.get("/posters/new", response_class=HTMLResponse)
def poster_new(request: Request, type: str = "badges", db: Session = Depends(get_db)):
    user = _require_user(request, db)
    if user is None:
        return RedirectResponse("/login", status_code=303)
    poster_type = type if posters_svc.is_valid_type(type) else "badges"
    spec = pt.base_template(poster_type)
    return _page(
        request, "posters/designer.html", db,
        current_user=user,
        poster=None,
        editable=True,
        poster_type=spec["poster_type"],
        poster_name="",
        paper_size=spec["paper_size"],
        orientation=spec["orientation"],
        params=spec["params"],
        scopes=posters_svc.manageable_scopes(db, user),
        paper_sizes=list(pt.PAPER_SIZES_MM.keys()),
        orientations=list(pt.ORIENTATIONS),
        poster_types=pt.POSTER_TYPES,
        **_picker_context(db, user, None),
    )


@router.get("/posters/render", response_class=HTMLResponse)
def poster_render(request: Request, db: Session = Depends(get_db)):
    """Standalone poster document (no base chrome): paged.js paginates it into
    exact A-series pages. Loaded by the preview iframe and the print window."""
    user = _require_user(request, db)
    if user is None:
        return RedirectResponse("/login", status_code=303)
    q = request.query_params
    poster_type = q.get("type", "badges")
    if not posters_svc.is_valid_type(poster_type):
        poster_type = "badges"
    paper_size, orientation = _clean_paper(q.get("paper_size"), q.get("orientation"))
    params = _params_from(poster_type, q)
    w_mm, h_mm = pt.page_dimensions_mm(paper_size, orientation)
    preview = q.get("preview") == "1"
    return _TEMPLATES.TemplateResponse(
        request=request,
        name="posters/render.html",
        context={
            "poster_type": poster_type,
            "params": params,
            "poster_badges": _poster_badges(params) if poster_type == "badges" else [],
            "paper_size": paper_size,
            "orientation": orientation,
            "page_w_mm": w_mm,
            "page_h_mm": h_mm,
            "page_margin_mm": pt.PAGE_MARGIN_MM,
            "preview": preview,
        },
    )


@router.get("/posters/{poster_id}", response_class=HTMLResponse)
def poster_designer(poster_id: str, request: Request, db: Session = Depends(get_db)):
    user = _require_user(request, db)
    if user is None:
        return RedirectResponse("/login", status_code=303)
    if not _UUID_RE.match(poster_id):
        return RedirectResponse("/posters", status_code=303)
    poster = posters_svc.get(db, poster_id)
    if poster is None or not posters_svc.can_view(db, user, poster):
        return RedirectResponse("/posters", status_code=303)
    return _page(
        request, "posters/designer.html", db,
        current_user=user,
        poster=poster,
        editable=posters_svc.can_edit(db, user, poster),
        poster_type=poster.poster_type,
        poster_name=poster.name,
        paper_size=poster.paper_size,
        orientation=poster.orientation,
        params={**pt.CHROME_PARAMS, **pt.TYPE_PARAM_DEFAULTS.get(poster.poster_type, {}), **(poster.params or {})},
        scopes=posters_svc.manageable_scopes(db, user),
        paper_sizes=list(pt.PAPER_SIZES_MM.keys()),
        orientations=list(pt.ORIENTATIONS),
        poster_types=pt.POSTER_TYPES,
        **_picker_context(db, user, poster),
    )


# ── Create / update / delete ──────────────────────────────────────────────────

@router.post("/posters")
async def poster_create(request: Request, db: Session = Depends(get_db)):
    user = _require_user(request, db)
    if user is None:
        return RedirectResponse("/login", status_code=303)
    form = await request.form()
    poster_type = form.get("poster_type", "badges")
    if not posters_svc.is_valid_type(poster_type):
        poster_type = "badges"
    scope = form.get("scope", "user")
    scope_id = form.get("scope_id") or None
    if not posters_svc.can_save_at(db, user, scope, scope_id):
        return RedirectResponse("/posters", status_code=303)
    paper_size, orientation = _clean_paper(form.get("paper_size"), form.get("orientation"))
    name = (form.get("name") or "").strip() or pt.POSTER_TYPES.get(poster_type, "Poster")
    poster = posters_svc.create(
        db,
        created_by_id=user.id,
        name=name,
        poster_type=poster_type,
        paper_size=paper_size,
        orientation=orientation,
        params=_params_from(poster_type, form),
        scope=scope,
        scope_id=scope_id,
    )
    return RedirectResponse(f"/posters/{poster.id}", status_code=303)


@router.post("/posters/{poster_id}")
async def poster_update(poster_id: str, request: Request, db: Session = Depends(get_db)):
    user = _require_user(request, db)
    if user is None:
        return RedirectResponse("/login", status_code=303)
    if not _UUID_RE.match(poster_id):
        return RedirectResponse("/posters", status_code=303)
    poster = posters_svc.get(db, poster_id)
    if poster is None:
        return RedirectResponse("/posters", status_code=303)
    form = await request.form()
    # A viewer who can't edit the shared template "saves a copy" → personal.
    if not posters_svc.can_edit(db, user, poster):
        if not posters_svc.can_view(db, user, poster):
            return RedirectResponse("/posters", status_code=303)
        paper_size, orientation = _clean_paper(form.get("paper_size"), form.get("orientation"))
        name = (form.get("name") or "").strip() or poster.name
        copy = posters_svc.create(
            db,
            created_by_id=user.id,
            name=name,
            poster_type=poster.poster_type,
            paper_size=paper_size,
            orientation=orientation,
            params=_params_from(poster.poster_type, form),
            scope="user",
            scope_id=None,
        )
        return RedirectResponse(f"/posters/{copy.id}", status_code=303)
    paper_size, orientation = _clean_paper(form.get("paper_size"), form.get("orientation"))
    name = (form.get("name") or "").strip() or poster.name
    posters_svc.update(
        db, poster,
        name=name,
        paper_size=paper_size,
        orientation=orientation,
        params=_params_from(poster.poster_type, form),
    )
    return RedirectResponse(f"/posters/{poster.id}", status_code=303)


@router.post("/posters/{poster_id}/delete")
async def poster_delete(poster_id: str, request: Request, db: Session = Depends(get_db)):
    user = _require_user(request, db)
    if user is None:
        return RedirectResponse("/login", status_code=303)
    if not _UUID_RE.match(poster_id):
        return RedirectResponse("/posters", status_code=303)
    poster = posters_svc.get(db, poster_id)
    if poster is not None and posters_svc.can_edit(db, user, poster):
        posters_svc.delete(db, poster)
    return RedirectResponse("/posters", status_code=303)

"""Poster designer routes (#132) — YAML-definition storage + sandboxed templating.

A poster is a self-contained YAML *definition* (exportable/importable). The
designer holds it as a JSON object (Alpine ``def``); the preview iframe and the
print window load ``GET /posters/render?def=<json>`` so preview == print. Text
fields may contain ``{{ user.name }}`` / ``{{ date }}`` — rendered through the
sandbox in ``insigne.poster_render`` (never the app's Jinja env). State-changing
routes are POST (app-wide SameSite + Origin/Referer CSRF); redirects use
server-derived ids; access helpers return data only.
"""
import json
import re as _re
from pathlib import Path

from fastapi import APIRouter, Depends, File, Request, UploadFile
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from sqlalchemy.orm import Session

from insigne import groups as groups_svc
from insigne import poster_render as poster_render_svc
from insigne import poster_templates as pt
from insigne import posters as posters_svc
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

_MAX_DEF_BYTES = 64 * 1024  # cap on a definition/upload size


def _require_user(request: Request, db: Session) -> UserModel | None:
    return _get_current_user(request, db)


def _page(request: Request, name: str, db: Session, **ctx):
    ctx.setdefault("current_user", _get_current_user(request, db))
    return _TEMPLATES.TemplateResponse(request=request, name=name, context=ctx)


def _clean_definition(defn: dict) -> dict:
    """Normalise + drop badge slugs that aren't real catalogue entries."""
    defn = pt.normalise(defn)
    bb = defn["elements"]["badge_block"]
    seen: set[str] = set()
    bb["badges"] = [s for s in bb["badges"]
                    if s not in seen and not seen.add(s) and _CATALOGUE.get(s)]
    return defn


def _definition_from_json(raw: str | None) -> dict:
    """Parse a definition JSON string from a form/query → cleaned dict.
    Falls back to a fresh badge poster on anything invalid."""
    if not raw or len(raw) > _MAX_DEF_BYTES:
        return _clean_definition(pt.base_definition(0))
    try:
        data = json.loads(raw)
    except (ValueError, TypeError):
        return _clean_definition(pt.base_definition(0))
    return _clean_definition(data)


def _badge_image(badge: dict, niveau: int) -> str | None:
    imgs = badge.get("images") or []
    if not imgs:
        return None
    if badge.get("type") == "jaarinsigne":
        return imgs[0]
    return imgs[min(max(niveau - 1, 0), len(imgs) - 1)]


def _background_css(bg: dict) -> str:
    """CSS background value for the page (colours already sanitised in normalise)."""
    style = bg.get("style")
    start, end = bg.get("start_color", ""), bg.get("end_color", "")
    if style == "solid":
        return start
    if style == "horizontal_gradient":
        return f"linear-gradient(to right,{start},{end})"
    if style == "vertical_gradient":
        return f"linear-gradient(to bottom,{start},{end})"
    return ""


def _all_default_slugs() -> list[str]:
    """Every badge in the default categories (gewoon + buitengewoon) — used when
    the selection is empty ('Leeg is allemaal')."""
    cat = _CATALOGUE.list()
    return [info["slug"] for key in pt.DEFAULT_BADGE_CATEGORIES
            for info in cat.get(key, [])]


def _badge_cell(b: dict, niveaus: list[int]) -> dict | None:
    """A {title, images, gebied} cell for one badge (one image per niveau)."""
    if b.get("type") == "jaarinsigne":
        images = [_badge_image(b, 1)]
    else:
        images = [_badge_image(b, n) for n in niveaus]
    images = [img for img in images if img]
    if not images:
        return None
    return {"title": b["title"], "images": images,
            "gebied": b.get("activiteitengebied", "")}


def _mark_callouts(cells: list[dict]) -> None:
    """Within a column, flag the first badge of each new activiteitengebied."""
    prev = None
    for cell in cells:
        g = cell.get("gebied") or ""
        if g and g != prev:
            cell["callout"] = g
            prev = g
        else:
            cell["callout"] = ""


def _poster_sections(defn: dict) -> list[dict]:
    """Resolve the badge block to sections grouped by catalogue category, in
    catalogue order. Each section's badges are split column-major into ``columns``
    columns: [{label, columns:[[{title, images, callout}], …]}]. Empty selection
    = all default-category badges (gewoon + buitengewoon)."""
    bb = defn.get("elements", {}).get("badge_block", {})
    niveaus = bb.get("niveaus") or [1]
    ncols = max(1, int(bb.get("columns") or 1))
    selected = set(bb.get("badges") or [])
    use_all = not selected
    sections: list[dict] = []
    for cat_key, items in _CATALOGUE.list().items():
        if use_all and cat_key not in pt.DEFAULT_BADGE_CATEGORIES:
            continue
        cells = []
        for info in items:
            if not use_all and info["slug"] not in selected:
                continue
            b = _CATALOGUE.get(info["slug"])
            cell = _badge_cell(b, niveaus) if b else None
            if cell:
                cells.append(cell)
        if not cells:
            continue
        per = (len(cells) + ncols - 1) // ncols          # rows per column (column-major)
        columns = [cells[i:i + per] for i in range(0, len(cells), per)]
        while len(columns) < ncols:                      # pad to a full grid
            columns.append([])
        for col in columns:
            _mark_callouts(col)                           # callouts per column
        # Transpose to aligned rows so the columns line up (no vertical drift):
        # row i holds one badge from each column (or None).
        rows = [[(col[i] if i < len(col) else None) for col in columns]
                for i in range(per)]
        sections.append({
            "label": _CATALOGUE.category_labels.get(cat_key, cat_key),
            "ncols": ncols,
            "rows": rows,
        })
    return sections


def _picker_context(db: Session, user: UserModel, poster) -> dict:
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
            "all": _all_default_slugs(),
            "favorites": sorted(fav),
            "progress": sorted(prog),
            "speltak_favorites": sorted(speltak_fav),
            "speltak_progress": sorted(speltak_prog),
        },
    }


def _designer(request: Request, db: Session, user, *, poster, editable, definition: dict):
    return _page(
        request, "posters/designer.html", db,
        current_user=user,
        poster=poster,
        editable=editable,
        definition=definition,
        scopes=posters_svc.manageable_scopes(db, user),
        paper_sizes=list(pt.PAPER_SIZES_MM.keys()),
        type_labels=pt.TYPE_LABELS,
        **_picker_context(db, user, poster),
    )


# ── List ────────────────────────────────────────────────────────────────────

@router.get("/posters", response_class=HTMLResponse)
def posters_list(request: Request, db: Session = Depends(get_db)):
    user = _require_user(request, db)
    if user is None:
        return RedirectResponse("/login", status_code=303)
    return _page(
        request, "posters/list.html", db,
        current_user=user,
        visible=posters_svc.list_visible_to(db, user),
        type_labels=pt.TYPE_LABELS,
    )


# ── Designer (static paths before /{poster_id}) ───────────────────────────────

@router.get("/posters/new", response_class=HTMLResponse)
def poster_new(request: Request, type: str = "badges", db: Session = Depends(get_db)):
    user = _require_user(request, db)
    if user is None:
        return RedirectResponse("/login", status_code=303)
    code = pt.code_from_key(type, 0)
    return _designer(request, db, user, poster=None, editable=True,
                     definition=pt.base_definition(code))


@router.get("/posters/render", response_class=HTMLResponse)
def poster_render(request: Request, db: Session = Depends(get_db)):
    """Standalone poster doc (no base chrome). Loaded by the preview iframe and
    the print window. The definition arrives as ?def=<json>; text fields are
    rendered through the sandbox with the {user, date, time} context."""
    user = _require_user(request, db)
    if user is None:
        return RedirectResponse("/login", status_code=303)
    q = request.query_params
    defn = _definition_from_json(q.get("def"))
    ctx = poster_render_svc.build_context(user)
    rendered = poster_render_svc.render_definition(defn, ctx)
    w_mm, h_mm = pt.page_dimensions_mm(rendered["paper"], rendered["orientation"])
    poster_type = pt.TYPE_CODES.get(rendered["type"], "badges")
    sel = q.get("sel", "")
    if sel not in ("pagina", "title", "subtitle", "header", "footer", "badge_block"):
        sel = ""
    return _TEMPLATES.TemplateResponse(
        request=request,
        name="posters/render.html",
        context={
            "defn": rendered,
            "poster_type": poster_type,
            "poster_sections": _poster_sections(rendered) if poster_type == "badges" else [],
            "page_w_mm": w_mm,
            "page_h_mm": h_mm,
            "page_margin_mm": pt.PAGE_MARGIN_MM,
            "multi_page": rendered["multi_page"],
            "page_background": _background_css(rendered["elements"]["background"]),
            "preview": q.get("preview") == "1",
            # Proof view: render faithfully (no placeholders, not clickable) and
            # scale to fit the window, but don't open the print dialog.
            "proof": q.get("proof") == "1",
            "sel": sel,
        },
    )


@router.get("/posters/{poster_id}/export")
def poster_export(poster_id: str, request: Request, db: Session = Depends(get_db)):
    user = _require_user(request, db)
    if user is None:
        return RedirectResponse("/login", status_code=303)
    if not _UUID_RE.match(poster_id):
        return RedirectResponse("/posters", status_code=303)
    poster = posters_svc.get(db, poster_id)
    if poster is None or not posters_svc.can_view(db, user, poster):
        return RedirectResponse("/posters", status_code=303)
    yaml_text = pt.to_yaml(posters_svc.get_definition(poster))
    safe = _re.sub(r"[^a-z0-9_-]+", "-", (poster.name or "poster").lower()).strip("-") or "poster"
    return Response(
        content=yaml_text,
        media_type="application/x-yaml",
        headers={"Content-Disposition": f'attachment; filename="{safe}.yml"'},
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
    return _designer(request, db, user, poster=poster,
                     editable=posters_svc.can_edit(db, user, poster),
                     definition=posters_svc.get_definition(poster))


# ── Create / update / delete / import ─────────────────────────────────────────

@router.post("/posters")
async def poster_create(request: Request, db: Session = Depends(get_db)):
    user = _require_user(request, db)
    if user is None:
        return RedirectResponse("/login", status_code=303)
    form = await request.form()
    scope = form.get("scope", "user")
    scope_id = form.get("scope_id") or None
    if not posters_svc.can_save_at(db, user, scope, scope_id):
        return RedirectResponse("/posters", status_code=303)
    defn = _definition_from_json(form.get("definition"))
    poster = posters_svc.create(db, created_by_id=user.id, definition=defn,
                                scope=scope, scope_id=scope_id)
    return RedirectResponse(f"/posters/{poster.id}", status_code=303)


@router.post("/posters/import")
async def poster_import(request: Request, file: UploadFile | None = File(None),
                        db: Session = Depends(get_db)):
    """Import a poster YAML → create a personal poster, open it in the designer.
    Declared before /posters/{poster_id} so 'import' isn't captured as an id."""
    user = _require_user(request, db)
    if user is None:
        return RedirectResponse("/login", status_code=303)
    if file is None:
        return RedirectResponse("/posters", status_code=303)
    raw = (await file.read())[:_MAX_DEF_BYTES]
    try:
        defn = pt.from_yaml(raw.decode("utf-8", "replace"))
    except ValueError:
        return RedirectResponse("/posters", status_code=303)
    poster = posters_svc.create(db, created_by_id=user.id, definition=_clean_definition(defn),
                                scope="user", scope_id=None)
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
    defn = _definition_from_json(form.get("definition"))
    # A viewer who can't edit the shared template saves a personal copy.
    if not posters_svc.can_edit(db, user, poster):
        if not posters_svc.can_view(db, user, poster):
            return RedirectResponse("/posters", status_code=303)
        copy = posters_svc.create(db, created_by_id=user.id, definition=defn,
                                  scope="user", scope_id=None)
        return RedirectResponse(f"/posters/{copy.id}", status_code=303)
    posters_svc.update(db, poster, definition=defn)
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

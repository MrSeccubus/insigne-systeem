from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.orm import Session

from insigne import groups as groups_svc
from insigne.config import config
from insigne.database import get_db
from routers.users import _get_current_user
from templates import templates as _TEMPLATES

router = APIRouter()


def _page(request: Request, name: str, db: Session, **ctx):
    ctx.setdefault("current_user", _get_current_user(request, db))
    return _TEMPLATES.TemplateResponse(request=request, name=name, context=ctx)


def _require_user(request: Request, db: Session):
    user = _get_current_user(request, db)
    if not user:
        return None, RedirectResponse("/login", status_code=303)
    return user, None


# ── Groups list ───────────────────────────────────────────────────────────────

@router.get("/groups", response_class=HTMLResponse)
def groups_list(request: Request, db: Session = Depends(get_db)):
    current_user = _get_current_user(request, db)
    groups = groups_svc.list_groups(db)
    can_create = current_user and (
        current_user.is_admin or config.allow_any_user_to_create_groups
    )
    return _page(request, "groups.html", db,
                 groups=groups, can_create=can_create)


# ── Create group ──────────────────────────────────────────────────────────────

@router.get("/groups/new", response_class=HTMLResponse)
def group_new_form(request: Request, db: Session = Depends(get_db)):
    user, redirect = _require_user(request, db)
    if redirect:
        return redirect
    if not user.is_admin and not config.allow_any_user_to_create_groups:
        return RedirectResponse("/groups", status_code=303)
    return _page(request, "group_edit.html", db, group=None, error=None)


@router.post("/groups/new", response_class=HTMLResponse)
def group_create(
    request: Request,
    name: str = Form(...),
    slug: str = Form(...),
    db: Session = Depends(get_db),
):
    user, redirect = _require_user(request, db)
    if redirect:
        return redirect
    if not user.is_admin and not config.allow_any_user_to_create_groups:
        return RedirectResponse("/groups", status_code=303)
    slug = groups_svc.unique_group_slug(db, slug)
    groups_svc.create_group(db, name=name, slug=slug, created_by_id=user.id)
    return RedirectResponse(f"/groups/{slug}", status_code=303)


# ── Group detail / edit ───────────────────────────────────────────────────────

@router.get("/groups/{slug}", response_class=HTMLResponse)
def group_detail(slug: str, request: Request, db: Session = Depends(get_db)):
    current_user = _get_current_user(request, db)
    group = groups_svc.get_group_by_slug(db, slug)
    if not group:
        return RedirectResponse("/groups", status_code=303)
    can_manage = bool(current_user and groups_svc.can_manage_group(current_user, db, group.id))
    members = groups_svc.list_group_members(db, group.id)
    return _page(request, "group_detail.html", db,
                 group=group, can_manage=can_manage, members=members)


@router.get("/groups/{slug}/edit", response_class=HTMLResponse)
def group_edit_form(slug: str, request: Request, db: Session = Depends(get_db)):
    user, redirect = _require_user(request, db)
    if redirect:
        return redirect
    group = groups_svc.get_group_by_slug(db, slug)
    if not group or not groups_svc.can_manage_group(user, db, group.id):
        return RedirectResponse("/groups", status_code=303)
    return _page(request, "group_edit.html", db, group=group, error=None)


@router.post("/groups/{slug}/edit", response_class=HTMLResponse)
def group_edit(
    slug: str,
    request: Request,
    name: str = Form(...),
    new_slug: str = Form(...),
    db: Session = Depends(get_db),
):
    user, redirect = _require_user(request, db)
    if redirect:
        return redirect
    group = groups_svc.get_group_by_slug(db, slug)
    if not group or not groups_svc.can_manage_group(user, db, group.id):
        return RedirectResponse("/groups", status_code=303)
    existing = groups_svc.get_group_by_slug(db, new_slug)
    if existing and existing.id != group.id:
        return _page(request, "group_edit.html", db,
                     group=group, error="Deze slug is al in gebruik.")
    groups_svc.update_group(db, group, name=name, slug=new_slug)
    return RedirectResponse(f"/groups/{new_slug}", status_code=303)


@router.post("/groups/{slug}/delete", response_class=HTMLResponse)
def group_delete(slug: str, request: Request, db: Session = Depends(get_db)):
    user, redirect = _require_user(request, db)
    if redirect:
        return redirect
    group = groups_svc.get_group_by_slug(db, slug)
    if group and groups_svc.can_manage_group(user, db, group.id):
        groups_svc.delete_group(db, group)
    return RedirectResponse("/groups", status_code=303)


# ── Group member management ───────────────────────────────────────────────────

@router.post("/groups/{slug}/members/add", response_class=HTMLResponse)
def group_add_member(
    slug: str,
    request: Request,
    email: str = Form(...),
    db: Session = Depends(get_db),
):
    user, redirect = _require_user(request, db)
    if redirect:
        return redirect
    group = groups_svc.get_group_by_slug(db, slug)
    if not group or not groups_svc.can_manage_group(user, db, group.id):
        return RedirectResponse("/groups", status_code=303)
    from insigne.models import User as UserModel
    target = db.query(UserModel).filter_by(email=email).first()
    if not target:
        members = groups_svc.list_group_members(db, group.id)
        return _page(request, "group_detail.html", db,
                     group=group, can_manage=True, members=members,
                     error=f"Geen gebruiker gevonden met e-mail {email}.")
    groups_svc.set_group_role(db, user_id=target.id, group_id=group.id, role="groepsleider")
    return RedirectResponse(f"/groups/{slug}", status_code=303)


@router.post("/groups/{slug}/members/{member_id}/remove", response_class=HTMLResponse)
def group_remove_member(
    slug: str, member_id: str,
    request: Request, db: Session = Depends(get_db),
):
    user, redirect = _require_user(request, db)
    if redirect:
        return redirect
    group = groups_svc.get_group_by_slug(db, slug)
    if group and groups_svc.can_manage_group(user, db, group.id):
        groups_svc.remove_group_member(db, user_id=member_id, group_id=group.id)
    return RedirectResponse(f"/groups/{slug}", status_code=303)


# ── Speltak management ────────────────────────────────────────────────────────

@router.get("/groups/{group_slug}/speltakken/new", response_class=HTMLResponse)
def speltak_new_form(group_slug: str, request: Request, db: Session = Depends(get_db)):
    user, redirect = _require_user(request, db)
    if redirect:
        return redirect
    group = groups_svc.get_group_by_slug(db, group_slug)
    if not group or not groups_svc.can_manage_group(user, db, group.id):
        return RedirectResponse(f"/groups/{group_slug}", status_code=303)
    return _page(request, "speltak_edit.html", db, group=group, speltak=None, error=None)


@router.post("/groups/{group_slug}/speltakken/new", response_class=HTMLResponse)
def speltak_create(
    group_slug: str,
    request: Request,
    name: str = Form(...),
    slug: str = Form(...),
    db: Session = Depends(get_db),
):
    user, redirect = _require_user(request, db)
    if redirect:
        return redirect
    group = groups_svc.get_group_by_slug(db, group_slug)
    if not group or not groups_svc.can_manage_group(user, db, group.id):
        return RedirectResponse(f"/groups/{group_slug}", status_code=303)
    if groups_svc.get_speltak_by_slug(db, group.id, slug):
        return _page(request, "speltak_edit.html", db,
                     group=group, speltak=None, error="Deze slug is al in gebruik.")
    groups_svc.create_speltak(db, group_id=group.id, name=name, slug=slug)
    return RedirectResponse(f"/groups/{group_slug}", status_code=303)


@router.get("/groups/{group_slug}/speltakken/{speltak_slug}", response_class=HTMLResponse)
def speltak_detail(
    group_slug: str, speltak_slug: str, request: Request, db: Session = Depends(get_db)
):
    current_user = _get_current_user(request, db)
    group = groups_svc.get_group_by_slug(db, group_slug)
    if not group:
        return RedirectResponse("/groups", status_code=303)
    speltak = groups_svc.get_speltak_by_slug(db, group.id, speltak_slug)
    if not speltak:
        return RedirectResponse(f"/groups/{group_slug}", status_code=303)
    can_manage = bool(current_user and groups_svc.can_manage_speltak(current_user, db, speltak.id))
    members = groups_svc.list_speltak_members(db, speltak.id)
    other_speltakken = [s for s in group.speltakken if s.id != speltak.id]
    return _page(request, "speltak_detail.html", db,
                 group=group, speltak=speltak, members=members,
                 can_manage=can_manage, other_speltakken=other_speltakken)


@router.get("/groups/{group_slug}/speltakken/{speltak_slug}/edit", response_class=HTMLResponse)
def speltak_edit_form(
    group_slug: str, speltak_slug: str, request: Request, db: Session = Depends(get_db)
):
    user, redirect = _require_user(request, db)
    if redirect:
        return redirect
    group = groups_svc.get_group_by_slug(db, group_slug)
    speltak = group and groups_svc.get_speltak_by_slug(db, group.id, speltak_slug)
    if not speltak or not groups_svc.can_manage_group(user, db, group.id):
        return RedirectResponse(f"/groups/{group_slug}", status_code=303)
    return _page(request, "speltak_edit.html", db, group=group, speltak=speltak, error=None)


@router.post("/groups/{group_slug}/speltakken/{speltak_slug}/edit", response_class=HTMLResponse)
def speltak_edit(
    group_slug: str,
    speltak_slug: str,
    request: Request,
    name: str = Form(...),
    new_slug: str = Form(...),
    db: Session = Depends(get_db),
):
    user, redirect = _require_user(request, db)
    if redirect:
        return redirect
    group = groups_svc.get_group_by_slug(db, group_slug)
    speltak = group and groups_svc.get_speltak_by_slug(db, group.id, speltak_slug)
    if not speltak or not groups_svc.can_manage_group(user, db, group.id):
        return RedirectResponse(f"/groups/{group_slug}", status_code=303)
    existing = groups_svc.get_speltak_by_slug(db, group.id, new_slug)
    if existing and existing.id != speltak.id:
        return _page(request, "speltak_edit.html", db,
                     group=group, speltak=speltak, error="Deze slug is al in gebruik.")
    groups_svc.update_speltak(db, speltak, name=name, slug=new_slug)
    return RedirectResponse(f"/groups/{group_slug}", status_code=303)


@router.post("/groups/{group_slug}/speltakken/{speltak_slug}/delete", response_class=HTMLResponse)
def speltak_delete(
    group_slug: str, speltak_slug: str, request: Request, db: Session = Depends(get_db)
):
    user, redirect = _require_user(request, db)
    if redirect:
        return redirect
    group = groups_svc.get_group_by_slug(db, group_slug)
    speltak = group and groups_svc.get_speltak_by_slug(db, group.id, speltak_slug)
    if speltak and groups_svc.can_manage_group(user, db, group.id):
        groups_svc.delete_speltak(db, speltak)
    return RedirectResponse(f"/groups/{group_slug}", status_code=303)


# ── Speltak member actions ────────────────────────────────────────────────────

@router.post("/groups/{group_slug}/speltakken/{speltak_slug}/members/add",
             response_class=HTMLResponse)
def speltak_add_member(
    group_slug: str,
    speltak_slug: str,
    request: Request,
    email: str = Form(...),
    role: str = Form("scout"),
    db: Session = Depends(get_db),
):
    user, redirect = _require_user(request, db)
    if redirect:
        return redirect
    group = groups_svc.get_group_by_slug(db, group_slug)
    speltak = group and groups_svc.get_speltak_by_slug(db, group.id, speltak_slug)
    if not speltak or not groups_svc.can_manage_speltak(user, db, speltak.id):
        return RedirectResponse(f"/groups/{group_slug}", status_code=303)
    from insigne.models import User as UserModel
    target = db.query(UserModel).filter_by(email=email).first()
    error = None
    if not target:
        error = f"Geen gebruiker gevonden met e-mail {email}."
    else:
        groups_svc.set_speltak_role(db, user_id=target.id, speltak_id=speltak.id, role=role)
    if error:
        members = groups_svc.list_speltak_members(db, speltak.id)
        other_speltakken = [s for s in group.speltakken if s.id != speltak.id]
        return _page(request, "speltak_detail.html", db,
                     group=group, speltak=speltak, members=members,
                     can_manage=True, other_speltakken=other_speltakken, error=error)
    return RedirectResponse(f"/groups/{group_slug}/speltakken/{speltak_slug}", status_code=303)


@router.post("/groups/{group_slug}/speltakken/{speltak_slug}/members/new-scout",
             response_class=HTMLResponse)
def speltak_create_scout(
    group_slug: str,
    speltak_slug: str,
    request: Request,
    name: str = Form(...),
    db: Session = Depends(get_db),
):
    user, redirect = _require_user(request, db)
    if redirect:
        return redirect
    group = groups_svc.get_group_by_slug(db, group_slug)
    speltak = group and groups_svc.get_speltak_by_slug(db, group.id, speltak_slug)
    if not speltak or not groups_svc.can_manage_speltak(user, db, speltak.id):
        return RedirectResponse(f"/groups/{group_slug}", status_code=303)
    scout = groups_svc.create_emailless_scout(db, name=name, created_by_id=user.id)
    groups_svc.set_speltak_role(db, user_id=scout.id, speltak_id=speltak.id, role="scout")
    return RedirectResponse(f"/groups/{group_slug}/speltakken/{speltak_slug}", status_code=303)


@router.post("/groups/{group_slug}/speltakken/{speltak_slug}/members/{member_id}/remove",
             response_class=HTMLResponse)
def speltak_remove_member(
    group_slug: str, speltak_slug: str, member_id: str,
    request: Request, db: Session = Depends(get_db),
):
    user, redirect = _require_user(request, db)
    if redirect:
        return redirect
    group = groups_svc.get_group_by_slug(db, group_slug)
    speltak = group and groups_svc.get_speltak_by_slug(db, group.id, speltak_slug)
    if speltak and groups_svc.can_manage_speltak(user, db, speltak.id):
        groups_svc.remove_speltak_member(db, user_id=member_id, speltak_id=speltak.id)
    return RedirectResponse(f"/groups/{group_slug}/speltakken/{speltak_slug}", status_code=303)


@router.post("/groups/{group_slug}/speltakken/{speltak_slug}/members/{member_id}/transfer",
             response_class=HTMLResponse)
def speltak_transfer_member(
    group_slug: str, speltak_slug: str, member_id: str,
    request: Request,
    to_speltak_id: str = Form(...),
    db: Session = Depends(get_db),
):
    user, redirect = _require_user(request, db)
    if redirect:
        return redirect
    group = groups_svc.get_group_by_slug(db, group_slug)
    speltak = group and groups_svc.get_speltak_by_slug(db, group.id, speltak_slug)
    if speltak and groups_svc.can_manage_speltak(user, db, speltak.id):
        groups_svc.transfer_scout(db, user_id=member_id,
                                  from_speltak_id=speltak.id, to_speltak_id=to_speltak_id)
    return RedirectResponse(f"/groups/{group_slug}/speltakken/{speltak_slug}", status_code=303)


@router.post("/groups/{group_slug}/speltakken/{speltak_slug}/members/{member_id}/role",
             response_class=HTMLResponse)
def speltak_set_role(
    group_slug: str, speltak_slug: str, member_id: str,
    request: Request,
    role: str = Form(...),
    db: Session = Depends(get_db),
):
    user, redirect = _require_user(request, db)
    if redirect:
        return redirect
    group = groups_svc.get_group_by_slug(db, group_slug)
    speltak = group and groups_svc.get_speltak_by_slug(db, group.id, speltak_slug)
    if speltak and groups_svc.can_manage_speltak(user, db, speltak.id):
        groups_svc.set_speltak_role(db, user_id=member_id,
                                    speltak_id=speltak.id, role=role)
    return RedirectResponse(f"/groups/{group_slug}/speltakken/{speltak_slug}", status_code=303)

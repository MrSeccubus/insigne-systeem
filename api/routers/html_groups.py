from fastapi import APIRouter, Depends, Form, Query, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, Response
from sqlalchemy.orm import Session

from insigne import email as email_svc
from insigne import groups as groups_svc
from insigne import users as users_svc
from insigne.config import config
from insigne.database import get_db
from insigne.models import GroupMembership, SpeltakMembership
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


# ── Invitation accept / deny ──────────────────────────────────────────────────

@router.post("/invitations/group/{group_id}/accept")
def accept_group_invite(group_id: str, request: Request, db: Session = Depends(get_db)):
    user, redirect = _require_user(request, db)
    if redirect:
        return redirect
    groups_svc.accept_group_invite(db, user_id=user.id, group_id=group_id)
    return RedirectResponse("/", status_code=303)


@router.post("/invitations/group/{group_id}/deny")
def deny_group_invite(group_id: str, request: Request, db: Session = Depends(get_db)):
    user, redirect = _require_user(request, db)
    if redirect:
        return redirect
    groups_svc.deny_group_invite(db, user_id=user.id, group_id=group_id)
    return RedirectResponse("/", status_code=303)


@router.post("/invitations/speltak/{speltak_id}/accept")
def accept_speltak_invite(speltak_id: str, request: Request, db: Session = Depends(get_db)):
    user, redirect = _require_user(request, db)
    if redirect:
        return redirect
    groups_svc.accept_speltak_invite(db, user_id=user.id, speltak_id=speltak_id)
    return RedirectResponse("/", status_code=303)


@router.post("/invitations/speltak/{speltak_id}/deny")
def deny_speltak_invite(speltak_id: str, request: Request, db: Session = Depends(get_db)):
    user, redirect = _require_user(request, db)
    if redirect:
        return redirect
    groups_svc.deny_speltak_invite(db, user_id=user.id, speltak_id=speltak_id)
    return RedirectResponse("/", status_code=303)


@router.post("/invitations/group/{group_id}/dismiss")
def dismiss_group_invite(group_id: str, request: Request, db: Session = Depends(get_db)):
    user, redirect = _require_user(request, db)
    if redirect:
        return redirect
    groups_svc.dismiss_group_invite(db, user_id=user.id, group_id=group_id)
    return RedirectResponse("/", status_code=303)


@router.post("/invitations/speltak/{speltak_id}/dismiss")
def dismiss_speltak_invite(speltak_id: str, request: Request, db: Session = Depends(get_db)):
    user, redirect = _require_user(request, db)
    if redirect:
        return redirect
    groups_svc.dismiss_speltak_invite(db, user_id=user.id, speltak_id=speltak_id)
    return RedirectResponse("/", status_code=303)


# ── Groups list ───────────────────────────────────────────────────────────────

@router.get("/groups", response_class=HTMLResponse)
def groups_list(request: Request, db: Session = Depends(get_db)):
    current_user = _get_current_user(request, db)
    groups = groups_svc.list_groups_for_user(db, current_user) if current_user else []
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
    db: Session = Depends(get_db),
):
    user, redirect = _require_user(request, db)
    if redirect:
        return redirect
    if not user.is_admin and not config.allow_any_user_to_create_groups:
        return RedirectResponse("/groups", status_code=303)
    slug = groups_svc.unique_group_slug(db, groups_svc.name_to_slug(name))
    groups_svc.create_group(db, name=name, slug=slug, created_by_id=user.id)
    return RedirectResponse(f"/groups/{slug}", status_code=303)


# ── Group search (JSON, for datalist) ────────────────────────────────────────

@router.get("/groups/search")
def group_search(q: str = Query(""), db: Session = Depends(get_db)):
    results = groups_svc.search_groups(db, q) if q.strip() else []
    return JSONResponse([{"id": g.id, "name": g.name, "slug": g.slug} for g in results])


# ── Membership request: join ──────────────────────────────────────────────────

@router.get("/groups/join", response_class=HTMLResponse)
def groups_join(request: Request, db: Session = Depends(get_db)):
    user, redirect = _require_user(request, db)
    if redirect:
        return redirect
    return _page(request, "groups_join.html", db)


@router.post("/groups/join", response_class=HTMLResponse)
def groups_join_submit(
    request: Request,
    group_id: str = Form(...),
    speltak_id: str = Form(""),
    db: Session = Depends(get_db),
):
    user, redirect = _require_user(request, db)
    if redirect:
        return redirect

    group = groups_svc.get_group(db, group_id)
    if not group:
        return _page(request, "groups_join.html", db, error="Groep niet gevonden.")

    sid = speltak_id.strip() or None
    speltak = groups_svc.get_speltak(db, sid) if sid else None

    try:
        req = groups_svc.create_membership_request(
            db, user_id=user.id, group_id=group.id, speltak_id=sid
        )
    except ValueError as e:
        msg = {
            "already_member": "Je bent al lid van deze groep/speltak.",
            "request_exists": "Je hebt al een openstaande aanvraag voor deze groep/speltak.",
        }.get(str(e), "Er is iets misgegaan.")
        return _page(request, "groups_join.html", db, error=msg)

    # Notify all groepsleiders
    leaders = [
        m for m in groups_svc.list_group_members(db, group.id)
        if m.role == "groepsleider"
    ]
    for lm in leaders:
        if lm.user and lm.user.email:
            email_svc.send_membership_request_received_email(
                to=lm.user.email,
                naam=lm.user.name or lm.user.email,
                requester_name=user.name or user.email,
                group_name=group.name,
                speltak_name=speltak.name if speltak else None,
                group_slug=group.slug,
            )

    return _page(request, "groups_join.html", db,
                 success=f"Je aanvraag voor {group.name}"
                         f"{f' / {speltak.name}' if speltak else ''} is verstuurd.")


# ── Group detail / edit ───────────────────────────────────────────────────────

@router.get("/groups/{slug}", response_class=HTMLResponse)
def group_detail(slug: str, request: Request, db: Session = Depends(get_db)):
    current_user = _get_current_user(request, db)
    group = groups_svc.get_group_by_slug(db, slug)
    if not group:
        return RedirectResponse("/groups", status_code=303)
    can_manage = bool(current_user and groups_svc.can_manage_group(current_user, db, group.id))
    members = groups_svc.list_group_members(db, group.id)
    pending_members = groups_svc.list_pending_group_members(db, group.id) if can_manage else []
    pending_request_count = groups_svc.count_pending_requests_for_leader(db, current_user.id) if can_manage else 0
    return _page(request, "group_detail.html", db,
                 group=group, can_manage=can_manage, members=members,
                 pending_members=pending_members,
                 pending_request_count=pending_request_count)


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
    db: Session = Depends(get_db),
):
    user, redirect = _require_user(request, db)
    if redirect:
        return redirect
    group = groups_svc.get_group_by_slug(db, slug)
    if not group or not groups_svc.can_manage_group(user, db, group.id):
        return RedirectResponse("/groups", status_code=303)
    groups_svc.update_group(db, group, name=name, slug=group.slug)
    return RedirectResponse(f"/groups/{slug}", status_code=303)


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

@router.get("/groups/{slug}/members/check-email")
def group_check_email(
    slug: str,
    request: Request,
    email: str = Query(...),
    db: Session = Depends(get_db),
):
    user = _get_current_user(request, db)
    if not user:
        return JSONResponse({"error": "unauthorized"}, status_code=401)
    group = groups_svc.get_group_by_slug(db, slug)
    if not group or not groups_svc.can_manage_group(user, db, group.id):
        return JSONResponse({"error": "forbidden"}, status_code=403)
    from insigne.models import User as UserModel
    target = db.query(UserModel).filter_by(email=email.strip().lower()).first()
    return JSONResponse({"exists": target is not None and target.status == "active"})


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
        pending_members = groups_svc.list_pending_group_members(db, group.id)
        return _page(request, "group_detail.html", db,
                     group=group, can_manage=True, members=members,
                     pending_members=pending_members,
                     pending_request_count=groups_svc.count_pending_requests_for_leader(db, user.id),
                     invite_email=email)
    groups_svc.set_group_role(db, user_id=target.id, group_id=group.id, role="groepsleider")
    return RedirectResponse(f"/groups/{slug}", status_code=303)


@router.post("/groups/{slug}/members/invite", response_class=HTMLResponse)
def group_invite_member(
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
    invitee = db.query(UserModel).filter_by(email=email.strip().lower()).first()

    if invitee and invitee.status == "active":
        # Existing active user — create pending membership, send login-to-accept email
        m = db.query(GroupMembership).filter_by(user_id=invitee.id, group_id=group.id).first()
        if m:
            m.role = "groepsleider"
            m.approved = False
            m.withdrawn = False
            m.invited_by_id = user.id
        else:
            db.add(GroupMembership(user_id=invitee.id, group_id=group.id,
                                   role="groepsleider", approved=False, invited_by_id=user.id))
        db.commit()
        email_svc.send_membership_invite_email(
            to=email,
            naam=invitee.name or email.split("@")[0],
            inviter_name=user.name or user.email,
            description=f"groepsleider van groep {group.name}",
        )
    else:
        # New or pending user — registration flow, auto-approved on activation
        code, _token_type, invitee = users_svc.start_registration(db, email)
        m = db.query(GroupMembership).filter_by(user_id=invitee.id, group_id=group.id).first()
        if m:
            m.role = "groepsleider"
            m.approved = False
            m.withdrawn = False
            m.invited_by_id = user.id
        else:
            db.add(GroupMembership(user_id=invitee.id, group_id=group.id,
                                   role="groepsleider", approved=False, invited_by_id=user.id))
        db.commit()
        email_svc.send_groepsleider_invite_email(
            to=email,
            naam=invitee.name or email.split("@")[0],
            code=code,
            inviter_name=user.name or user.email,
            group_name=group.name,
        )
    members = groups_svc.list_group_members(db, group.id)
    pending_members = groups_svc.list_pending_group_members(db, group.id)
    return _page(request, "group_detail.html", db,
                 group=group, can_manage=True, members=members,
                 pending_members=pending_members,
                 pending_request_count=groups_svc.count_pending_requests_for_leader(db, user.id),
                 success=f"Uitnodiging verstuurd naar {email}.")


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


@router.post("/groups/{slug}/members/{member_id}/withdraw")
def group_withdraw_invite(
    slug: str, member_id: str,
    request: Request, db: Session = Depends(get_db),
):
    user, redirect = _require_user(request, db)
    if redirect:
        return redirect
    group = groups_svc.get_group_by_slug(db, slug)
    if group and groups_svc.can_manage_group(user, db, group.id):
        groups_svc.withdraw_group_invite(db, user_id=member_id, group_id=group.id)
    return Response(status_code=204)


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
    peer_signoff: bool = Form(False),
    db: Session = Depends(get_db),
):
    user, redirect = _require_user(request, db)
    if redirect:
        return redirect
    group = groups_svc.get_group_by_slug(db, group_slug)
    if not group or not groups_svc.can_manage_group(user, db, group.id):
        return RedirectResponse(f"/groups/{group_slug}", status_code=303)
    slug = groups_svc.unique_speltak_slug(db, group.id, groups_svc.name_to_slug(name))
    groups_svc.create_speltak(db, group_id=group.id, name=name, slug=slug, peer_signoff=peer_signoff)
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
    pending_members = groups_svc.list_pending_speltak_members(db, speltak.id) if can_manage else []
    other_speltakken = [s for s in group.speltakken if s.id != speltak.id]
    suggested_users = (
        groups_svc.list_group_users_not_in_speltak(db, group.id, speltak.id)
        if can_manage else []
    )
    return _page(request, "speltak_detail.html", db,
                 group=group, speltak=speltak, members=members,
                 pending_members=pending_members,
                 can_manage=can_manage, other_speltakken=other_speltakken,
                 suggested_users=suggested_users)


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
    peer_signoff: bool = Form(False),
    db: Session = Depends(get_db),
):
    user, redirect = _require_user(request, db)
    if redirect:
        return redirect
    group = groups_svc.get_group_by_slug(db, group_slug)
    speltak = group and groups_svc.get_speltak_by_slug(db, group.id, speltak_slug)
    if not speltak or not groups_svc.can_manage_group(user, db, group.id):
        return RedirectResponse(f"/groups/{group_slug}", status_code=303)
    groups_svc.update_speltak(db, speltak, name=name, slug=speltak.slug, peer_signoff=peer_signoff)
    return RedirectResponse(f"/groups/{group_slug}/speltakken/{speltak.slug}", status_code=303)


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

@router.get("/groups/{group_slug}/speltakken/{speltak_slug}/members/check-email")
def speltak_check_email(
    group_slug: str,
    speltak_slug: str,
    request: Request,
    email: str = Query(...),
    db: Session = Depends(get_db),
):
    user = _get_current_user(request, db)
    if not user:
        return JSONResponse({"error": "unauthorized"}, status_code=401)
    group = groups_svc.get_group_by_slug(db, group_slug)
    speltak = group and groups_svc.get_speltak_by_slug(db, group.id, speltak_slug)
    if not speltak or not groups_svc.can_manage_speltak(user, db, speltak.id):
        return JSONResponse({"error": "forbidden"}, status_code=403)
    from insigne.models import User as UserModel
    target = db.query(UserModel).filter_by(email=email.strip().lower()).first()
    exists = target is not None and target.status == "active"
    in_group = exists and groups_svc.is_user_in_group(db, target.id, group.id)
    return JSONResponse({"exists": exists, "in_group": in_group})


@router.post("/groups/{group_slug}/speltakken/{speltak_slug}/members/invite",
             response_class=HTMLResponse)
def speltak_invite_member(
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
    invitee = db.query(UserModel).filter_by(email=email.strip().lower()).first()

    if invitee and invitee.status == "active":
        # Existing active user — create pending membership and send login-to-accept email
        m = db.query(SpeltakMembership).filter_by(user_id=invitee.id, speltak_id=speltak.id).first()
        if m:
            m.role = role
            m.approved = False
            m.withdrawn = False
            m.invited_by_id = user.id
        else:
            db.add(SpeltakMembership(user_id=invitee.id, speltak_id=speltak.id,
                                     role=role, approved=False, invited_by_id=user.id))
        db.commit()
        email_svc.send_membership_invite_email(
            to=email,
            naam=invitee.name or email.split("@")[0],
            inviter_name=user.name or user.email,
            description=f"{role} bij speltak {speltak.name} van groep {group.name}",
        )
    else:
        # New or pending user — registration flow with pending membership
        code, _token_type, invitee = users_svc.start_registration(db, email)
        m = db.query(SpeltakMembership).filter_by(user_id=invitee.id, speltak_id=speltak.id).first()
        if m:
            m.role = role
            m.approved = False
            m.withdrawn = False
            m.invited_by_id = user.id
        else:
            db.add(SpeltakMembership(user_id=invitee.id, speltak_id=speltak.id,
                                     role=role, approved=False, invited_by_id=user.id))
        db.commit()
        email_svc.send_speltak_invite_email(
            to=email,
            naam=invitee.name or email.split("@")[0],
            code=code,
            inviter_name=user.name or user.email,
            group_name=group.name,
            speltak_name=speltak.name,
            role=role,
        )
    members = groups_svc.list_speltak_members(db, speltak.id)
    pending_members = groups_svc.list_pending_speltak_members(db, speltak.id)
    other_speltakken = [s for s in group.speltakken if s.id != speltak.id]
    suggested_users = groups_svc.list_group_users_not_in_speltak(db, group.id, speltak.id)
    return _page(request, "speltak_detail.html", db,
                 group=group, speltak=speltak, members=members,
                 pending_members=pending_members,
                 can_manage=True, other_speltakken=other_speltakken,
                 suggested_users=suggested_users,
                 success=f"Uitnodiging verstuurd naar {email}.")


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


@router.post("/groups/{group_slug}/speltakken/{speltak_slug}/members/{member_id}/set-email",
             response_class=HTMLResponse)
def speltak_set_member_email(
    group_slug: str, speltak_slug: str, member_id: str,
    request: Request,
    email: str = Form(...),
    db: Session = Depends(get_db),
):
    user, redirect = _require_user(request, db)
    if redirect:
        return redirect
    group = groups_svc.get_group_by_slug(db, group_slug)
    speltak = group and groups_svc.get_speltak_by_slug(db, group.id, speltak_slug)
    if not speltak or not groups_svc.can_manage_speltak(user, db, speltak.id):
        return RedirectResponse(f"/groups/{group_slug}", status_code=303)

    members = groups_svc.list_speltak_members(db, speltak.id)
    pending_members = groups_svc.list_pending_speltak_members(db, speltak.id)
    other_speltakken = [s for s in group.speltakken if s.id != speltak.id]
    suggested_users = groups_svc.list_group_users_not_in_speltak(db, group.id, speltak.id)

    try:
        action, target, code = groups_svc.attach_email_to_scout(
            db, scout_user_id=member_id, email=email,
            invited_by_id=user.id, speltak=speltak,
        )
    except ValueError as e:
        return _page(request, "speltak_detail.html", db,
                     group=group, speltak=speltak, members=members,
                     pending_members=pending_members, can_manage=True,
                     other_speltakken=other_speltakken, suggested_users=suggested_users,
                     error=f"Het e-mailadres {email} is al in gebruik door een andere uitgenodigde gebruiker.")

    if action == "new_user":
        email_svc.send_speltak_invite_email(
            to=email,
            naam=target.name or email.split("@")[0],
            code=code,
            inviter_name=user.name or user.email,
            group_name=group.name,
            speltak_name=speltak.name,
            role="scout",
        )
        success = f"Uitnodiging verstuurd naar {email}. De scout kan nu een account aanmaken."
    else:
        email_svc.send_membership_invite_email(
            to=email,
            naam=target.name or email.split("@")[0],
            inviter_name=user.name or user.email,
            description=f"scout bij speltak {speltak.name} van groep {group.name}",
        )
        success = f"Uitnodiging verstuurd naar {email}. Voortgang is samengevoegd."

    members = groups_svc.list_speltak_members(db, speltak.id)
    pending_members = groups_svc.list_pending_speltak_members(db, speltak.id)
    suggested_users = groups_svc.list_group_users_not_in_speltak(db, group.id, speltak.id)
    return _page(request, "speltak_detail.html", db,
                 group=group, speltak=speltak, members=members,
                 pending_members=pending_members, can_manage=True,
                 other_speltakken=other_speltakken, suggested_users=suggested_users,
                 success=success)


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


@router.post("/groups/{group_slug}/speltakken/{speltak_slug}/members/{member_id}/withdraw")
def speltak_withdraw_invite(
    group_slug: str, speltak_slug: str, member_id: str,
    request: Request, db: Session = Depends(get_db),
):
    user, redirect = _require_user(request, db)
    if redirect:
        return redirect
    group = groups_svc.get_group_by_slug(db, group_slug)
    speltak = group and groups_svc.get_speltak_by_slug(db, group.id, speltak_slug)
    reverted = False
    if speltak and groups_svc.can_manage_speltak(user, db, speltak.id):
        reverted = groups_svc.withdraw_speltak_invite(db, user_id=member_id, speltak_id=speltak.id)
    from fastapi.responses import JSONResponse
    return JSONResponse({"reverted": reverted})


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


# ── Membership request: leader review ────────────────────────────────────────

@router.get("/groups/{group_slug}/requests", response_class=HTMLResponse)
def group_requests(group_slug: str, request: Request, db: Session = Depends(get_db)):
    user, redirect = _require_user(request, db)
    if redirect:
        return redirect
    group = groups_svc.get_group_by_slug(db, group_slug)
    if not group or not groups_svc.can_manage_group(user, db, group.id):
        return RedirectResponse("/groups", status_code=303)
    pending = groups_svc.list_pending_requests_for_group(db, group.id)
    return _page(request, "group_requests.html", db, group=group, pending=pending,
                 can_manage=True)


@router.post("/groups/{group_slug}/requests/{req_id}/approve", response_class=HTMLResponse)
def group_request_approve(
    group_slug: str, req_id: str,
    request: Request,
    db: Session = Depends(get_db),
):
    user, redirect = _require_user(request, db)
    if redirect:
        return redirect
    group = groups_svc.get_group_by_slug(db, group_slug)
    if not group or not groups_svc.can_manage_group(user, db, group.id):
        return RedirectResponse("/groups", status_code=303)

    try:
        req = groups_svc.approve_membership_request(db, request_id=req_id,
                                                    reviewed_by_id=user.id)
    except ValueError:
        return RedirectResponse(f"/groups/{group_slug}/requests", status_code=303)

    if req.user and req.user.email:
        speltak_name = req.speltak.name if req.speltak else None
        email_svc.send_membership_request_approved_email(
            to=req.user.email,
            naam=req.user.name or req.user.email,
            group_name=group.name,
            speltak_name=speltak_name,
        )
    return RedirectResponse(f"/groups/{group_slug}/requests", status_code=303)


@router.post("/groups/{group_slug}/requests/{req_id}/reject", response_class=HTMLResponse)
def group_request_reject(
    group_slug: str, req_id: str,
    request: Request,
    db: Session = Depends(get_db),
):
    user, redirect = _require_user(request, db)
    if redirect:
        return redirect
    group = groups_svc.get_group_by_slug(db, group_slug)
    if not group or not groups_svc.can_manage_group(user, db, group.id):
        return RedirectResponse("/groups", status_code=303)

    try:
        req = groups_svc.reject_membership_request(db, request_id=req_id,
                                                   reviewed_by_id=user.id)
    except ValueError:
        return RedirectResponse(f"/groups/{group_slug}/requests", status_code=303)

    if req.user and req.user.email:
        speltak_name = req.speltak.name if req.speltak else None
        email_svc.send_membership_request_rejected_email(
            to=req.user.email,
            naam=req.user.name or req.user.email,
            group_name=group.name,
            speltak_name=speltak_name,
        )
    return RedirectResponse(f"/groups/{group_slug}/requests", status_code=303)

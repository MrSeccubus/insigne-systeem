from pathlib import Path

from fastapi import APIRouter, BackgroundTasks, Depends, Form, Query, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, Response
from sqlalchemy.orm import Session

from insigne import email as email_svc
from insigne import groups as groups_svc
from insigne import progress as progress_svc
from insigne import users as users_svc
from insigne.badges import get_badge, list_badges
from insigne.config import config
from insigne.database import get_db
from insigne.models import GroupMembership, ProgressEntry, Speltak, SpeltakMembership, User as UserModel
from routers.users import _get_current_user
from templates import templates as _TEMPLATES

_DATA_DIR = Path(__file__).parent.parent / "data"

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
    m = db.query(SpeltakMembership).filter_by(
        user_id=user.id, speltak_id=speltak_id, approved=False, withdrawn=False
    ).first()
    if m and m.source_scout_id and groups_svc.has_scout_progress(db, m.source_scout_id):
        speltak = db.get(Speltak, speltak_id)
        _rank = {"in_progress": 0, "work_done": 1, "pending_signoff": 2, "signed_off": 3}
        scout_map = {
            (e.badge_slug, e.level_index, e.step_index): e.status
            for e in db.query(ProgressEntry).filter_by(user_id=m.source_scout_id).all()
        }
        user_map = {
            (e.badge_slug, e.level_index, e.step_index): e.status
            for e in db.query(ProgressEntry).filter_by(user_id=user.id).all()
        }
        badge_rows = []
        for slug in sorted({k[0] for k in scout_map}):
            badge = get_badge(_DATA_DIR, slug)
            if not badge:
                continue
            n_levels = len(badge["levels"])
            n_niveaus = len(badge["levels"][0]["steps"]) if badge["levels"] else 0
            # Pivot: niveaus on horizontal axis, eisen (level_index) as tick boxes
            niveaus = []
            for si in range(n_niveaus):
                eisen = []
                has_changes = False
                for li in range(n_levels):
                    scout_s = scout_map.get((slug, li, si))
                    existing_s = user_map.get((slug, li, si))
                    if scout_s is None:
                        result_s, changed = existing_s, False
                    elif existing_s is None:
                        result_s, changed = scout_s, True
                    elif _rank.get(scout_s, 0) > _rank.get(existing_s, 0):
                        result_s, changed = scout_s, True
                    else:
                        result_s, changed = existing_s, False
                    if changed:
                        has_changes = True
                    eisen.append({"before": existing_s, "after": result_s, "changed": changed})
                niveaus.append({"has_changes": has_changes, "eisen": eisen})
            badge_rows.append({"title": badge["title"], "niveaus": niveaus})
        return _page(request, "merge_scout_progress.html", db,
                     speltak=speltak,
                     group=speltak.group if speltak else None,
                     scout=db.get(UserModel, m.source_scout_id),
                     badge_rows=badge_rows)
    groups_svc.accept_speltak_invite(db, user_id=user.id, speltak_id=speltak_id)
    return RedirectResponse("/", status_code=303)


@router.post("/invitations/speltak/{speltak_id}/accept-with-merge")
def accept_speltak_invite_with_merge(speltak_id: str, request: Request, db: Session = Depends(get_db)):
    user, redirect = _require_user(request, db)
    if redirect:
        return redirect
    groups_svc.accept_speltak_invite_with_merge(db, user_id=user.id, speltak_id=speltak_id)
    return RedirectResponse("/", status_code=303)


@router.post("/invitations/speltak/{speltak_id}/accept-without-merge")
def accept_speltak_invite_without_merge(speltak_id: str, request: Request, db: Session = Depends(get_db)):
    user, redirect = _require_user(request, db)
    if redirect:
        return redirect
    groups_svc.accept_speltak_invite_without_merge(db, user_id=user.id, speltak_id=speltak_id)
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
    pending_flat = groups_svc.list_all_pending_requests_for_leader(db, current_user.id) if current_user else []
    pending = groups_svc.group_pending_requests(pending_flat)
    return _page(request, "groups.html", db,
                 groups=groups, can_create=can_create, pending=pending)


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


# ── All pending requests overview ────────────────────────────────────────────

@router.post("/my-requests/{req_id}/cancel", response_class=HTMLResponse)
def cancel_my_request(req_id: str, request: Request, db: Session = Depends(get_db)):
    user, redirect = _require_user(request, db)
    if redirect:
        return redirect
    groups_svc.cancel_membership_request(db, request_id=req_id, user_id=user.id)
    return RedirectResponse("/", status_code=303)


@router.post("/my-requests/cancel-all", response_class=HTMLResponse)
def cancel_all_my_requests(request: Request, db: Session = Depends(get_db)):
    user, redirect = _require_user(request, db)
    if redirect:
        return redirect
    groups_svc.cancel_all_membership_requests(db, user_id=user.id)
    return RedirectResponse("/", status_code=303)


@router.get("/requests", response_class=HTMLResponse)
def all_requests(request: Request, db: Session = Depends(get_db)):
    user, redirect = _require_user(request, db)
    if redirect:
        return redirect
    pending_flat = groups_svc.list_all_pending_requests_for_leader(db, user.id)
    pending = groups_svc.group_pending_requests(pending_flat)
    return _page(request, "all_requests.html", db, pending=pending, can_manage=True)


def _back_url(request: Request, default: str = "/requests") -> str:
    referer = request.headers.get("referer", "")
    for allowed in ("/requests", "/groups"):
        if referer.endswith(allowed):
            return allowed
    return default


@router.post("/requests/{req_id}/approve", response_class=HTMLResponse)
def all_requests_approve(req_id: str, request: Request, db: Session = Depends(get_db)):
    user, redirect = _require_user(request, db)
    if redirect:
        return redirect
    try:
        req = groups_svc.approve_membership_request(db, request_id=req_id, reviewed_by_id=user.id)
        if req.user and req.user.email:
            email_svc.send_membership_request_approved_email(
                to=req.user.email,
                naam=req.user.name or req.user.email,
                group_name=req.group.name,
                speltak_name=req.speltak.name if req.speltak else None,
            )
    except ValueError:
        pass
    return RedirectResponse(_back_url(request), status_code=303)


@router.post("/requests/{req_id}/reject", response_class=HTMLResponse)
def all_requests_reject(req_id: str, request: Request, db: Session = Depends(get_db)):
    user, redirect = _require_user(request, db)
    if redirect:
        return redirect
    try:
        req = groups_svc.reject_membership_request(db, request_id=req_id, reviewed_by_id=user.id)
        if req.user and req.user.email:
            email_svc.send_membership_request_rejected_email(
                to=req.user.email,
                naam=req.user.name or req.user.email,
                group_name=req.group.name,
                speltak_name=req.speltak.name if req.speltak else None,
            )
    except ValueError:
        pass
    return RedirectResponse(_back_url(request), status_code=303)


# ── Invite group leader ───────────────────────────────────────────────────────

@router.get("/groups/invite-leader", response_class=HTMLResponse)
def invite_leader_form(request: Request, db: Session = Depends(get_db)):
    user, redirect = _require_user(request, db)
    if redirect:
        return redirect
    if not config.allow_any_user_to_create_groups and not user.is_admin:
        return RedirectResponse("/groups/join", status_code=303)
    return _page(request, "invite_group_leader.html", db)


@router.post("/groups/invite-leader", response_class=HTMLResponse)
def invite_leader_submit(
    request: Request,
    email: str = Form(...),
    db: Session = Depends(get_db),
):
    user, redirect = _require_user(request, db)
    if redirect:
        return redirect
    if not config.allow_any_user_to_create_groups and not user.is_admin:
        return RedirectResponse("/groups/join", status_code=303)
    email_svc.send_invite_group_leader_email(
        to=email,
        invited_by_name=user.name or user.email,
    )
    return _page(request, "invite_group_leader.html", db,
                 success=f"Uitnodiging verstuurd naar {email}.")


# ── Membership request: join ──────────────────────────────────────────────────

@router.get("/groups/join", response_class=HTMLResponse)
def groups_join(request: Request, db: Session = Depends(get_db)):
    user, redirect = _require_user(request, db)
    if redirect:
        return redirect
    all_groups = [
        {"id": g.id, "name": g.name, "slug": g.slug,
         "speltakken": [{"id": s.id, "name": s.name} for s in g.speltakken]}
        for g in groups_svc.list_groups(db)
    ]
    my_group_memberships, my_speltak_memberships = groups_svc.list_active_memberships_for_user(db, user.id)
    my_requests = groups_svc.list_my_membership_requests(db, user.id)
    my_group_roles = {m.group_id: m.role for m in my_group_memberships}
    my_speltak_roles = {m.speltak_id: m.role for m in my_speltak_memberships}
    pending_group_ids = {r.group_id for r in my_requests if r.status == "pending" and r.speltak_id is None}
    pending_speltak_ids = {r.speltak_id for r in my_requests if r.status == "pending" and r.speltak_id is not None}
    return _page(request, "groups_join.html", db,
                 all_groups=all_groups,
                 my_group_roles=my_group_roles,
                 my_speltak_roles=my_speltak_roles,
                 pending_group_ids=list(pending_group_ids),
                 pending_speltak_ids=list(pending_speltak_ids),
                 allow_invite_leader=config.allow_any_user_to_create_groups or user.is_admin)


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

    def _join_ctx():
        all_groups = [
            {"id": g.id, "name": g.name, "slug": g.slug,
             "speltakken": [{"id": s.id, "name": s.name} for s in g.speltakken]}
            for g in groups_svc.list_groups(db)
        ]
        gm, sm = groups_svc.list_active_memberships_for_user(db, user.id)
        reqs = groups_svc.list_my_membership_requests(db, user.id)
        return dict(
            all_groups=all_groups,
            my_group_roles={m.group_id: m.role for m in gm},
            my_speltak_roles={m.speltak_id: m.role for m in sm},
            pending_group_ids=list({r.group_id for r in reqs if r.status == "pending" and r.speltak_id is None}),
            pending_speltak_ids=list({r.speltak_id for r in reqs if r.status == "pending" and r.speltak_id is not None}),
            allow_invite_leader=config.allow_any_user_to_create_groups or user.is_admin,
        )

    wants_json = "application/json" in request.headers.get("accept", "")

    group = groups_svc.get_group(db, group_id)
    if not group:
        if wants_json:
            return JSONResponse({"error": "Groep niet gevonden."}, status_code=404)
        return _page(request, "groups_join.html", db, **_join_ctx(), error="Groep niet gevonden.")

    sid = speltak_id.strip() or None
    speltak = groups_svc.get_speltak(db, sid) if sid else None

    try:
        groups_svc.create_membership_request(
            db, user_id=user.id, group_id=group.id, speltak_id=sid
        )
    except ValueError as e:
        msg = {
            "already_member": "Je bent al lid van deze groep/speltak.",
            "request_exists": "Je hebt al een openstaande aanvraag voor deze groep/speltak.",
        }.get(str(e), "Er is iets misgegaan.")
        if wants_json:
            return JSONResponse({"error": msg}, status_code=409)
        return _page(request, "groups_join.html", db, **_join_ctx(), error=msg)

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

    if wants_json:
        return JSONResponse({"ok": True})
    return _page(request, "groups_join.html", db,
                 **_join_ctx(),
                 success=f"Je aanvraag voor {group.name}"
                         f"{f' / {speltak.name}' if speltak else ''} is verstuurd.")


# ── Group detail / edit ───────────────────────────────────────────────────────

def _group_detail_ctx(db: Session, group, user):
    members = groups_svc.list_group_members(db, group.id)
    can_manage = bool(user and groups_svc.can_manage_group(user, db, group.id))
    pending_members = groups_svc.list_pending_group_members(db, group.id) if can_manage else []
    speltak_member_counts = {
        s.id: len(groups_svc.list_speltak_members(db, s.id))
        for s in group.speltakken
    }
    members_without_speltak = groups_svc.list_members_without_speltak(db, group.id) if can_manage else []
    pending_request_count = groups_svc.count_pending_requests_for_leader(db, user.id) if can_manage else 0
    current_leader_ids = {m.user_id for m in members if m.role == "groepsleider"}
    seen_ids: set[str] = set()
    suggestion_users = []
    for u in (
        [m.user for m in members if m.role != "groepsleider" and m.user and m.user.email]
        + [sm.user for s in group.speltakken
           for sm in groups_svc.list_speltak_members(db, s.id)
           if sm.user and sm.user.email and sm.user_id not in current_leader_ids]
    ):
        if u.id not in seen_ids:
            seen_ids.add(u.id)
            suggestion_users.append(u)
    suggestion_users.sort(key=lambda u: (u.name or u.email).lower())
    member_email_suggestions = suggestion_users
    return dict(
        group=group, can_manage=can_manage, members=members,
        pending_members=pending_members,
        pending_request_count=pending_request_count,
        speltak_member_counts=speltak_member_counts,
        members_without_speltak=members_without_speltak,
        member_email_suggestions=member_email_suggestions,
    )


@router.get("/groups/{slug}", response_class=HTMLResponse)
def group_detail(slug: str, request: Request, db: Session = Depends(get_db)):
    current_user = _get_current_user(request, db)
    group = groups_svc.get_group_by_slug(db, slug)
    if not group:
        return RedirectResponse("/groups", status_code=303)
    return _page(request, "group_detail.html", db,
                 **_group_detail_ctx(db, group, current_user))


@router.post("/groups/{slug}/members/{member_id}/assign-speltak", response_class=HTMLResponse)
def group_assign_speltak(
    slug: str, member_id: str,
    to_speltak_id: str = Form(...),
    request: Request = None,
    db: Session = Depends(get_db),
):
    user, redirect = _require_user(request, db)
    if redirect:
        return redirect
    group = groups_svc.get_group_by_slug(db, slug)
    if not group or not groups_svc.can_manage_group(user, db, group.id):
        return RedirectResponse("/groups", status_code=303)
    groups_svc.set_speltak_role(db, user_id=member_id, speltak_id=to_speltak_id, role="scout")
    return RedirectResponse(f"/groups/{slug}", status_code=303)


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
        return _page(request, "group_detail.html", db,
                     **_group_detail_ctx(db, group, user),
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
    return _page(request, "group_detail.html", db,
                 **_group_detail_ctx(db, group, user),
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
        success = f"Uitnodiging verstuurd naar {email}. De gebruiker kan bij het accepteren kiezen of de voortgang wordt overgenomen."

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




# ── Leider progress management ────────────────────────────────────────────────

_NEXT_STATUS = {
    "none": "in_progress",
    "in_progress": "work_done",
    "work_done": "none",
    "pending_signoff": "pending_signoff",
    "signed_off": "work_done",
}


@router.get("/my-speltakken", response_class=HTMLResponse)
def my_speltakken(request: Request, db: Session = Depends(get_db)):
    user, redirect = _require_user(request, db)
    if redirect:
        return redirect
    pairs = groups_svc.list_my_speltakken(db, user.id)
    if len(pairs) == 1:
        group, speltak = pairs[0]
        return RedirectResponse(
            f"/groups/{group.slug}/speltakken/{speltak.slug}/progress",
            status_code=303,
        )
    nav_entries = {}
    for group, speltak in pairs:
        nav_entries.setdefault(group.id, {"group": group, "speltakken": []})
        nav_entries[group.id]["speltakken"].append(speltak)
    return _page(request, "my_speltakken.html", db,
                 nav_entries=list(nav_entries.values()))


@router.get("/groups/{group_slug}/progress", response_class=HTMLResponse)
def group_progress(group_slug: str, request: Request, db: Session = Depends(get_db)):
    user, redirect = _require_user(request, db)
    if redirect:
        return redirect
    group = groups_svc.get_group_by_slug(db, group_slug)
    if not group:
        return RedirectResponse("/groups", status_code=303)
    if not groups_svc.can_manage_group(user, db, group.id):
        return RedirectResponse(f"/groups/{group_slug}", status_code=303)
    speltakken_data = [
        {
            "speltak": s,
            "member_count": len(groups_svc.list_speltak_members(db, s.id)),
            "progress_url": f"/groups/{group_slug}/speltakken/{s.slug}/progress",
        }
        for s in group.speltakken
    ]
    members_without_speltak = groups_svc.list_members_without_speltak(db, group.id)
    return _page(request, "group_progress.html", db,
                 group=group,
                 speltakken_data=speltakken_data,
                 members_without_speltak=members_without_speltak)


@router.get("/groups/{group_slug}/speltakken/{speltak_slug}/progress",
            response_class=HTMLResponse)
def speltak_progress(
    group_slug: str, speltak_slug: str,
    request: Request,
    only_favorites: bool = Query(False),
    db: Session = Depends(get_db),
):
    user, redirect = _require_user(request, db)
    if redirect:
        return redirect
    group = groups_svc.get_group_by_slug(db, group_slug)
    if not group:
        return RedirectResponse("/groups", status_code=303)
    speltak = groups_svc.get_speltak_by_slug(db, group.id, speltak_slug)
    if not speltak:
        return RedirectResponse(f"/groups/{group_slug}", status_code=303)
    if not groups_svc.can_manage_speltak(user, db, speltak.id):
        return RedirectResponse(f"/groups/{group_slug}", status_code=303)

    memberships = groups_svc.list_speltak_members(db, speltak.id)
    if not speltak.peer_signoff:
        memberships = [m for m in memberships if m.role != "speltakleider"]
    scout_ids = [m.user_id for m in memberships]
    progress_by_scout = progress_svc.list_progress_for_scouts(db, scout_ids)
    favorite_slugs = groups_svc.get_speltak_favorite_slugs(db, speltak.id)
    can_edit = not speltak.peer_signoff

    all_badges_raw = list_badges(_DATA_DIR)
    all_badges = {}
    for category, summaries in all_badges_raw.items():
        badge_list = []
        for summary in summaries:
            badge = get_badge(_DATA_DIR, summary["slug"])
            if badge:
                badge["n_levels"] = len(badge["levels"])
                badge_list.append(badge)
        all_badges[category] = badge_list

    return _page(request, "speltak_progress.html", db,
                 group=group, speltak=speltak,
                 members=memberships,
                 progress_by_scout=progress_by_scout,
                 favorite_slugs=favorite_slugs,
                 all_badges=all_badges,
                 can_edit=can_edit,
                 only_favorites=only_favorites,
                 leider_id=user.id)


@router.post("/groups/{group_slug}/speltakken/{speltak_slug}/scouts/{scout_id}/progress/set",
             response_class=HTMLResponse)
def speltak_set_scout_progress(
    group_slug: str, speltak_slug: str, scout_id: str,
    request: Request,
    background_tasks: BackgroundTasks,
    badge_slug: str = Form(...),
    level_index: int = Form(...),
    step_index: int = Form(...),
    status: str = Form(...),
    db: Session = Depends(get_db),
):
    user, redirect = _require_user(request, db)
    if redirect:
        return redirect
    group = groups_svc.get_group_by_slug(db, group_slug)
    speltak = group and groups_svc.get_speltak_by_slug(db, group.id, speltak_slug)
    if not speltak:
        return HTMLResponse("", status_code=404)

    try:
        entry = progress_svc.set_scout_progress(
            db, leider_id=user.id, scout_id=scout_id,
            speltak_id=speltak.id, badge_slug=badge_slug,
            level_index=level_index, step_index=step_index, status=status,
        )
        if entry and status == "signed_off":
            scout = entry.user
            if scout.email:
                badge = get_badge(_DATA_DIR, badge_slug)
                level = badge["levels"][level_index]
                step_text = level["steps"][step_index]["text"]
                mentor_name = user.name or user.email
                background_tasks.add_task(
                    email_svc.send_scout_signed_off_email,
                    scout.email,
                    scout.name or scout.email,
                    badge_slug,
                    badge["title"],
                    step_index + 1,
                    level["name"],
                    step_text,
                    mentor_name,
                )
                n_eisen = len(badge["levels"])
                signed_count = db.query(ProgressEntry).filter(
                    ProgressEntry.user_id == scout_id,
                    ProgressEntry.badge_slug == badge_slug,
                    ProgressEntry.step_index == step_index,
                    ProgressEntry.status == "signed_off",
                ).count()
                if signed_count == n_eisen:
                    background_tasks.add_task(
                        email_svc.send_scout_niveau_completed_email,
                        scout.email,
                        scout.name or scout.email,
                        badge["title"],
                        step_index + 1,
                        badge_slug,
                    )
    except (progress_svc.Forbidden, progress_svc.Conflict, ValueError):
        from insigne.models import ProgressEntry as PE
        entry = db.query(PE).filter_by(
            user_id=scout_id, badge_slug=badge_slug,
            level_index=level_index, step_index=step_index,
        ).first()

    entry_status = entry.status if entry else "none"
    can_edit = not speltak.peer_signoff
    can_edit_cell = can_edit and scout_id != user.id and entry_status != "pending_signoff"
    return _TEMPLATES.TemplateResponse(
        request=request,
        name="partials/leider_step_check.html",
        context={
            "scout_id": scout_id,
            "badge_slug": badge_slug,
            "level_index": level_index,
            "step_index": step_index,
            "entry_status": entry_status,
            "group_slug": group_slug,
            "speltak_slug": speltak_slug,
            "can_edit_cell": can_edit_cell,
            "next_status": _NEXT_STATUS.get(entry_status, "in_progress"),
        },
    )


@router.post("/groups/{group_slug}/speltakken/{speltak_slug}/favorite-badge",
             response_class=HTMLResponse)
def speltak_toggle_favorite_badge(
    group_slug: str, speltak_slug: str,
    request: Request,
    badge_slug: str = Form(...),
    db: Session = Depends(get_db),
):
    user, redirect = _require_user(request, db)
    if redirect:
        return HTMLResponse("", status_code=401)
    group = groups_svc.get_group_by_slug(db, group_slug)
    speltak = group and groups_svc.get_speltak_by_slug(db, group.id, speltak_slug)
    if not speltak or not groups_svc.can_manage_speltak(user, db, speltak.id):
        return HTMLResponse("", status_code=403)
    is_fav = groups_svc.toggle_speltak_favorite_badge(db, speltak.id, badge_slug)
    label = "Verwijder uit favorieten" if is_fav else "Voeg toe aan favorieten"
    star = "★" if is_fav else "☆"
    return HTMLResponse(
        f'<button hx-post="/groups/{group_slug}/speltakken/{speltak_slug}/favorite-badge" '
        f'hx-vals=\'{{"badge_slug":"{badge_slug}"}}\' hx-target="this" hx-swap="outerHTML" '
        f'class="btn-sm btn-neutral" style="font-size:1rem;padding:0 0.4rem;line-height:1.6;" '
        f'title="{label}">{star}</button>'
    )

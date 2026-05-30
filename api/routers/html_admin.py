from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.orm import Session

from insigne import admin as admin_svc
from insigne.database import get_db
from insigne.email import send_account_deleted_email
from insigne.models import User as UserModel
from routers.users import _get_current_user
from templates import templates as _TEMPLATES

router = APIRouter()


def _require_admin(request: Request, db: Session):
    """Return ``(current_user, admin)``:

    - ``(User, User)`` — caller may proceed (admin is the same user).
    - ``(None, None)`` — unauthenticated; caller redirects to ``/login``.
    - ``(User, None)`` — authenticated but not an admin; caller redirects to ``/``.

    Returns data only (no ``RedirectResponse``) so that taint cannot flow
    from request parameters into the response object via the helper. Same
    shape as ``_require_scout_access`` after PR #116 (closes #100 noise
    from ``return redirect`` flagged by CodeQL ``py/reflective-xss``).
    """
    user = _get_current_user(request, db)
    if user is None:
        return None, None
    if not user.is_admin:
        return user, None
    return user, user


@router.get("/admin", response_class=HTMLResponse)
def admin_dashboard(request: Request, db: Session = Depends(get_db)):
    current_user, admin = _require_admin(request, db)
    if admin is None:
        return RedirectResponse("/login" if current_user is None else "/", status_code=303)
    stats = admin_svc.get_dashboard_stats(db)
    return _TEMPLATES.TemplateResponse(
        request=request,
        name="admin_dashboard.html",
        context={"current_user": user, "stats": stats},
    )


@router.post("/admin/find-user", response_class=HTMLResponse)
def admin_find_user(
    request: Request,
    email: str = Form(""),
    db: Session = Depends(get_db),
):
    current_user, admin = _require_admin(request, db)
    if admin is None:
        return RedirectResponse("/login" if current_user is None else "/", status_code=303)
    found = admin_svc.find_user_by_email(db, email) if email.strip() else None
    return _TEMPLATES.TemplateResponse(
        request=request,
        name="partials/admin_user_result.html",
        context={
            "current_user": user,
            "found_user": found,
            "searched_email": email.strip(),
            "deleted_email": None,
        },
    )


@router.post("/admin/delete-user/{user_id}", response_class=HTMLResponse)
def admin_delete_user(
    user_id: str,
    request: Request,
    db: Session = Depends(get_db),
):
    current_user, admin = _require_admin(request, db)
    if admin is None:
        return RedirectResponse("/login" if current_user is None else "/", status_code=303)
    target = db.get(UserModel, user_id)
    if target and target.is_admin:
        return _TEMPLATES.TemplateResponse(
            request=request,
            name="partials/admin_user_result.html",
            context={
                "current_user": user,
                "found_user": target,
                "searched_email": target.email or "",
                "deleted_email": None,
                "error_message": "Dit account heeft beheerdersrechten. Verwijder eerst de beheerdersrechten uit de configuratie voordat u het account verwijdert.",
            },
        )
    deleted_email = target.email if target else ""
    deleted_name = target.name or deleted_email if target else ""
    if target and target.email:
        send_account_deleted_email(target.email, deleted_name)
    admin_svc.delete_user(db, user_id)
    return _TEMPLATES.TemplateResponse(
        request=request,
        name="partials/admin_user_result.html",
        context={
            "current_user": user,
            "found_user": None,
            "searched_email": "",
            "deleted_email": deleted_email,
            "error_message": None,
        },
    )

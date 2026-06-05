"""Happy-path smoke test for every template-rendering HTML GET route.

#142: issue #139 (an admin-dashboard 500 caused by a stale ``user`` reference
in the route handler's template context after the ``_require_admin`` refactor)
shipped **silently** — no test ever rendered ``/admin`` as a logged-in admin,
so the ``NameError`` on the happy path went unnoticed until production.

The whole class of bug is "an authorized GET that builds a template context
but has no test that actually renders it." This test closes that gap once and
for all: it logs in a user who is admin + groepsleider + speltakleider, seeds a
scout with progress (so path-parameter routes resolve to real data), then GETs
every HTML page route and asserts the response is **not a 5xx**.

Because the TestClient runs with ``raise_server_exceptions=True`` (see
conftest), a handler-level ``NameError`` / ``KeyError`` doesn't even reach the
assertion — it raises straight out of ``client.get`` with a clear traceback.
Either way, a regression of the #139 shape fails here.

New page routes are covered automatically once added to ``PAGE_ROUTES`` below;
the ``test_all_page_routes_are_listed`` guard fails if a template-rendering GET
route is added to the app without being listed here, so the smoke set can't
silently fall behind.
"""
import pytest

from insigne.auth import create_access_token
from insigne.config import config
from insigne.models import (
    GroupMembership,
    ProgressEntry,
    SpeltakMembership,
    User,
)

_REGULAR_BADGE = "vredeslicht"
_JAAR_BADGE = "jaarinsigne_2026"


@pytest.fixture
def world(client, db):
    """An admin who is also groepsleider of group ``g`` and speltakleider of
    speltak ``s``, plus a scout in that speltak with some recorded progress.

    Returns the dict of substitution values used to build concrete URLs.
    """
    from insigne import groups as groups_svc

    admin_email = "admin@example.com"
    config.admins = [admin_email]
    admin = User(email=admin_email, name="Admin", status="active", password_hash="x")
    db.add(admin)
    db.flush()

    g = groups_svc.create_group(db, name="Groep", slug="g", created_by_id=admin.id)
    s = groups_svc.create_speltak(db, group_id=g.id, name="Speltak", slug="s")
    db.add(SpeltakMembership(user_id=admin.id, speltak_id=s.id,
                             role="speltakleider", approved=True))

    scout = User(name="Scout", status="active")
    db.add(scout)
    db.flush()
    db.add(GroupMembership(user_id=scout.id, group_id=g.id, role="member", approved=True))
    db.add(SpeltakMembership(user_id=scout.id, speltak_id=s.id, role="scout", approved=True))

    # Progress for both a regular badge and the jaarinsigne, so the scout /
    # speltak progress pages render with real rows rather than empty states.
    for slug in (_REGULAR_BADGE, _JAAR_BADGE):
        db.add(ProgressEntry(user_id=scout.id, badge_slug=slug,
                             level_index=0, step_index=0, status="work_done"))
    db.commit()

    token, _ = create_access_token(admin.id)
    client.cookies.set("access_token", token)
    return {"scout_id": scout.id, "group_slug": "g", "speltak_slug": "s",
            "badge": _REGULAR_BADGE, "jaar": _JAAR_BADGE}


# Every template-/JSON-rendering GET route, as a path template keyed on the
# ``world`` substitution values. Pure-asset / probe routes (/ping, /sw.js,
# /static, /images) and query-only endpoints (/groups/search, check-email) are
# intentionally excluded — they don't build a user-dependent render context.
PAGE_ROUTES = [
    "/",
    "/install",
    "/offline",
    "/offline/disabled",
    "/offline/manifest.json",
    "/sync",
    "/admin",                                            # ← the #139 route
    "/contact",
    "/privacy",
    "/badges/{badge}",
    "/badges/{badge}/niveau-checks/0",
    "/scouts/{scout_id}",
    "/scouts/{scout_id}/badges/{badge}",
    "/scouts/{scout_id}/badges/{badge}/niveau-checks/0",
    "/scouts/{scout_id}/badges/{jaar}",
    "/signoff-requests",
    "/signoff-requests/count",
    "/groups",
    "/groups/new",
    "/groups/invite-leader",
    "/groups/join",
    "/my-speltakken",
    "/requests",
    "/groups/{group_slug}",
    "/groups/{group_slug}/edit",
    "/groups/{group_slug}/progress",
    "/groups/{group_slug}/speltakken/new",
    "/groups/{group_slug}/speltakken/{speltak_slug}",
    "/groups/{group_slug}/speltakken/{speltak_slug}/edit",
    "/groups/{group_slug}/speltakken/{speltak_slug}/progress",
]


@pytest.mark.parametrize("route", PAGE_ROUTES)
def test_page_route_renders_without_server_error(client, db, world, route):
    """A regression of the #139 shape (handler crash on the happy path) makes
    this fail — either by raising out of ``client.get`` or via the 5xx assert."""
    url = route.format(**world)
    r = client.get(url, follow_redirects=False)
    assert r.status_code < 500, f"{url} returned {r.status_code}:\n{r.text[:500]}"


def test_all_page_routes_are_listed():
    """Guard: every template-rendering HTML GET route in the app must appear in
    PAGE_ROUTES, so the smoke set can't silently fall behind a new page (which
    is exactly how #139 slipped through). Asset/probe and query-only endpoints
    are allow-listed exceptions."""
    from starlette.routing import Route
    from main import app

    excluded = {
        "/ping", "/sw.js",                       # probe / worker
        "/groups/search",                        # needs ?q=
        "/groups/{group_slug}/speltakken/{speltak_slug}/members/check-email",
        "/groups/{slug}/members/check-email",    # JSON, needs ?email=
    }
    # PAGE_ROUTES use literal "0" for niveau index and resolve {slug} via the
    # group/speltak/badge keys; normalise both sides to FastAPI's path templates.
    def normalise(p):
        return (p.replace("/0", "/{niveau_index}")
                 .replace("{badge}", "{slug}").replace("{jaar}", "{slug}")
                 .replace("{group_slug}", "{slug}").replace("{speltak_slug}", "{slug}")
                 .replace("{scout_id}", "{scout_id}"))

    listed = {normalise(p) for p in PAGE_ROUTES}

    missing = []
    for r in app.router.routes:
        if not isinstance(r, Route) or not r.methods or "GET" not in r.methods:
            continue
        mod = getattr(r.endpoint, "__module__", "")
        if "html_" not in mod and mod != "main":
            continue
        path = r.path
        if path in excluded or path.startswith("/static") or path.startswith("/images"):
            continue
        if normalise(path) not in listed:
            missing.append(path)

    assert not missing, (
        "These template-rendering GET routes are not covered by PAGE_ROUTES "
        f"(add them, or allow-list them): {sorted(set(missing))}"
    )

"""Behavioural tests for the HTML group routes (routers/html_groups.py)."""
from insigne import groups as svc
from insigne.auth import create_access_token
from insigne.models import User


def _user(db, email="user@example.com", name="User"):
    u = User(email=email, name=name, status="active", password_hash="x")
    db.add(u)
    db.commit()
    return u


def _cookie(user) -> dict:
    token, _ = create_access_token(user.id)
    return {"access_token": token}


# ── GET /groups ───────────────────────────────────────────────────────────────

class TestGroupsList:
    def test_returns_200(self, client, db):
        r = client.get("/groups")
        assert r.status_code == 200

    def test_shows_groups(self, client, db):
        svc.create_group(db, name="Welpen", slug="welpen")
        r = client.get("/groups")
        assert "Welpen" in r.text


# ── GET /groups/new ───────────────────────────────────────────────────────────

class TestGroupNew:
    def test_unauthenticated_redirects_to_login(self, client, db):
        r = client.get("/groups/new", follow_redirects=False)
        assert r.status_code == 303
        assert r.headers["location"] == "/login"

    def test_authenticated_returns_200(self, client, db):
        user = _user(db)
        r = client.get("/groups/new", cookies=_cookie(user))
        assert r.status_code == 200


# ── POST /groups/new ──────────────────────────────────────────────────────────

class TestGroupCreate:
    def test_creates_group_and_redirects(self, client, db):
        user = _user(db)
        r = client.post("/groups/new", data={"name": "Groep A", "slug": "groep-a"},
                        cookies=_cookie(user), follow_redirects=False)
        assert r.status_code == 303
        assert svc.get_group_by_slug(db, "groep-a") is not None

    def test_duplicate_slug_shows_error(self, client, db):
        user = _user(db)
        svc.create_group(db, name="Oud", slug="groep-a")
        r = client.post("/groups/new", data={"name": "Nieuw", "slug": "groep-a"},
                        cookies=_cookie(user), follow_redirects=False)
        assert r.status_code == 200
        assert "al in gebruik" in r.text


# ── GET /groups/{slug} ────────────────────────────────────────────────────────

class TestGroupDetail:
    def test_returns_200(self, client, db):
        svc.create_group(db, name="G", slug="g")
        r = client.get("/groups/g")
        assert r.status_code == 200

    def test_unknown_slug_redirects(self, client, db):
        r = client.get("/groups/nonexistent", follow_redirects=False)
        assert r.status_code == 303

    def test_shows_groepsleiders(self, client, db):
        user = _user(db)
        svc.create_group(db, name="G", slug="g", created_by_id=user.id)
        r = client.get("/groups/g")
        assert "User" in r.text


# ── POST /groups/{slug}/members/add ──────────────────────────────────────────

class TestGroupAddMember:
    def test_adds_groepsleider(self, client, db):
        leider = _user(db)
        new_leider = _user(db, email="new@example.com", name="New")
        g = svc.create_group(db, name="G", slug="g", created_by_id=leider.id)
        r = client.post(f"/groups/g/members/add", data={"email": "new@example.com"},
                        cookies=_cookie(leider), follow_redirects=False)
        assert r.status_code == 303
        members = svc.list_group_members(db, g.id)
        assert any(m.user_id == new_leider.id for m in members)

    def test_unknown_email_shows_error(self, client, db):
        leider = _user(db)
        svc.create_group(db, name="G", slug="g", created_by_id=leider.id)
        r = client.post("/groups/g/members/add", data={"email": "nobody@example.com"},
                        cookies=_cookie(leider))
        assert r.status_code == 200
        assert "Geen gebruiker" in r.text

    def test_non_manager_cannot_add(self, client, db):
        other = _user(db)
        svc.create_group(db, name="G", slug="g")
        r = client.post("/groups/g/members/add", data={"email": "x@example.com"},
                        cookies=_cookie(other), follow_redirects=False)
        assert r.status_code == 303
        assert r.headers["location"] == "/groups"


# ── POST /groups/{slug}/members/{id}/remove ───────────────────────────────────

class TestGroupRemoveMember:
    def test_removes_groepsleider(self, client, db):
        leider = _user(db)
        other = _user(db, email="other@example.com")
        g = svc.create_group(db, name="G", slug="g", created_by_id=leider.id)
        svc.set_group_role(db, user_id=other.id, group_id=g.id, role="groepsleider")
        r = client.post(f"/groups/g/members/{other.id}/remove",
                        cookies=_cookie(leider), follow_redirects=False)
        assert r.status_code == 303
        members = svc.list_group_members(db, g.id)
        assert not any(m.user_id == other.id for m in members)

    def test_non_manager_cannot_remove(self, client, db):
        leider = _user(db)
        outsider = _user(db, email="outsider@example.com")
        target = _user(db, email="target@example.com")
        g = svc.create_group(db, name="G", slug="g", created_by_id=leider.id)
        svc.set_group_role(db, user_id=target.id, group_id=g.id, role="groepsleider")
        r = client.post(f"/groups/g/members/{target.id}/remove",
                        cookies=_cookie(outsider), follow_redirects=False)
        assert r.status_code == 303
        members = svc.list_group_members(db, g.id)
        assert any(m.user_id == target.id for m in members)

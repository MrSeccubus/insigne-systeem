"""API tests for /api/groups."""
from insigne import groups as svc
from insigne.config import config
from insigne.models import ConfirmationToken, User


def _full_register(client, db, email="user@example.com", password="validpass1", name="User"):
    client.post("/api/users", json={"email": email})
    user = db.query(User).filter_by(email=email).first()
    ct = db.query(ConfirmationToken).filter_by(user_id=user.id, type="email_confirmation").first()
    r = client.post("/api/users/confirm", json={"code": ct.token})
    setup = r.json()["setup_token"]
    r = client.post("/api/users/activate", json={"setup_token": setup, "password": password, "name": name})
    return r.json()["access_token"]


def _auth(token):
    return {"Authorization": f"Bearer {token}"}


def _make_admin(email):
    if email not in config.admins:
        config.admins.append(email)


def _remove_admin(email):
    if email in config.admins:
        config.admins.remove(email)


# ── GET /api/groups ───────────────────────────────────────────────────────────

class TestListGroups:
    def test_returns_empty_list(self, client, db):
        r = client.get("/api/groups")
        assert r.status_code == 200
        assert r.json() == []

    def test_returns_created_groups(self, client, db):
        svc.create_group(db, name="Groep A", slug="groep-a")
        r = client.get("/api/groups")
        assert len(r.json()) == 1
        assert r.json()[0]["slug"] == "groep-a"


# ── POST /api/groups ──────────────────────────────────────────────────────────

class TestCreateGroup:
    def test_any_user_can_create_when_allowed(self, client, db):
        config.allow_any_user_to_create_groups = True
        token = _full_register(client, db)
        r = client.post("/api/groups", json={"name": "G", "slug": "g"}, headers=_auth(token))
        assert r.status_code == 201
        assert r.json()["slug"] == "g"

    def test_unauthenticated_returns_401(self, client, db):
        r = client.post("/api/groups", json={"name": "G", "slug": "g"})
        assert r.status_code == 401

    def test_duplicate_slug_returns_409(self, client, db):
        config.allow_any_user_to_create_groups = True
        token = _full_register(client, db)
        client.post("/api/groups", json={"name": "G", "slug": "g"}, headers=_auth(token))
        r = client.post("/api/groups", json={"name": "G2", "slug": "g"}, headers=_auth(token))
        assert r.status_code == 409

    def test_non_admin_blocked_when_restricted(self, client, db):
        config.allow_any_user_to_create_groups = False
        token = _full_register(client, db)
        r = client.post("/api/groups", json={"name": "G", "slug": "g"}, headers=_auth(token))
        assert r.status_code == 403
        config.allow_any_user_to_create_groups = True

    def test_admin_can_create_when_restricted(self, client, db):
        config.allow_any_user_to_create_groups = False
        email = "admin2@example.com"
        _make_admin(email)
        token = _full_register(client, db, email=email, name="Admin")
        r = client.post("/api/groups", json={"name": "G", "slug": "g-adm"}, headers=_auth(token))
        assert r.status_code == 201
        config.allow_any_user_to_create_groups = True
        _remove_admin(email)


# ── PUT /api/groups/{id} ──────────────────────────────────────────────────────

class TestUpdateGroup:
    def test_groepsleider_can_update(self, client, db):
        token = _full_register(client, db)
        user = db.query(User).filter_by(email="user@example.com").first()
        g = svc.create_group(db, name="Oud", slug="oud", created_by_id=user.id)
        r = client.put(f"/api/groups/{g.id}", json={"name": "Nieuw", "slug": "nieuw"}, headers=_auth(token))
        assert r.status_code == 200
        assert r.json()["slug"] == "nieuw"

    def test_non_member_cannot_update(self, client, db):
        token = _full_register(client, db)
        g = svc.create_group(db, name="G", slug="g")
        r = client.put(f"/api/groups/{g.id}", json={"name": "X", "slug": "x"}, headers=_auth(token))
        assert r.status_code == 403

    def test_unknown_group_returns_404(self, client, db):
        token = _full_register(client, db)
        r = client.put("/api/groups/nonexistent", json={"name": "X", "slug": "x"}, headers=_auth(token))
        assert r.status_code == 404


# ── DELETE /api/groups/{id} ───────────────────────────────────────────────────

class TestDeleteGroup:
    def test_groepsleider_can_delete(self, client, db):
        token = _full_register(client, db)
        user = db.query(User).filter_by(email="user@example.com").first()
        g = svc.create_group(db, name="G", slug="g", created_by_id=user.id)
        r = client.delete(f"/api/groups/{g.id}", headers=_auth(token))
        assert r.status_code == 204

    def test_non_member_cannot_delete(self, client, db):
        token = _full_register(client, db)
        g = svc.create_group(db, name="G", slug="g")
        r = client.delete(f"/api/groups/{g.id}", headers=_auth(token))
        assert r.status_code == 403


# ── Speltakken ────────────────────────────────────────────────────────────────

class TestSpeltakken:
    def test_groepsleider_can_create_speltak(self, client, db):
        token = _full_register(client, db)
        user = db.query(User).filter_by(email="user@example.com").first()
        g = svc.create_group(db, name="G", slug="g", created_by_id=user.id)
        r = client.post(f"/api/groups/{g.id}/speltakken",
                        json={"name": "Welpen", "slug": "welpen"}, headers=_auth(token))
        assert r.status_code == 201
        assert r.json()["slug"] == "welpen"

    def test_non_member_cannot_create_speltak(self, client, db):
        token = _full_register(client, db)
        g = svc.create_group(db, name="G", slug="g")
        r = client.post(f"/api/groups/{g.id}/speltakken",
                        json={"name": "Welpen", "slug": "welpen"}, headers=_auth(token))
        assert r.status_code == 403

    def test_groepsleider_can_delete_speltak(self, client, db):
        token = _full_register(client, db)
        user = db.query(User).filter_by(email="user@example.com").first()
        g = svc.create_group(db, name="G", slug="g", created_by_id=user.id)
        s = svc.create_speltak(db, group_id=g.id, name="S", slug="s")
        r = client.delete(f"/api/groups/{g.id}/speltakken/{s.id}", headers=_auth(token))
        assert r.status_code == 204


# ── Speltak members ───────────────────────────────────────────────────────────

class TestSpeltakMembers:
    def test_set_speltak_role(self, client, db):
        token = _full_register(client, db)
        user = db.query(User).filter_by(email="user@example.com").first()
        g = svc.create_group(db, name="G", slug="g", created_by_id=user.id)
        s = svc.create_speltak(db, group_id=g.id, name="S", slug="s")
        scout = User(email="scout@example.com", name="Scout", status="active", password_hash="x")
        db.add(scout)
        db.commit()
        r = client.post(f"/api/groups/{g.id}/speltakken/{s.id}/members",
                        json={"user_id": scout.id, "role": "scout"}, headers=_auth(token))
        assert r.status_code == 204

    def test_create_emailless_scout(self, client, db):
        token = _full_register(client, db)
        user = db.query(User).filter_by(email="user@example.com").first()
        g = svc.create_group(db, name="G", slug="g", created_by_id=user.id)
        s = svc.create_speltak(db, group_id=g.id, name="S", slug="s")
        svc.set_speltak_role(db, user_id=user.id, speltak_id=s.id, role="speltakleider")
        r = client.post(f"/api/groups/{g.id}/speltakken/{s.id}/scouts",
                        json={"name": "Piet"}, headers=_auth(token))
        assert r.status_code == 201
        assert r.json()["name"] == "Piet"

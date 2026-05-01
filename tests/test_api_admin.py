from insigne.models import ConfirmationToken, ProgressEntry, User


# ── helpers ──────────────────────────────────────────────────────────────────

def _full_register(client, db, email="user@example.com", password="validpass1", name="Test"):
    client.post("/api/users", json={"email": email})
    user = db.query(User).filter_by(email=email).first()
    ct = db.query(ConfirmationToken).filter_by(user_id=user.id, type="email_confirmation").first()
    r = client.post("/api/users/confirm", json={"code": ct.token})
    setup = r.json()["setup_token"]
    r = client.post("/api/users/activate", json={"setup_token": setup, "password": password, "name": name})
    return r.json()["access_token"]


def _auth(token):
    return {"Authorization": f"Bearer {token}"}


def _admin_token(client, db):
    return _full_register(client, db, email="admin@example.com", name="Admin")


def _regular_token(client, db):
    return _full_register(client, db, email="user@example.com", name="User")


# ── GET /api/admin/stats ──────────────────────────────────────────────────────

class TestAdminStats:
    def test_returns_stats_for_admin(self, client, db):
        token = _admin_token(client, db)
        r = client.get("/api/admin/stats", headers=_auth(token))
        assert r.status_code == 200
        body = r.json()
        assert "total_users" in body
        assert body["total_users"] >= 1
        assert "users_by_group" in body
        assert "users_by_status" in body
        assert "users_over_time" in body
        assert "signoff_over_time" in body
        assert "badges_over_time" in body

    def test_requires_auth(self, client, db):
        r = client.get("/api/admin/stats")
        assert r.status_code == 401

    def test_requires_admin(self, client, db):
        token = _regular_token(client, db)
        r = client.get("/api/admin/stats", headers=_auth(token))
        assert r.status_code == 403

    def test_ungrouped_users_counted(self, client, db):
        token = _admin_token(client, db)
        r = client.get("/api/admin/stats", headers=_auth(token))
        body = r.json()
        labels = [g["label"] for g in body["users_by_group"]]
        assert "Zonder groep" in labels

    def test_users_by_status_contains_active(self, client, db):
        token = _admin_token(client, db)
        r = client.get("/api/admin/stats", headers=_auth(token))
        labels = [g["label"] for g in r.json()["users_by_status"]]
        assert "Actief" in labels

    def test_users_over_time_cumulative(self, client, db):
        token = _admin_token(client, db)
        r = client.get("/api/admin/stats", headers=_auth(token))
        rows = r.json()["users_over_time"]
        assert len(rows) >= 1
        counts = [row["count"] for row in rows]
        assert counts == sorted(counts)  # cumulative → non-decreasing


# ── GET /api/admin/users ──────────────────────────────────────────────────────

class TestAdminFindUser:
    def test_finds_existing_user(self, client, db):
        admin_token = _admin_token(client, db)
        _full_register(client, db, email="scout@example.com", name="Scout")
        r = client.get("/api/admin/users", params={"email": "scout@example.com"}, headers=_auth(admin_token))
        assert r.status_code == 200
        body = r.json()
        assert body["email"] == "scout@example.com"
        assert body["name"] == "Scout"

    def test_returns_404_for_unknown(self, client, db):
        token = _admin_token(client, db)
        r = client.get("/api/admin/users", params={"email": "nobody@example.com"}, headers=_auth(token))
        assert r.status_code == 404

    def test_requires_admin(self, client, db):
        token = _regular_token(client, db)
        r = client.get("/api/admin/users", params={"email": "x@x.com"}, headers=_auth(token))
        assert r.status_code == 403

    def test_requires_auth(self, client, db):
        r = client.get("/api/admin/users", params={"email": "x@x.com"})
        assert r.status_code == 401


# ── DELETE /api/admin/users/{user_id} ─────────────────────────────────────────

class TestAdminDeleteUser:
    def test_deletes_user(self, client, db):
        admin_token = _admin_token(client, db)
        _full_register(client, db, email="todelete@example.com", name="Delete Me")
        target = db.query(User).filter_by(email="todelete@example.com").first()
        r = client.delete(f"/api/admin/users/{target.id}", headers=_auth(admin_token))
        assert r.status_code == 204
        db.expire_all()
        assert db.query(User).filter_by(email="todelete@example.com").first() is None

    def test_deletes_users_progress_entries(self, client, db):
        admin_token = _admin_token(client, db)
        _full_register(client, db, email="withprogress@example.com")
        target = db.query(User).filter_by(email="withprogress@example.com").first()
        entry = ProgressEntry(
            user_id=target.id, badge_slug="sport_spel",
            level_index=0, step_index=0, status="in_progress",
        )
        db.add(entry)
        db.commit()
        r = client.delete(f"/api/admin/users/{target.id}", headers=_auth(admin_token))
        assert r.status_code == 204
        db.expire_all()
        assert db.query(ProgressEntry).filter_by(user_id=target.id).count() == 0

    def test_cannot_delete_self(self, client, db):
        token = _admin_token(client, db)
        admin = db.query(User).filter_by(email="admin@example.com").first()
        r = client.delete(f"/api/admin/users/{admin.id}", headers=_auth(token))
        assert r.status_code == 400

    def test_returns_404_for_unknown(self, client, db):
        token = _admin_token(client, db)
        r = client.delete("/api/admin/users/00000000-0000-0000-0000-000000000000", headers=_auth(token))
        assert r.status_code == 404

    def test_requires_admin(self, client, db):
        token = _regular_token(client, db)
        r = client.delete("/api/admin/users/some-id", headers=_auth(token))
        assert r.status_code == 403

    def test_requires_auth(self, client, db):
        r = client.delete("/api/admin/users/some-id")
        assert r.status_code == 401

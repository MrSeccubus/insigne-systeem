from datetime import datetime, timezone

from insigne.models import ConfirmationToken, ProgressEntry, User


# ── helpers ──────────────────────────────────────────────────────────────────

def _full_register(client, db, email="jan@example.com", password="validpass1", name="Jan"):
    client.post("/api/users", json={"email": email})
    user = db.query(User).filter_by(email=email).first()
    ct = db.query(ConfirmationToken).filter_by(user_id=user.id, type="email_confirmation").first()
    r = client.post("/api/users/confirm", json={"code": ct.token})
    setup = r.json()["setup_token"]
    r = client.post("/api/users/activate", json={"setup_token": setup, "password": password, "name": name})
    return r.json()["access_token"]


def _auth(token):
    return {"Authorization": f"Bearer {token}"}


def _create_entry(client, token, badge_slug="kantklossen", level_index=0, step_index=0, notes=None):
    body = {"badge_slug": badge_slug, "level_index": level_index, "step_index": step_index}
    if notes is not None:
        body["notes"] = notes
    return client.post("/api/progress", json=body, headers=_auth(token))


def _completed_entry(db, user_id, badge_slug="kantklossen", level_index=0, step_index=0):
    entry = ProgressEntry(
        user_id=user_id,
        badge_slug=badge_slug,
        level_index=level_index,
        step_index=step_index,
        status="signed_off",
        signed_off_at=datetime.now(timezone.utc),
    )
    db.add(entry)
    db.commit()
    return entry


def _set_work_done(db, entry_id):
    entry = db.query(ProgressEntry).filter_by(id=entry_id).first()
    entry.status = "work_done"
    db.commit()


# ── GET /api/progress ─────────────────────────────────────────────────────────

class TestListProgress:
    def test_empty_for_new_user(self, client, db):
        token = _full_register(client, db)
        r = client.get("/api/progress", headers=_auth(token))
        assert r.status_code == 200
        assert r.json() == []

    def test_requires_auth(self, client, db):
        r = client.get("/api/progress")
        assert r.status_code == 401

    def test_filters_by_badge_slug(self, client, db):
        token = _full_register(client, db)
        _create_entry(client, token, badge_slug="kantklossen", level_index=0, step_index=0)
        _create_entry(client, token, badge_slug="cybersecurity", level_index=0, step_index=0)
        r = client.get("/api/progress?badge_slug=kantklossen", headers=_auth(token))
        assert r.status_code == 200
        results = r.json()
        assert len(results) == 1
        assert results[0]["badge_slug"] == "kantklossen"

    def test_filters_by_status(self, client, db):
        token = _full_register(client, db)
        _create_entry(client, token, level_index=0, step_index=0)
        _create_entry(client, token, level_index=0, step_index=1)
        user = db.query(User).filter_by(email="jan@example.com").first()
        _completed_entry(db, user.id, level_index=0, step_index=2)
        r = client.get("/api/progress?status=in_progress", headers=_auth(token))
        assert all(e["status"] == "in_progress" for e in r.json())
        assert len(r.json()) == 2


# ── POST /api/progress ────────────────────────────────────────────────────────

class TestCreateProgress:
    def test_creates_entry_with_status_open(self, client, db):
        token = _full_register(client, db)
        r = _create_entry(client, token)
        assert r.status_code == 201
        data = r.json()
        assert data["status"] == "in_progress"
        assert data["badge_slug"] == "kantklossen"
        assert data["level_index"] == 0
        assert data["step_index"] == 0

    def test_stores_notes(self, client, db):
        token = _full_register(client, db)
        r = _create_entry(client, token, notes="interesting session")
        assert r.json()["notes"] == "interesting session"

    def test_conflict_for_completed_step_returns_409(self, client, db):
        token = _full_register(client, db)
        user = db.query(User).filter_by(email="jan@example.com").first()
        _completed_entry(db, user.id)
        r = _create_entry(client, token)
        assert r.status_code == 409

    def test_requires_auth(self, client, db):
        r = client.post("/api/progress", json={"badge_slug": "kantklossen", "level_index": 0, "step_index": 0})
        assert r.status_code == 401


# ── GET /api/progress/{id} ────────────────────────────────────────────────────

class TestGetProgress:
    def test_returns_entry(self, client, db):
        token = _full_register(client, db)
        entry_id = _create_entry(client, token).json()["id"]
        r = client.get(f"/api/progress/{entry_id}", headers=_auth(token))
        assert r.status_code == 200
        assert r.json()["id"] == entry_id

    def test_not_found_returns_404(self, client, db):
        token = _full_register(client, db)
        r = client.get("/api/progress/nonexistent-id", headers=_auth(token))
        assert r.status_code == 404

    def test_other_users_entry_returns_404(self, client, db):
        token1 = _full_register(client, db, "scout1@example.com")
        token2 = _full_register(client, db, "scout2@example.com")
        entry_id = _create_entry(client, token1).json()["id"]
        r = client.get(f"/api/progress/{entry_id}", headers=_auth(token2))
        assert r.status_code == 404


# ── PUT /api/progress/{id} ────────────────────────────────────────────────────

class TestUpdateProgress:
    def test_updates_notes(self, client, db):
        token = _full_register(client, db)
        entry_id = _create_entry(client, token).json()["id"]
        r = client.put(f"/api/progress/{entry_id}", json={"notes": "updated"}, headers=_auth(token))
        assert r.status_code == 200
        assert r.json()["notes"] == "updated"

    def test_completed_entry_returns_403(self, client, db):
        token = _full_register(client, db)
        user = db.query(User).filter_by(email="jan@example.com").first()
        entry = _completed_entry(db, user.id)
        r = client.put(f"/api/progress/{entry.id}", json={"notes": "x"}, headers=_auth(token))
        assert r.status_code == 403

    def test_not_found_returns_404(self, client, db):
        token = _full_register(client, db)
        r = client.put("/api/progress/nonexistent", json={"notes": "x"}, headers=_auth(token))
        assert r.status_code == 404


# ── DELETE /api/progress/{id} ─────────────────────────────────────────────────

class TestDeleteProgress:
    def test_returns_204(self, client, db):
        token = _full_register(client, db)
        entry_id = _create_entry(client, token).json()["id"]
        r = client.delete(f"/api/progress/{entry_id}", headers=_auth(token))
        assert r.status_code == 204

    def test_completed_entry_returns_403(self, client, db):
        token = _full_register(client, db)
        user = db.query(User).filter_by(email="jan@example.com").first()
        entry = _completed_entry(db, user.id)
        r = client.delete(f"/api/progress/{entry.id}", headers=_auth(token))
        assert r.status_code == 403

    def test_not_found_returns_404(self, client, db):
        token = _full_register(client, db)
        r = client.delete("/api/progress/nonexistent", headers=_auth(token))
        assert r.status_code == 404


# ── POST /api/progress/{id}/signoff ──────────────────────────────────────────

class TestRequestSignoff:
    def test_returns_202(self, client, db):
        token = _full_register(client, db)
        entry_id = _create_entry(client, token).json()["id"]
        _set_work_done(db, entry_id)
        r = client.post(f"/api/progress/{entry_id}/signoff",
                        json={"mentor_email": "mentor@example.com"},
                        headers=_auth(token))
        assert r.status_code == 202

    def test_entry_becomes_pending_signoff(self, client, db):
        token = _full_register(client, db)
        entry_id = _create_entry(client, token).json()["id"]
        _set_work_done(db, entry_id)
        client.post(f"/api/progress/{entry_id}/signoff",
                    json={"mentor_email": "mentor@example.com"},
                    headers=_auth(token))
        r = client.get(f"/api/progress/{entry_id}", headers=_auth(token))
        assert r.json()["status"] == "pending_signoff"

    def test_pending_mentor_appears_in_entry(self, client, db):
        token = _full_register(client, db)
        entry_id = _create_entry(client, token).json()["id"]
        _set_work_done(db, entry_id)
        client.post(f"/api/progress/{entry_id}/signoff",
                    json={"mentor_email": "mentor@example.com"},
                    headers=_auth(token))
        r = client.get(f"/api/progress/{entry_id}", headers=_auth(token))
        assert len(r.json()["pending_mentors"]) == 1

    def test_already_completed_returns_409(self, client, db):
        token = _full_register(client, db)
        user = db.query(User).filter_by(email="jan@example.com").first()
        entry = _completed_entry(db, user.id)
        r = client.post(f"/api/progress/{entry.id}/signoff",
                        json={"mentor_email": "mentor@example.com"},
                        headers=_auth(token))
        assert r.status_code == 409

    def test_duplicate_invite_returns_409(self, client, db):
        token = _full_register(client, db)
        entry_id = _create_entry(client, token).json()["id"]
        _set_work_done(db, entry_id)
        client.post(f"/api/progress/{entry_id}/signoff",
                    json={"mentor_email": "mentor@example.com"},
                    headers=_auth(token))
        r = client.post(f"/api/progress/{entry_id}/signoff",
                        json={"mentor_email": "mentor@example.com"},
                        headers=_auth(token))
        assert r.status_code == 409

    def test_not_found_returns_404(self, client, db):
        token = _full_register(client, db)
        r = client.post("/api/progress/nonexistent/signoff",
                        json={"mentor_email": "mentor@example.com"},
                        headers=_auth(token))
        assert r.status_code == 404


# ── POST /api/progress/{id}/signoff/confirm ───────────────────────────────────

class TestConfirmSignoff:
    def _setup(self, client, db):
        scout_token = _full_register(client, db, "scout@example.com", name="Scout")
        mentor_token = _full_register(client, db, "mentor@example.com", name="Mentor")
        entry_id = _create_entry(client, scout_token).json()["id"]
        _set_work_done(db, entry_id)
        client.post(f"/api/progress/{entry_id}/signoff",
                    json={"mentor_email": "mentor@example.com"},
                    headers=_auth(scout_token))
        return scout_token, mentor_token, entry_id

    def test_returns_completed_entry(self, client, db):
        _, mentor_token, entry_id = self._setup(client, db)
        r = client.post(f"/api/progress/{entry_id}/signoff/confirm",
                        headers=_auth(mentor_token))
        assert r.status_code == 200
        data = r.json()
        assert data["status"] == "signed_off"
        assert data["signed_off_by"] is not None

    def test_not_invited_returns_403(self, client, db):
        other_token = _full_register(client, db, "other@example.com", name="Other")
        scout_token = _full_register(client, db, "scout@example.com", name="Scout")
        entry_id = _create_entry(client, scout_token).json()["id"]
        r = client.post(f"/api/progress/{entry_id}/signoff/confirm",
                        headers=_auth(other_token))
        assert r.status_code == 403

    def test_already_completed_returns_409(self, client, db):
        _, mentor_token, entry_id = self._setup(client, db)
        client.post(f"/api/progress/{entry_id}/signoff/confirm",
                    headers=_auth(mentor_token))
        r = client.post(f"/api/progress/{entry_id}/signoff/confirm",
                        headers=_auth(mentor_token))
        assert r.status_code == 409


# ── GET /api/signoff-requests ─────────────────────────────────────────────────

class TestListSignoffRequests:
    def test_empty_when_no_requests(self, client, db):
        token = _full_register(client, db)
        r = client.get("/api/signoff-requests", headers=_auth(token))
        assert r.status_code == 200
        assert r.json() == []

    def test_returns_pending_requests_for_mentor(self, client, db):
        scout_token = _full_register(client, db, "scout@example.com")
        mentor_token = _full_register(client, db, "mentor@example.com")
        entry_id = _create_entry(client, scout_token).json()["id"]
        _set_work_done(db, entry_id)
        client.post(f"/api/progress/{entry_id}/signoff",
                    json={"mentor_email": "mentor@example.com"},
                    headers=_auth(scout_token))
        r = client.get("/api/signoff-requests", headers=_auth(mentor_token))
        assert r.status_code == 200
        assert len(r.json()) == 1
        assert r.json()[0]["badge_slug"] == "kantklossen"

    def test_requires_auth(self, client, db):
        r = client.get("/api/signoff-requests")
        assert r.status_code == 401


# ── GET /api/progress/mentors ─────────────────────────────────────────────────

class TestListMentors:
    def test_empty_for_new_scout(self, client, db):
        token = _full_register(client, db)
        r = client.get("/api/progress/mentors", headers=_auth(token))
        assert r.status_code == 200
        assert r.json() == []

    def test_returns_mentor_after_confirmed_signoff(self, client, db):
        scout_token = _full_register(client, db, "scout@example.com")
        mentor_token = _full_register(client, db, "mentor@example.com", name="Mentor")
        entry_id = _create_entry(client, scout_token).json()["id"]
        _set_work_done(db, entry_id)
        client.post(f"/api/progress/{entry_id}/signoff",
                    json={"mentor_email": "mentor@example.com"},
                    headers=_auth(scout_token))
        client.post(f"/api/progress/{entry_id}/signoff/confirm",
                    headers=_auth(mentor_token))
        r = client.get("/api/progress/mentors", headers=_auth(scout_token))
        assert r.status_code == 200
        assert len(r.json()) == 1
        assert r.json()[0]["name"] == "Mentor"

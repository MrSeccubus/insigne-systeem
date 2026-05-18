"""API-layer tests for the jaarinsigne_2026 JSON endpoints."""
from insigne.auth import create_access_token
from insigne import groups as groups_svc
from insigne.models import (
    GroupMembership,
    Jaarinsigne2026Inclusion,
    ProgressEntry,
    SignoffRejection,
    SignoffRequest,
    SpeltakMembership,
    User,
)


def _token_for(user):
    token, _ = create_access_token(user.id)
    return {"Authorization": f"Bearer {token}"}


def _user(db, email, name="X"):
    u = User(email=email, name=name, status="active", password_hash="x")
    db.add(u)
    db.commit()
    return u


def _signed_off(db, user_id, badge_slug, level_index, step_index):
    e = ProgressEntry(
        user_id=user_id, badge_slug=badge_slug,
        level_index=level_index, step_index=step_index, status="signed_off",
    )
    db.add(e)
    db.commit()
    return e


def _entry(db, user_id, level_index, step_index, status, badge_slug="jaarinsigne_2026"):
    e = ProgressEntry(
        user_id=user_id, badge_slug=badge_slug,
        level_index=level_index, step_index=step_index, status=status,
    )
    db.add(e)
    db.commit()
    return e


def _speltak_with_leider(db, leider, scout, speltak_type="welpen"):
    g = groups_svc.create_group(db, name="Groep X", slug="groep-x", created_by_id=leider.id)
    s = groups_svc.create_speltak(
        db, group_id=g.id, name="Welpen", slug="welpen", speltak_type=speltak_type,
    )
    db.add(GroupMembership(user_id=leider.id, group_id=g.id, role="groepsleider", approved=True))
    db.add(SpeltakMembership(user_id=leider.id, speltak_id=s.id, role="speltakleider", approved=True))
    db.add(GroupMembership(user_id=scout.id, group_id=g.id, role="member", approved=True))
    db.add(SpeltakMembership(user_id=scout.id, speltak_id=s.id, role="scout", approved=True))
    db.commit()
    return g, s


# ── GET /api/users/me/jaarinsigne_2026/score ─────────────────────────────────

class TestScore:
    def test_returns_score_summary(self, client, db):
        scout = _user(db, "scout@x.com")
        leider = _user(db, "leider@x.com")
        _speltak_with_leider(db, leider, scout)
        # Sign off a couple of eligible eisen, include them.
        _signed_off(db, scout.id, "kamperen", 0, 0)
        db.add(Jaarinsigne2026Inclusion(user_id=scout.id, badge_slug="kamperen",
                                       level_index=0, step_index=0))
        db.commit()

        r = client.get("/api/users/me/jaarinsigne_2026/score", headers=_token_for(scout))
        assert r.status_code == 200
        body = r.json()
        assert body["speltak_slug"] == "welpen"
        assert body["score"]["total_punten"] == 1
        assert body["score"]["distinct_insignes"] == 1
        assert "eis_statuses" in body

    def test_requires_speltak(self, client, db):
        scout = _user(db, "scout@x.com")  # no speltak membership
        r = client.get("/api/users/me/jaarinsigne_2026/score", headers=_token_for(scout))
        assert r.status_code == 404


# ── GET inclusions + available ───────────────────────────────────────────────

class TestInclusionsListing:
    def test_lists_only_current_user_inclusions(self, client, db):
        a = _user(db, "a@x.com")
        b = _user(db, "b@x.com")
        _signed_off(db, a.id, "kamperen", 0, 0)
        db.add(Jaarinsigne2026Inclusion(user_id=a.id, badge_slug="kamperen",
                                       level_index=0, step_index=0))
        db.commit()
        r = client.get("/api/users/me/jaarinsigne_2026/inclusions", headers=_token_for(a))
        assert r.status_code == 200
        assert len(r.json()) == 1
        r = client.get("/api/users/me/jaarinsigne_2026/inclusions", headers=_token_for(b))
        assert r.json() == []

    def test_available_excludes_already_included(self, client, db):
        a = _user(db, "a@x.com")
        _signed_off(db, a.id, "kamperen", 0, 0)
        _signed_off(db, a.id, "kamperen", 0, 1)
        db.add(Jaarinsigne2026Inclusion(user_id=a.id, badge_slug="kamperen",
                                       level_index=0, step_index=0))
        db.commit()
        r = client.get(
            "/api/users/me/jaarinsigne_2026/inclusions/available",
            headers=_token_for(a),
        )
        assert r.status_code == 200
        keys = {(it["badge_slug"], it["level_index"], it["step_index"]) for it in r.json()}
        assert ("kamperen", 0, 1) in keys
        assert ("kamperen", 0, 0) not in keys

    def test_requires_auth(self, client, db):
        r = client.get("/api/users/me/jaarinsigne_2026/inclusions")
        assert r.status_code == 401


# ── POST /inclusions/toggle ──────────────────────────────────────────────────

class TestToggle:
    def test_toggle_adds_and_then_removes(self, client, db):
        scout = _user(db, "scout@x.com")
        leider = _user(db, "leider@x.com")
        _speltak_with_leider(db, leider, scout)
        _signed_off(db, scout.id, "kamperen", 0, 0)
        body = {"badge_slug": "kamperen", "level_index": 0, "step_index": 0}

        r1 = client.post(
            "/api/users/me/jaarinsigne_2026/inclusions/toggle",
            json=body, headers=_token_for(scout),
        )
        assert r1.status_code == 200
        assert r1.json()["included"] is True

        r2 = client.post(
            "/api/users/me/jaarinsigne_2026/inclusions/toggle",
            json=body, headers=_token_for(scout),
        )
        assert r2.status_code == 200
        assert r2.json()["included"] is False

    def test_rejects_unsignoffed_eis(self, client, db):
        scout = _user(db, "scout@x.com")
        _entry(db, scout.id, 0, 0, "in_progress", badge_slug="kamperen")
        r = client.post(
            "/api/users/me/jaarinsigne_2026/inclusions/toggle",
            json={"badge_slug": "kamperen", "level_index": 0, "step_index": 0},
            headers=_token_for(scout),
        )
        assert r.status_code == 409

    def test_rejects_non_eligible_badge(self, client, db):
        scout = _user(db, "scout@x.com")
        r = client.post(
            "/api/users/me/jaarinsigne_2026/inclusions/toggle",
            json={"badge_slug": "jaarinsigne_2025", "level_index": 0, "step_index": 0},
            headers=_token_for(scout),
        )
        assert r.status_code == 422

    def test_blocked_when_pending(self, client, db):
        scout = _user(db, "scout@x.com")
        leider = _user(db, "leider@x.com")
        _, speltak = _speltak_with_leider(db, leider, scout)
        # Put scout into "pending" state by creating a work_done jaarinsigne entry and inviting.
        _entry(db, scout.id, 1, 0, "work_done")
        # Use the JSON API to invite — simulates the actual flow.
        client.post(
            "/api/users/me/jaarinsigne_2026/signoff/speltak",
            json={"speltak_id": speltak.id}, headers=_token_for(scout),
        )
        # Now try to toggle an eligible eis — must 409.
        _signed_off(db, scout.id, "kamperen", 0, 0)
        r = client.post(
            "/api/users/me/jaarinsigne_2026/inclusions/toggle",
            json={"badge_slug": "kamperen", "level_index": 0, "step_index": 0},
            headers=_token_for(scout),
        )
        assert r.status_code == 409


# ── POST signoff variants ────────────────────────────────────────────────────

class TestRequestSignoff:
    def test_speltak_path_creates_pending_requests(self, client, db):
        scout = _user(db, "scout@x.com")
        leider = _user(db, "leider@x.com")
        _, speltak = _speltak_with_leider(db, leider, scout)
        _entry(db, scout.id, 1, 0, "work_done")
        _entry(db, scout.id, 1, 1, "work_done")

        r = client.post(
            "/api/users/me/jaarinsigne_2026/signoff/speltak",
            json={"speltak_id": speltak.id}, headers=_token_for(scout),
        )
        assert r.status_code == 202
        assert db.query(SignoffRequest).count() == 2
        for e in db.query(ProgressEntry).filter_by(user_id=scout.id).all():
            assert e.status == "pending_signoff"

    def test_members_path_creates_pending_requests(self, client, db):
        scout = _user(db, "scout@x.com")
        peer = _user(db, "peer@x.com")
        _entry(db, scout.id, 1, 0, "work_done")
        r = client.post(
            "/api/users/me/jaarinsigne_2026/signoff/members",
            json={"mentor_ids": [peer.id]}, headers=_token_for(scout),
        )
        assert r.status_code == 202
        assert db.query(SignoffRequest).count() == 1

    def test_direct_path_creates_mentor(self, client, db):
        scout = _user(db, "scout@x.com")
        _entry(db, scout.id, 1, 0, "work_done")
        r = client.post(
            "/api/users/me/jaarinsigne_2026/signoff",
            json={"mentor_email": "new@x.com"}, headers=_token_for(scout),
        )
        assert r.status_code == 202
        assert db.query(User).filter_by(email="new@x.com").first() is not None

    def test_direct_self_signoff_403(self, client, db):
        scout = _user(db, "scout@x.com")
        _entry(db, scout.id, 1, 0, "work_done")
        r = client.post(
            "/api/users/me/jaarinsigne_2026/signoff",
            json={"mentor_email": "scout@x.com"}, headers=_token_for(scout),
        )
        assert r.status_code == 403


# ── DELETE /signoff ──────────────────────────────────────────────────────────

class TestCancel:
    def test_reverts_pending_to_work_done(self, client, db):
        scout = _user(db, "scout@x.com")
        leider = _user(db, "leider@x.com")
        _, speltak = _speltak_with_leider(db, leider, scout)
        _entry(db, scout.id, 1, 0, "work_done")
        client.post(
            "/api/users/me/jaarinsigne_2026/signoff/speltak",
            json={"speltak_id": speltak.id}, headers=_token_for(scout),
        )
        r = client.delete(
            "/api/users/me/jaarinsigne_2026/signoff", headers=_token_for(scout),
        )
        assert r.status_code == 200
        assert db.query(SignoffRequest).count() == 0
        e = db.query(ProgressEntry).filter_by(user_id=scout.id).first()
        assert e.status == "work_done"


# ── POST /scouts/{id}/jaarinsigne_2026/{confirm,reject}-signoff ──────────────

class TestMentorBatch:
    def test_confirm_signs_off_all(self, client, db):
        scout = _user(db, "scout@x.com")
        leider = _user(db, "leider@x.com")
        _, speltak = _speltak_with_leider(db, leider, scout)
        _entry(db, scout.id, 1, 0, "work_done")
        _entry(db, scout.id, 1, 1, "work_done")
        client.post(
            "/api/users/me/jaarinsigne_2026/signoff/speltak",
            json={"speltak_id": speltak.id}, headers=_token_for(scout),
        )
        r = client.post(
            f"/api/scouts/{scout.id}/jaarinsigne_2026/confirm-signoff",
            json={"comment": "Goed gedaan"}, headers=_token_for(leider),
        )
        assert r.status_code == 200
        for e in db.query(ProgressEntry).filter_by(user_id=scout.id).all():
            assert e.status == "signed_off"

    def test_reject_creates_rejections(self, client, db):
        scout = _user(db, "scout@x.com")
        leider = _user(db, "leider@x.com")
        _, speltak = _speltak_with_leider(db, leider, scout)
        _entry(db, scout.id, 1, 0, "work_done")
        _entry(db, scout.id, 1, 1, "work_done")
        client.post(
            "/api/users/me/jaarinsigne_2026/signoff/speltak",
            json={"speltak_id": speltak.id}, headers=_token_for(scout),
        )
        r = client.post(
            f"/api/scouts/{scout.id}/jaarinsigne_2026/reject-signoff",
            json={"message": "Probeer nog eens"}, headers=_token_for(leider),
        )
        assert r.status_code == 200
        for e in db.query(ProgressEntry).filter_by(user_id=scout.id).all():
            assert e.status == "work_done"
        assert db.query(SignoffRejection).count() == 2

    def test_confirm_self_forbidden(self, client, db):
        scout = _user(db, "scout@x.com")
        r = client.post(
            f"/api/scouts/{scout.id}/jaarinsigne_2026/confirm-signoff",
            json={}, headers=_token_for(scout),
        )
        assert r.status_code == 403

    def test_reject_self_forbidden(self, client, db):
        scout = _user(db, "scout@x.com")
        r = client.post(
            f"/api/scouts/{scout.id}/jaarinsigne_2026/reject-signoff",
            json={"message": "x"}, headers=_token_for(scout),
        )
        assert r.status_code == 403

    def test_uninvited_mentor_forbidden(self, client, db):
        scout = _user(db, "scout@x.com")
        bystander = _user(db, "bystander@x.com")
        _entry(db, scout.id, 1, 0, "work_done")
        r = client.post(
            f"/api/scouts/{scout.id}/jaarinsigne_2026/confirm-signoff",
            json={}, headers=_token_for(bystander),
        )
        assert r.status_code == 403

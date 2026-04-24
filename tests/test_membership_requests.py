"""Tests for the membership request / approval flow."""
import pytest
from insigne import groups as svc
from insigne.models import ConfirmationToken, MembershipRequest, User


def _user(db, email="user@example.com", name="User"):
    u = User(email=email, name=name, status="active", password_hash="x")
    db.add(u)
    db.commit()
    return u


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


# ── Library: create_membership_request ───────────────────────────────────────

class TestCreateMembershipRequest:
    def test_creates_pending_request(self, client, db):
        scout = _user(db, email="scout@example.com")
        g = svc.create_group(db, name="G", slug="g")
        req = svc.create_membership_request(db, user_id=scout.id, group_id=g.id)
        assert req.status == "pending"
        assert req.speltak_id is None

    def test_creates_speltak_request(self, client, db):
        scout = _user(db, email="scout@example.com")
        g = svc.create_group(db, name="G", slug="g")
        s = svc.create_speltak(db, group_id=g.id, name="S", slug="s")
        req = svc.create_membership_request(db, user_id=scout.id, group_id=g.id, speltak_id=s.id)
        assert req.speltak_id == s.id

    def test_raises_if_already_member(self, client, db):
        scout = _user(db, email="scout@example.com")
        g = svc.create_group(db, name="G", slug="g")
        svc.set_group_role(db, user_id=scout.id, group_id=g.id, role="member")
        with pytest.raises(ValueError, match="already_member"):
            svc.create_membership_request(db, user_id=scout.id, group_id=g.id)

    def test_raises_if_duplicate_pending(self, client, db):
        scout = _user(db, email="scout@example.com")
        g = svc.create_group(db, name="G", slug="g")
        svc.create_membership_request(db, user_id=scout.id, group_id=g.id)
        with pytest.raises(ValueError, match="request_exists"):
            svc.create_membership_request(db, user_id=scout.id, group_id=g.id)


# ── Library: approve / reject ─────────────────────────────────────────────────

class TestApproveRejectRequest:
    def test_approve_creates_group_membership(self, client, db):
        scout = _user(db, email="scout@example.com")
        leider = _user(db)
        g = svc.create_group(db, name="G", slug="g", created_by_id=leider.id)
        req = svc.create_membership_request(db, user_id=scout.id, group_id=g.id)
        svc.approve_membership_request(db, request_id=req.id, reviewed_by_id=leider.id)
        members = svc.list_group_members(db, g.id)
        assert any(m.user_id == scout.id for m in members)
        db.refresh(req)
        assert req.status == "approved"

    def test_approve_creates_speltak_membership(self, client, db):
        scout = _user(db, email="scout@example.com")
        leider = _user(db)
        g = svc.create_group(db, name="G", slug="g", created_by_id=leider.id)
        s = svc.create_speltak(db, group_id=g.id, name="S", slug="s")
        req = svc.create_membership_request(db, user_id=scout.id, group_id=g.id, speltak_id=s.id)
        svc.approve_membership_request(db, request_id=req.id, reviewed_by_id=leider.id)
        members = svc.list_speltak_members(db, s.id)
        assert any(m.user_id == scout.id for m in members)

    def test_reject_sets_status(self, client, db):
        scout = _user(db, email="scout@example.com")
        leider = _user(db)
        g = svc.create_group(db, name="G", slug="g", created_by_id=leider.id)
        req = svc.create_membership_request(db, user_id=scout.id, group_id=g.id)
        svc.reject_membership_request(db, request_id=req.id, reviewed_by_id=leider.id)
        db.refresh(req)
        assert req.status == "rejected"
        members = svc.list_group_members(db, g.id)
        assert not any(m.user_id == scout.id for m in members)

    def test_approve_unknown_raises(self, client, db):
        leider = _user(db)
        with pytest.raises(ValueError, match="not_found"):
            svc.approve_membership_request(db, request_id="nonexistent", reviewed_by_id=leider.id)


# ── Library: list / count ─────────────────────────────────────────────────────

class TestListRequests:
    def test_list_pending_for_group(self, client, db):
        scout = _user(db, email="scout@example.com")
        g = svc.create_group(db, name="G", slug="g")
        svc.create_membership_request(db, user_id=scout.id, group_id=g.id)
        pending = svc.list_pending_requests_for_group(db, g.id)
        assert len(pending) == 1

    def test_approved_not_in_pending_list(self, client, db):
        scout = _user(db, email="scout@example.com")
        leider = _user(db)
        g = svc.create_group(db, name="G", slug="g", created_by_id=leider.id)
        req = svc.create_membership_request(db, user_id=scout.id, group_id=g.id)
        svc.approve_membership_request(db, request_id=req.id, reviewed_by_id=leider.id)
        assert svc.list_pending_requests_for_group(db, g.id) == []

    def test_count_for_leader(self, client, db):
        scout = _user(db, email="scout@example.com")
        leider = _user(db)
        g = svc.create_group(db, name="G", slug="g", created_by_id=leider.id)
        svc.create_membership_request(db, user_id=scout.id, group_id=g.id)
        assert svc.count_pending_requests_for_leader(db, leider.id) == 1

    def test_count_zero_for_non_leader(self, client, db):
        scout = _user(db, email="scout@example.com")
        outsider = _user(db, email="out@example.com")
        g = svc.create_group(db, name="G", slug="g")
        svc.create_membership_request(db, user_id=scout.id, group_id=g.id)
        assert svc.count_pending_requests_for_leader(db, outsider.id) == 0

    def test_search_groups(self, client, db):
        svc.create_group(db, name="Groep Noord", slug="groep-noord")
        svc.create_group(db, name="Groep Zuid", slug="groep-zuid")
        results = svc.search_groups(db, "noord")
        assert len(results) == 1
        assert results[0].slug == "groep-noord"


# ── JSON API ──────────────────────────────────────────────────────────────────

class TestMembershipRequestAPI:
    def test_create_request(self, client, db):
        token = _full_register(client, db)
        user = db.query(User).filter_by(email="user@example.com").first()
        g = svc.create_group(db, name="G", slug="g")
        r = client.post(f"/api/groups/{g.id}/requests", json={}, headers=_auth(token))
        assert r.status_code == 201
        assert r.json()["status"] == "pending"
        assert r.json()["user_id"] == user.id

    def test_create_speltak_request(self, client, db):
        token = _full_register(client, db)
        g = svc.create_group(db, name="G", slug="g")
        s = svc.create_speltak(db, group_id=g.id, name="S", slug="s")
        r = client.post(f"/api/groups/{g.id}/requests",
                        json={"speltak_id": s.id}, headers=_auth(token))
        assert r.status_code == 201
        assert r.json()["speltak_id"] == s.id

    def test_duplicate_request_returns_409(self, client, db):
        token = _full_register(client, db)
        g = svc.create_group(db, name="G", slug="g")
        client.post(f"/api/groups/{g.id}/requests", json={}, headers=_auth(token))
        r = client.post(f"/api/groups/{g.id}/requests", json={}, headers=_auth(token))
        assert r.status_code == 409

    def test_list_requests_requires_manager(self, client, db):
        token = _full_register(client, db)
        g = svc.create_group(db, name="G", slug="g")
        r = client.get(f"/api/groups/{g.id}/requests", headers=_auth(token))
        assert r.status_code == 403

    def test_list_requests_as_leader(self, client, db):
        token = _full_register(client, db)
        user = db.query(User).filter_by(email="user@example.com").first()
        g = svc.create_group(db, name="G", slug="g", created_by_id=user.id)
        scout = _user(db, email="scout@example.com")
        svc.create_membership_request(db, user_id=scout.id, group_id=g.id)
        r = client.get(f"/api/groups/{g.id}/requests", headers=_auth(token))
        assert r.status_code == 200
        assert len(r.json()) == 1

    def test_approve_request(self, client, db):
        token = _full_register(client, db)
        user = db.query(User).filter_by(email="user@example.com").first()
        g = svc.create_group(db, name="G", slug="g", created_by_id=user.id)
        scout = _user(db, email="scout@example.com")
        req = svc.create_membership_request(db, user_id=scout.id, group_id=g.id)
        r = client.post(f"/api/groups/{g.id}/requests/{req.id}/approve", headers=_auth(token))
        assert r.status_code == 204
        db.refresh(req)
        assert req.status == "approved"

    def test_reject_request(self, client, db):
        token = _full_register(client, db)
        user = db.query(User).filter_by(email="user@example.com").first()
        g = svc.create_group(db, name="G", slug="g", created_by_id=user.id)
        scout = _user(db, email="scout@example.com")
        req = svc.create_membership_request(db, user_id=scout.id, group_id=g.id)
        r = client.post(f"/api/groups/{g.id}/requests/{req.id}/reject", headers=_auth(token))
        assert r.status_code == 204
        db.refresh(req)
        assert req.status == "rejected"

    def test_unauthenticated_returns_401(self, client, db):
        g = svc.create_group(db, name="G", slug="g")
        r = client.post(f"/api/groups/{g.id}/requests", json={})
        assert r.status_code == 401


# ── HTML: join flow ───────────────────────────────────────────────────────────

class TestGroupsJoinHTML:
    def _login(self, client, user):
        from insigne.auth import create_access_token
        token, _ = create_access_token(user.id)
        client.cookies.set("access_token", token)

    def test_join_page_requires_auth(self, client, db):
        r = client.get("/groups/join", follow_redirects=False)
        assert r.status_code == 303

    def test_join_page_loads(self, client, db):
        user = _user(db)
        self._login(client, user)
        r = client.get("/groups/join")
        assert r.status_code == 200

    def test_group_search_endpoint(self, client, db):
        svc.create_group(db, name="Groep Noord", slug="groep-noord")
        r = client.get("/groups/search?q=noord")
        assert r.status_code == 200
        data = r.json()
        assert len(data) == 1
        assert data[0]["slug"] == "groep-noord"

    def test_submit_creates_request(self, client, db):
        user = _user(db)
        self._login(client, user)
        g = svc.create_group(db, name="G", slug="g")
        r = client.post("/groups/join", data={"group_id": g.id, "speltak_id": ""})
        assert r.status_code == 200
        assert "verstuurd" in r.text
        reqs = db.query(MembershipRequest).filter_by(user_id=user.id, group_id=g.id).all()
        assert len(reqs) == 1

    def test_duplicate_shows_error(self, client, db):
        user = _user(db)
        self._login(client, user)
        g = svc.create_group(db, name="G", slug="g")
        svc.create_membership_request(db, user_id=user.id, group_id=g.id)
        r = client.post("/groups/join", data={"group_id": g.id, "speltak_id": ""})
        assert r.status_code == 200
        assert "openstaande aanvraag" in r.text


# ── HTML: leader review (/requests) ──────────────────────────────────────────

class TestGroupRequestsHTML:
    def _login(self, client, user):
        from insigne.auth import create_access_token
        token, _ = create_access_token(user.id)
        client.cookies.set("access_token", token)

    def test_requests_page_shows_pending(self, client, db):
        leider = _user(db)
        scout = _user(db, email="scout@example.com", name="Scout")
        g = svc.create_group(db, name="G", slug="g", created_by_id=leider.id)
        svc.create_membership_request(db, user_id=scout.id, group_id=g.id)
        self._login(client, leider)
        r = client.get("/requests")
        assert r.status_code == 200
        assert "Scout" in r.text

    def test_approve_redirects(self, client, db):
        leider = _user(db)
        scout = _user(db, email="scout@example.com")
        g = svc.create_group(db, name="G", slug="g", created_by_id=leider.id)
        req = svc.create_membership_request(db, user_id=scout.id, group_id=g.id)
        self._login(client, leider)
        r = client.post(f"/requests/{req.id}/approve", follow_redirects=False)
        assert r.status_code == 303
        db.refresh(req)
        assert req.status == "approved"

    def test_reject_redirects(self, client, db):
        leider = _user(db)
        scout = _user(db, email="scout@example.com")
        g = svc.create_group(db, name="G", slug="g", created_by_id=leider.id)
        req = svc.create_membership_request(db, user_id=scout.id, group_id=g.id)
        self._login(client, leider)
        r = client.post(f"/requests/{req.id}/reject", follow_redirects=False)
        assert r.status_code == 303
        db.refresh(req)
        assert req.status == "rejected"

    def test_unauthenticated_redirected(self, client, db):
        r = client.get("/requests", follow_redirects=False)
        assert r.status_code == 303


# ── HTML: cancel own requests ─────────────────────────────────────────────────

class TestCancelMyRequests:
    def _login(self, client, user):
        from insigne.auth import create_access_token
        token, _ = create_access_token(user.id)
        client.cookies.set("access_token", token)

    def test_cancel_single_request(self, client, db):
        user = _user(db)
        self._login(client, user)
        g = svc.create_group(db, name="G", slug="g")
        req = svc.create_membership_request(db, user_id=user.id, group_id=g.id)
        r = client.post(f"/my-requests/{req.id}/cancel", follow_redirects=False)
        assert r.status_code == 303
        assert db.query(MembershipRequest).filter_by(id=req.id).first() is None

    def test_cancel_all_requests(self, client, db):
        user = _user(db)
        self._login(client, user)
        g1 = svc.create_group(db, name="G1", slug="g1")
        g2 = svc.create_group(db, name="G2", slug="g2")
        svc.create_membership_request(db, user_id=user.id, group_id=g1.id)
        svc.create_membership_request(db, user_id=user.id, group_id=g2.id)
        r = client.post("/my-requests/cancel-all", follow_redirects=False)
        assert r.status_code == 303
        assert db.query(MembershipRequest).filter_by(user_id=user.id).count() == 0

    def test_cancel_other_users_request_ignored(self, client, db):
        owner = _user(db, email="owner@example.com")
        other = _user(db, email="other@example.com")
        self._login(client, other)
        g = svc.create_group(db, name="G", slug="g")
        req = svc.create_membership_request(db, user_id=owner.id, group_id=g.id)
        client.post(f"/my-requests/{req.id}/cancel", follow_redirects=False)
        assert db.query(MembershipRequest).filter_by(id=req.id).first() is not None


# ── HTML: assign speltak (group detail) ───────────────────────────────────────

class TestAssignSpeltak:
    def _login(self, client, user):
        from insigne.auth import create_access_token
        token, _ = create_access_token(user.id)
        client.cookies.set("access_token", token)

    def test_assign_speltak_adds_membership(self, client, db):
        leider = _user(db, email="leider@example.com")
        scout = _user(db, email="scout@example.com")
        g = svc.create_group(db, name="G", slug="g", created_by_id=leider.id)
        s = svc.create_speltak(db, group_id=g.id, name="S", slug="s")
        svc.set_group_role(db, user_id=scout.id, group_id=g.id, role="member")
        self._login(client, leider)
        r = client.post(
            f"/groups/{g.slug}/members/{scout.id}/assign-speltak",
            data={"to_speltak_id": s.id},
            follow_redirects=False,
        )
        assert r.status_code == 303
        speltak_members = svc.list_speltak_members(db, s.id)
        assert any(m.user_id == scout.id for m in speltak_members)

    def test_assign_speltak_requires_manager(self, client, db):
        outsider = _user(db, email="outsider@example.com")
        scout = _user(db, email="scout@example.com")
        g = svc.create_group(db, name="G", slug="g")
        s = svc.create_speltak(db, group_id=g.id, name="S", slug="s")
        svc.set_group_role(db, user_id=scout.id, group_id=g.id, role="member")
        self._login(client, outsider)
        r = client.post(
            f"/groups/{g.slug}/members/{scout.id}/assign-speltak",
            data={"to_speltak_id": s.id},
            follow_redirects=False,
        )
        assert r.status_code == 303
        assert svc.list_speltak_members(db, s.id) == []

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


# ── Group members ─────────────────────────────────────────────────────────────

class TestGroupMembers:
    def test_list_members(self, client, db):
        token = _full_register(client, db)
        user = db.query(User).filter_by(email="user@example.com").first()
        g = svc.create_group(db, name="G", slug="g", created_by_id=user.id)
        r = client.get(f"/api/groups/{g.id}/members", headers=_auth(token))
        assert r.status_code == 200
        assert any(m["user_id"] == user.id for m in r.json())

    def test_list_members_requires_manager(self, client, db):
        token = _full_register(client, db)
        g = svc.create_group(db, name="G", slug="g")
        r = client.get(f"/api/groups/{g.id}/members", headers=_auth(token))
        assert r.status_code == 403

    def test_list_pending_members(self, client, db):
        token = _full_register(client, db)
        user = db.query(User).filter_by(email="user@example.com").first()
        g = svc.create_group(db, name="G", slug="g", created_by_id=user.id)
        invitee = User(email="inv@example.com", name="Inv", status="active", password_hash="x")
        db.add(invitee)
        db.commit()
        svc.set_group_role(db, user_id=invitee.id, group_id=g.id, role="member")
        from insigne.models import GroupMembership
        db.query(GroupMembership).filter_by(user_id=invitee.id).update({"approved": False})
        db.commit()
        r = client.get(f"/api/groups/{g.id}/members/pending", headers=_auth(token))
        assert r.status_code == 200
        assert any(m["user_id"] == invitee.id for m in r.json())

    def test_withdraw_group_invite(self, client, db):
        token = _full_register(client, db)
        user = db.query(User).filter_by(email="user@example.com").first()
        g = svc.create_group(db, name="G", slug="g", created_by_id=user.id)
        invitee = User(email="inv@example.com", name="Inv", status="active", password_hash="x")
        db.add(invitee)
        db.commit()
        svc.set_group_role(db, user_id=invitee.id, group_id=g.id, role="member")
        from insigne.models import GroupMembership
        db.query(GroupMembership).filter_by(user_id=invitee.id).update({"approved": False})
        db.commit()
        r = client.post(f"/api/groups/{g.id}/members/{invitee.id}/withdraw", headers=_auth(token))
        assert r.status_code == 204
        m = db.query(GroupMembership).filter_by(user_id=invitee.id).first()
        assert m.withdrawn is True

    def test_dismiss_group_invite(self, client, db):
        token_invitee = _full_register(client, db, email="inv@example.com", name="Inv")
        invitee = db.query(User).filter_by(email="inv@example.com").first()
        g = svc.create_group(db, name="G", slug="g")
        svc.set_group_role(db, user_id=invitee.id, group_id=g.id, role="member")
        from insigne.models import GroupMembership
        db.query(GroupMembership).filter_by(user_id=invitee.id).update(
            {"approved": False, "withdrawn": True}
        )
        db.commit()
        r = client.post(f"/api/groups/{g.id}/members/{invitee.id}/dismiss",
                        headers=_auth(token_invitee))
        assert r.status_code == 204
        assert db.query(GroupMembership).filter_by(user_id=invitee.id).first() is None

    def test_accept_group_invite(self, client, db):
        token_invitee = _full_register(client, db, email="inv@example.com", name="Inv")
        invitee = db.query(User).filter_by(email="inv@example.com").first()
        g = svc.create_group(db, name="G", slug="g")
        svc.set_group_role(db, user_id=invitee.id, group_id=g.id, role="member")
        from insigne.models import GroupMembership
        db.query(GroupMembership).filter_by(user_id=invitee.id).update({"approved": False})
        db.commit()
        r = client.post(f"/api/groups/{g.id}/members/{invitee.id}/accept",
                        headers=_auth(token_invitee))
        assert r.status_code == 204
        m = db.query(GroupMembership).filter_by(user_id=invitee.id).first()
        assert m.approved is True

    def test_deny_group_invite(self, client, db):
        token_invitee = _full_register(client, db, email="inv@example.com", name="Inv")
        invitee = db.query(User).filter_by(email="inv@example.com").first()
        g = svc.create_group(db, name="G", slug="g")
        svc.set_group_role(db, user_id=invitee.id, group_id=g.id, role="member")
        from insigne.models import GroupMembership
        db.query(GroupMembership).filter_by(user_id=invitee.id).update({"approved": False})
        db.commit()
        r = client.post(f"/api/groups/{g.id}/members/{invitee.id}/deny",
                        headers=_auth(token_invitee))
        assert r.status_code == 204
        assert db.query(GroupMembership).filter_by(user_id=invitee.id).first() is None


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
        assert r.json()["peer_signoff"] is False

    def test_create_speltak_with_peer_signoff(self, client, db):
        token = _full_register(client, db)
        user = db.query(User).filter_by(email="user@example.com").first()
        g = svc.create_group(db, name="G", slug="g", created_by_id=user.id)
        r = client.post(f"/api/groups/{g.id}/speltakken",
                        json={"name": "Rovers", "slug": "rovers", "peer_signoff": True},
                        headers=_auth(token))
        assert r.status_code == 201
        assert r.json()["peer_signoff"] is True

    def test_update_speltak_peer_signoff(self, client, db):
        token = _full_register(client, db)
        user = db.query(User).filter_by(email="user@example.com").first()
        g = svc.create_group(db, name="G", slug="g", created_by_id=user.id)
        s = svc.create_speltak(db, group_id=g.id, name="S", slug="s")
        r = client.put(f"/api/groups/{g.id}/speltakken/{s.id}",
                       json={"name": "S", "slug": "s", "peer_signoff": True},
                       headers=_auth(token))
        assert r.status_code == 200
        assert r.json()["peer_signoff"] is True

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

    def test_list_speltak_members(self, client, db):
        token = _full_register(client, db)
        user = db.query(User).filter_by(email="user@example.com").first()
        g = svc.create_group(db, name="G", slug="g", created_by_id=user.id)
        s = svc.create_speltak(db, group_id=g.id, name="S", slug="s")
        svc.set_speltak_role(db, user_id=user.id, speltak_id=s.id, role="speltakleider")
        r = client.get(f"/api/groups/{g.id}/speltakken/{s.id}/members", headers=_auth(token))
        assert r.status_code == 200
        assert any(m["user_id"] == user.id for m in r.json())

    def test_list_pending_speltak_members(self, client, db):
        token = _full_register(client, db)
        user = db.query(User).filter_by(email="user@example.com").first()
        g = svc.create_group(db, name="G", slug="g", created_by_id=user.id)
        s = svc.create_speltak(db, group_id=g.id, name="S", slug="s")
        svc.set_speltak_role(db, user_id=user.id, speltak_id=s.id, role="speltakleider")
        invitee = User(email="inv@example.com", name="Inv", status="active", password_hash="x")
        db.add(invitee)
        db.commit()
        svc.set_speltak_role(db, user_id=invitee.id, speltak_id=s.id, role="scout")
        from insigne.models import SpeltakMembership
        db.query(SpeltakMembership).filter_by(user_id=invitee.id).update({"approved": False})
        db.commit()
        r = client.get(f"/api/groups/{g.id}/speltakken/{s.id}/members/pending",
                       headers=_auth(token))
        assert r.status_code == 200
        assert any(m["user_id"] == invitee.id for m in r.json())

    def test_withdraw_speltak_invite(self, client, db):
        token = _full_register(client, db)
        user = db.query(User).filter_by(email="user@example.com").first()
        g = svc.create_group(db, name="G", slug="g", created_by_id=user.id)
        s = svc.create_speltak(db, group_id=g.id, name="S", slug="s")
        svc.set_speltak_role(db, user_id=user.id, speltak_id=s.id, role="speltakleider")
        invitee = User(email="inv@example.com", name="Inv", status="active", password_hash="x")
        db.add(invitee)
        db.commit()
        svc.set_speltak_role(db, user_id=invitee.id, speltak_id=s.id, role="scout")
        from insigne.models import SpeltakMembership
        db.query(SpeltakMembership).filter_by(user_id=invitee.id).update({"approved": False})
        db.commit()
        r = client.post(
            f"/api/groups/{g.id}/speltakken/{s.id}/members/{invitee.id}/withdraw",
            headers=_auth(token),
        )
        assert r.status_code == 204
        m = db.query(SpeltakMembership).filter_by(user_id=invitee.id).first()
        assert m.withdrawn is True

    def test_accept_speltak_invite(self, client, db):
        token_invitee = _full_register(client, db, email="inv@example.com", name="Inv")
        invitee = db.query(User).filter_by(email="inv@example.com").first()
        g = svc.create_group(db, name="G", slug="g")
        s = svc.create_speltak(db, group_id=g.id, name="S", slug="s")
        svc.set_speltak_role(db, user_id=invitee.id, speltak_id=s.id, role="scout")
        from insigne.models import SpeltakMembership
        db.query(SpeltakMembership).filter_by(user_id=invitee.id).update({"approved": False})
        db.commit()
        r = client.post(
            f"/api/groups/{g.id}/speltakken/{s.id}/members/{invitee.id}/accept",
            headers=_auth(token_invitee),
        )
        assert r.status_code == 204
        m = db.query(SpeltakMembership).filter_by(user_id=invitee.id).first()
        assert m.approved is True

    def test_deny_speltak_invite(self, client, db):
        token_invitee = _full_register(client, db, email="inv@example.com", name="Inv")
        invitee = db.query(User).filter_by(email="inv@example.com").first()
        g = svc.create_group(db, name="G", slug="g")
        s = svc.create_speltak(db, group_id=g.id, name="S", slug="s")
        svc.set_speltak_role(db, user_id=invitee.id, speltak_id=s.id, role="scout")
        from insigne.models import SpeltakMembership
        db.query(SpeltakMembership).filter_by(user_id=invitee.id).update({"approved": False})
        db.commit()
        r = client.post(
            f"/api/groups/{g.id}/speltakken/{s.id}/members/{invitee.id}/deny",
            headers=_auth(token_invitee),
        )
        assert r.status_code == 204
        assert db.query(SpeltakMembership).filter_by(user_id=invitee.id).first() is None

    def test_dismiss_speltak_invite(self, client, db):
        token_invitee = _full_register(client, db, email="inv@example.com", name="Inv")
        invitee = db.query(User).filter_by(email="inv@example.com").first()
        g = svc.create_group(db, name="G", slug="g")
        s = svc.create_speltak(db, group_id=g.id, name="S", slug="s")
        svc.set_speltak_role(db, user_id=invitee.id, speltak_id=s.id, role="scout")
        from insigne.models import SpeltakMembership
        db.query(SpeltakMembership).filter_by(user_id=invitee.id).update(
            {"approved": False, "withdrawn": True}
        )
        db.commit()
        r = client.post(
            f"/api/groups/{g.id}/speltakken/{s.id}/members/{invitee.id}/dismiss",
            headers=_auth(token_invitee),
        )
        assert r.status_code == 204
        assert db.query(SpeltakMembership).filter_by(user_id=invitee.id).first() is None

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

    def test_attach_email_to_scout_unknown_email(self, client, db):
        token = _full_register(client, db)
        user = db.query(User).filter_by(email="user@example.com").first()
        g = svc.create_group(db, name="G", slug="g", created_by_id=user.id)
        s = svc.create_speltak(db, group_id=g.id, name="S", slug="s")
        svc.set_speltak_role(db, user_id=user.id, speltak_id=s.id, role="speltakleider")
        scout = svc.create_emailless_scout(db, name="Piet", created_by_id=user.id)
        svc.set_speltak_role(db, user_id=scout.id, speltak_id=s.id, role="scout")
        r = client.post(
            f"/api/groups/{g.id}/speltakken/{s.id}/members/{scout.id}/set-email",
            json={"email": "piet@example.com"},
            headers=_auth(token),
        )
        assert r.status_code == 204
        db.refresh(scout)
        assert scout.email == "piet@example.com"
        assert scout.status == "pending"

    def test_attach_email_conflict_returns_409(self, client, db):
        token = _full_register(client, db)
        user = db.query(User).filter_by(email="user@example.com").first()
        g = svc.create_group(db, name="G", slug="g", created_by_id=user.id)
        s = svc.create_speltak(db, group_id=g.id, name="S", slug="s")
        svc.set_speltak_role(db, user_id=user.id, speltak_id=s.id, role="speltakleider")
        pending = User(email="pending@example.com", name="P", status="pending")
        db.add(pending)
        db.commit()
        scout = svc.create_emailless_scout(db, name="Piet", created_by_id=user.id)
        svc.set_speltak_role(db, user_id=scout.id, speltak_id=s.id, role="scout")
        r = client.post(
            f"/api/groups/{g.id}/speltakken/{s.id}/members/{scout.id}/set-email",
            json={"email": "pending@example.com"},
            headers=_auth(token),
        )
        assert r.status_code == 409


# ── GET /api/invitations/me ───────────────────────────────────────────────────

class TestMyInvitations:
    def test_returns_pending_invites(self, client, db):
        token = _full_register(client, db, email="inv@example.com", name="Inv")
        invitee = db.query(User).filter_by(email="inv@example.com").first()
        g = svc.create_group(db, name="G", slug="g")
        s = svc.create_speltak(db, group_id=g.id, name="S", slug="s")
        svc.set_group_role(db, user_id=invitee.id, group_id=g.id, role="member")
        svc.set_speltak_role(db, user_id=invitee.id, speltak_id=s.id, role="scout")
        from insigne.models import GroupMembership, SpeltakMembership
        db.query(GroupMembership).filter_by(user_id=invitee.id).update({"approved": False})
        db.query(SpeltakMembership).filter_by(user_id=invitee.id).update({"approved": False})
        db.commit()
        r = client.get("/api/invitations/me", headers=_auth(token))
        assert r.status_code == 200
        data = r.json()
        assert any(i["group_id"] == g.id for i in data["group_invites"])
        assert any(i["speltak_id"] == s.id for i in data["speltak_invites"])

    def test_requires_authentication(self, client, db):
        r = client.get("/api/invitations/me")
        assert r.status_code == 401


# ── GET /api/users/me/memberships ─────────────────────────────────────────────

class TestGetMyMemberships:
    def test_returns_group_and_speltak_memberships(self, client, db):
        token = _full_register(client, db)
        user = db.query(User).filter_by(email="user@example.com").first()
        g = svc.create_group(db, name="G", slug="g", created_by_id=user.id)
        s = svc.create_speltak(db, group_id=g.id, name="S", slug="s")
        svc.set_speltak_role(db, user_id=user.id, speltak_id=s.id, role="scout")
        r = client.get("/api/users/me/memberships", headers=_auth(token))
        assert r.status_code == 200
        data = r.json()
        assert any(m["group_id"] == g.id for m in data["group_memberships"])
        assert any(m["speltak_id"] == s.id for m in data["speltak_memberships"])

    def test_requires_authentication(self, client, db):
        r = client.get("/api/users/me/memberships")
        assert r.status_code == 401


# ── GET /api/users/me/requests ────────────────────────────────────────────────

class TestGetMyRequests:
    def test_returns_own_requests(self, client, db):
        token = _full_register(client, db)
        user = db.query(User).filter_by(email="user@example.com").first()
        g = svc.create_group(db, name="G", slug="g")
        svc.create_membership_request(db, user_id=user.id, group_id=g.id)
        r = client.get("/api/users/me/requests", headers=_auth(token))
        assert r.status_code == 200
        assert len(r.json()) == 1
        assert r.json()[0]["group_id"] == g.id

    def test_requires_authentication(self, client, db):
        r = client.get("/api/users/me/requests")
        assert r.status_code == 401


# ── DELETE /api/users/me/requests/{req_id} ────────────────────────────────────

class TestCancelMyRequestAPI:
    def test_cancel_own_request(self, client, db):
        token = _full_register(client, db)
        user = db.query(User).filter_by(email="user@example.com").first()
        g = svc.create_group(db, name="G", slug="g")
        req = svc.create_membership_request(db, user_id=user.id, group_id=g.id)
        r = client.delete(f"/api/users/me/requests/{req.id}", headers=_auth(token))
        assert r.status_code == 204
        r2 = client.get("/api/users/me/requests", headers=_auth(token))
        assert r2.json() == []

    def test_cancel_all_requests(self, client, db):
        token = _full_register(client, db)
        user = db.query(User).filter_by(email="user@example.com").first()
        g1 = svc.create_group(db, name="G1", slug="g1")
        g2 = svc.create_group(db, name="G2", slug="g2")
        svc.create_membership_request(db, user_id=user.id, group_id=g1.id)
        svc.create_membership_request(db, user_id=user.id, group_id=g2.id)
        r = client.delete("/api/users/me/requests", headers=_auth(token))
        assert r.status_code == 204
        r2 = client.get("/api/users/me/requests", headers=_auth(token))
        assert r2.json() == []

    def test_requires_authentication(self, client, db):
        r = client.delete("/api/users/me/requests/some-id")
        assert r.status_code == 401


# ── GET /api/groups/{group_id}/members/without-speltak ───────────────────────

class TestMembersWithoutSpeltak:
    def test_returns_members_without_speltak(self, client, db):
        token = _full_register(client, db)
        leider = db.query(User).filter_by(email="user@example.com").first()
        g = svc.create_group(db, name="G", slug="g", created_by_id=leider.id)
        scout_user = User(email="scout@example.com", name="Scout", status="active", password_hash="x")
        db.add(scout_user)
        db.commit()
        svc.set_group_role(db, user_id=scout_user.id, group_id=g.id, role="member")
        r = client.get(f"/api/groups/{g.id}/members/without-speltak", headers=_auth(token))
        assert r.status_code == 200
        assert any(m["user_id"] == scout_user.id for m in r.json())

    def test_excludes_speltak_members(self, client, db):
        token = _full_register(client, db)
        leider = db.query(User).filter_by(email="user@example.com").first()
        g = svc.create_group(db, name="G", slug="g", created_by_id=leider.id)
        s = svc.create_speltak(db, group_id=g.id, name="S", slug="s")
        scout_user = User(email="scout@example.com", name="Scout", status="active", password_hash="x")
        db.add(scout_user)
        db.commit()
        svc.set_speltak_role(db, user_id=scout_user.id, speltak_id=s.id, role="scout")
        r = client.get(f"/api/groups/{g.id}/members/without-speltak", headers=_auth(token))
        assert r.status_code == 200
        assert not any(m["user_id"] == scout_user.id for m in r.json())

    def test_requires_manager(self, client, db):
        token = _full_register(client, db)
        g = svc.create_group(db, name="G", slug="g")
        r = client.get(f"/api/groups/{g.id}/members/without-speltak", headers=_auth(token))
        assert r.status_code == 403


# ── GET /api/requests ─────────────────────────────────────────────────────────

class TestAllPendingRequestsAPI:
    def test_returns_pending_for_leader(self, client, db):
        token = _full_register(client, db)
        leider = db.query(User).filter_by(email="user@example.com").first()
        g = svc.create_group(db, name="G", slug="g", created_by_id=leider.id)
        scout_user = User(email="scout@example.com", name="Scout", status="active", password_hash="x")
        db.add(scout_user)
        db.commit()
        svc.create_membership_request(db, user_id=scout_user.id, group_id=g.id)
        r = client.get("/api/requests", headers=_auth(token))
        assert r.status_code == 200
        assert len(r.json()) == 1
        assert r.json()[0]["user_id"] == scout_user.id

    def test_returns_empty_for_non_leader(self, client, db):
        token = _full_register(client, db)
        g = svc.create_group(db, name="G", slug="g")
        scout_user = User(email="scout@example.com", name="Scout", status="active", password_hash="x")
        db.add(scout_user)
        db.commit()
        svc.create_membership_request(db, user_id=scout_user.id, group_id=g.id)
        r = client.get("/api/requests", headers=_auth(token))
        assert r.status_code == 200
        assert r.json() == []

    def test_requires_authentication(self, client, db):
        r = client.get("/api/requests")
        assert r.status_code == 401

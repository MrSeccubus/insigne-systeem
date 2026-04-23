"""Behavioural tests for the HTML group routes (routers/html_groups.py)."""
from insigne import groups as svc
from insigne.auth import create_access_token
from insigne.models import User


def _user(db, email="user@example.com", name="User"):
    u = User(email=email, name=name, status="active", password_hash="x")
    db.add(u)
    db.commit()
    return u


def _login(client, user) -> None:
    token, _ = create_access_token(user.id)
    client.cookies.set("access_token", token)


# ── GET /groups ───────────────────────────────────────────────────────────────

class TestGroupsList:
    def test_returns_200(self, client, db):
        r = client.get("/groups")
        assert r.status_code == 200

    def test_shows_groups_for_groepsleider(self, client, db):
        user = _user(db)
        svc.create_group(db, name="Welpen", slug="welpen", created_by_id=user.id)
        _login(client, user)
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
        _login(client, user)
        r = client.get("/groups/new")
        assert r.status_code == 200


# ── POST /groups/new ──────────────────────────────────────────────────────────

class TestGroupCreate:
    def test_creates_group_and_redirects(self, client, db):
        user = _user(db)
        _login(client, user)
        r = client.post("/groups/new", data={"name": "Groep A"}, follow_redirects=False)
        assert r.status_code == 303
        assert svc.get_group_by_slug(db, "groep-a") is not None

    def test_duplicate_name_auto_deduplicates_slug(self, client, db):
        user = _user(db)
        svc.create_group(db, name="Groep A", slug="groep-a")
        _login(client, user)
        r = client.post("/groups/new", data={"name": "Groep A"}, follow_redirects=False)
        assert r.status_code == 303
        assert svc.get_group_by_slug(db, "groep-a-2") is not None


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
        _login(client, leider)
        r = client.post(f"/groups/g/members/add", data={"email": "new@example.com"},
                        follow_redirects=False)
        assert r.status_code == 303
        members = svc.list_group_members(db, g.id)
        assert any(m.user_id == new_leider.id for m in members)

    def test_check_email_returns_exists_true(self, client, db):
        leider = _user(db)
        _user(db, email="exists@example.com", name="Existing")
        svc.create_group(db, name="G", slug="g", created_by_id=leider.id)
        _login(client, leider)
        r = client.get("/groups/g/members/check-email?email=exists@example.com")
        assert r.status_code == 200
        assert r.json()["exists"] is True

    def test_check_email_returns_exists_false(self, client, db):
        leider = _user(db)
        svc.create_group(db, name="G", slug="g", created_by_id=leider.id)
        _login(client, leider)
        r = client.get("/groups/g/members/check-email?email=nobody@example.com")
        assert r.status_code == 200
        assert r.json()["exists"] is False

    def test_check_email_requires_auth(self, client, db):
        svc.create_group(db, name="G", slug="g")
        r = client.get("/groups/g/members/check-email?email=x@example.com")
        assert r.status_code == 401

    def test_invite_creates_pending_membership(self, client, db):
        from insigne.models import GroupMembership
        leider = _user(db)
        g = svc.create_group(db, name="G", slug="g", created_by_id=leider.id)
        _login(client, leider)
        r = client.post("/groups/g/members/invite", data={"email": "new@example.com"})
        assert r.status_code == 200
        assert "Uitnodiging verstuurd" in r.text
        m = db.query(GroupMembership).filter_by(group_id=g.id).all()
        pending = [x for x in m if not x.approved]
        assert len(pending) == 1
        assert pending[0].role == "groepsleider"

    def test_non_manager_cannot_add(self, client, db):
        other = _user(db)
        svc.create_group(db, name="G", slug="g")
        _login(client, other)
        r = client.post("/groups/g/members/add", data={"email": "x@example.com"},
                        follow_redirects=False)
        assert r.status_code == 303
        assert r.headers["location"] == "/groups"


# ── POST /groups/{slug}/members/{id}/remove ───────────────────────────────────

class TestGroupRemoveMember:
    def test_removes_groepsleider(self, client, db):
        leider = _user(db)
        other = _user(db, email="other@example.com")
        g = svc.create_group(db, name="G", slug="g", created_by_id=leider.id)
        svc.set_group_role(db, user_id=other.id, group_id=g.id, role="groepsleider")
        _login(client, leider)
        r = client.post(f"/groups/g/members/{other.id}/remove", follow_redirects=False)
        assert r.status_code == 303
        members = svc.list_group_members(db, g.id)
        assert not any(m.user_id == other.id for m in members)

    def test_non_manager_cannot_remove(self, client, db):
        leider = _user(db)
        outsider = _user(db, email="outsider@example.com")
        target = _user(db, email="target@example.com")
        g = svc.create_group(db, name="G", slug="g", created_by_id=leider.id)
        svc.set_group_role(db, user_id=target.id, group_id=g.id, role="groepsleider")
        _login(client, outsider)
        r = client.post(f"/groups/g/members/{target.id}/remove", follow_redirects=False)
        assert r.status_code == 303
        members = svc.list_group_members(db, g.id)
        assert any(m.user_id == target.id for m in members)


# ── Accept speltak invite with/without merge ──────────────────────────────────

def _scout_user(db, group_id, speltak_id):
    """Emailless scout with approved speltak membership."""
    from insigne.models import GroupMembership, SpeltakMembership
    scout = User(name="Scout", status="active")
    db.add(scout)
    db.flush()
    db.add(SpeltakMembership(user_id=scout.id, speltak_id=speltak_id, role="scout", approved=True))
    db.add(GroupMembership(user_id=scout.id, group_id=group_id, role="member", approved=True))
    db.commit()
    return scout


def _progress(db, user_id, badge_slug="b", level_index=0, step_index=0, status="work_done"):
    from insigne.models import ProgressEntry
    e = ProgressEntry(user_id=user_id, badge_slug=badge_slug,
                      level_index=level_index, step_index=step_index, status=status)
    db.add(e)
    db.commit()
    return e


class TestAcceptSpeltakInviteWithMerge:
    def test_merges_progress_and_approves(self, client, db):
        from insigne.models import ProgressEntry, SpeltakMembership
        leader = _user(db, email="leader@example.com")
        g = svc.create_group(db, name="G", slug="g", created_by_id=leader.id)
        s = svc.create_speltak(db, group_id=g.id, name="S", slug="s")
        scout = _scout_user(db, g.id, s.id)
        existing = _user(db, email="ex@example.com", name="Existing")
        _progress(db, scout.id, status="work_done")
        svc.attach_email_to_scout(db, scout_user_id=scout.id, email="ex@example.com",
                                  invited_by_id=leader.id, speltak=s)
        _login(client, existing)
        r = client.post(f"/invitations/speltak/{s.id}/accept-with-merge",
                        follow_redirects=False)
        assert r.status_code == 303
        entries = db.query(ProgressEntry).filter_by(user_id=existing.id).all()
        assert any(e.status == "work_done" for e in entries)
        m = db.query(SpeltakMembership).filter_by(user_id=existing.id, speltak_id=s.id).first()
        assert m.approved is True

    def test_requires_login(self, client, db):
        r = client.post("/invitations/speltak/fake-id/accept-with-merge",
                        follow_redirects=False)
        assert r.status_code == 303
        assert "/login" in r.headers["location"]


class TestAcceptSpeltakInviteWithoutMerge:
    def test_discards_scout_progress_and_approves(self, client, db):
        from insigne.models import ProgressEntry, SpeltakMembership, User as U
        leader = _user(db, email="leader2@example.com")
        g = svc.create_group(db, name="G2", slug="g2", created_by_id=leader.id)
        s = svc.create_speltak(db, group_id=g.id, name="S2", slug="s2")
        scout = _scout_user(db, g.id, s.id)
        scout_id = scout.id
        existing = _user(db, email="ex2@example.com", name="Existing2")
        _progress(db, scout.id, status="signed_off")
        svc.attach_email_to_scout(db, scout_user_id=scout.id, email="ex2@example.com",
                                  invited_by_id=leader.id, speltak=s)
        _login(client, existing)
        r = client.post(f"/invitations/speltak/{s.id}/accept-without-merge",
                        follow_redirects=False)
        assert r.status_code == 303
        assert db.get(U, scout_id) is None
        entries = db.query(ProgressEntry).filter_by(user_id=existing.id).all()
        assert entries == []
        m = db.query(SpeltakMembership).filter_by(user_id=existing.id, speltak_id=s.id).first()
        assert m.approved is True

    def test_requires_login(self, client, db):
        r = client.post("/invitations/speltak/fake-id/accept-without-merge",
                        follow_redirects=False)
        assert r.status_code == 303
        assert "/login" in r.headers["location"]

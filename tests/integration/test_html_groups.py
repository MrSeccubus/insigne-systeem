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
    def test_unauthenticated_redirects_to_login(self, client, db):
        r = client.get("/groups", follow_redirects=False)
        assert r.status_code == 303
        assert r.headers["location"] == "/login"

    def test_authenticated_returns_200(self, client, db):
        user = _user(db)
        _login(client, user)
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
    def test_unauthenticated_redirects_to_login(self, client, db):
        svc.create_group(db, name="G", slug="g")
        r = client.get("/groups/g", follow_redirects=False)
        assert r.status_code == 303
        assert r.headers["location"] == "/login"

    def test_non_leider_redirected_to_groups(self, client, db):
        outsider = _user(db)
        svc.create_group(db, name="G", slug="g")
        _login(client, outsider)
        r = client.get("/groups/g", follow_redirects=False)
        assert r.status_code == 303
        assert r.headers["location"] == "/groups"

    def test_groepsleider_returns_200(self, client, db):
        user = _user(db)
        svc.create_group(db, name="G", slug="g", created_by_id=user.id)
        _login(client, user)
        r = client.get("/groups/g")
        assert r.status_code == 200

    def test_unknown_slug_redirects(self, client, db):
        user = _user(db)
        _login(client, user)
        r = client.get("/groups/nonexistent", follow_redirects=False)
        assert r.status_code == 303

    def test_shows_groepsleiders(self, client, db):
        user = _user(db)
        svc.create_group(db, name="G", slug="g", created_by_id=user.id)
        _login(client, user)
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

    def test_invite_rejects_invalid_email_inline(self, client, db):
        """Issue #106 — junk in the invite form must produce an inline error
        and must not pollute the users table with a bogus pending row."""
        from insigne.models import GroupMembership, User
        leider = _user(db)
        g = svc.create_group(db, name="G", slug="g", created_by_id=leider.id)
        _login(client, leider)
        users_before = db.query(User).count()
        r = client.post("/groups/g/members/invite", data={"email": "not-an-email"})
        assert r.status_code == 200
        assert "Geef een geldig e-mailadres op." in r.text
        assert db.query(User).count() == users_before
        assert db.query(GroupMembership).filter_by(group_id=g.id, approved=False).count() == 0


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


# ── Helpers for leider progress tests ─────────────────────────────────────────

def _speltakleider(db, group_id, speltak_id, email="leider@example.com"):
    from insigne.models import GroupMembership, SpeltakMembership
    leider = User(email=email, name="Leider", status="active", password_hash="x")
    db.add(leider)
    db.flush()
    db.add(GroupMembership(user_id=leider.id, group_id=group_id, role="member", approved=True))
    db.add(SpeltakMembership(user_id=leider.id, speltak_id=speltak_id, role="speltakleider", approved=True))
    db.commit()
    return leider


# ── GET /my-speltakken ────────────────────────────────────────────────────────

class TestMySpeltakken:
    def test_unauthenticated_redirects(self, client, db):
        r = client.get("/my-speltakken", follow_redirects=False)
        assert r.status_code == 303
        assert "/login" in r.headers["location"]

    def test_single_speltak_redirects_to_progress(self, client, db):
        from insigne import groups as svc
        g = svc.create_group(db, name="G", slug="g")
        s = svc.create_speltak(db, group_id=g.id, name="S", slug="s")
        leider = _speltakleider(db, g.id, s.id)
        _login(client, leider)
        r = client.get("/my-speltakken", follow_redirects=False)
        assert r.status_code == 303
        assert f"/groups/g/speltakken/s/progress" in r.headers["location"]

    def test_multiple_speltakken_shows_list(self, client, db):
        from insigne import groups as svc
        g = svc.create_group(db, name="G", slug="g")
        s1 = svc.create_speltak(db, group_id=g.id, name="S1", slug="s1")
        s2 = svc.create_speltak(db, group_id=g.id, name="S2", slug="s2")
        leider = _speltakleider(db, g.id, s1.id)
        _speltakleider_add(db, leider.id, g.id, s2.id)
        _login(client, leider)
        r = client.get("/my-speltakken")
        assert r.status_code == 200
        assert "S1" in r.text and "S2" in r.text

    def test_groepsleider_without_speltakleider_role_not_in_nav(self, client, db):
        from insigne import groups as svc
        user = _user(db, email="gl@x.com")
        svc.create_group(db, name="G", slug="g", created_by_id=user.id)
        _login(client, user)
        r = client.get("/")
        assert "Mijn speltakken" not in r.text


def _speltakleider_add(db, user_id, group_id, speltak_id):
    from insigne.models import SpeltakMembership
    db.add(SpeltakMembership(user_id=user_id, speltak_id=speltak_id, role="speltakleider", approved=True))
    db.commit()


# ── GET /groups/{slug}/speltakken/{slug} ──────────────────────────────────────

class TestSpeltakDetail:
    def test_unauthenticated_redirects_to_login(self, client, db):
        g = svc.create_group(db, name="G", slug="g")
        svc.create_speltak(db, group_id=g.id, name="S", slug="s")
        r = client.get("/groups/g/speltakken/s", follow_redirects=False)
        assert r.status_code == 303
        assert r.headers["location"] == "/login"

    def test_non_leider_redirected_to_group(self, client, db):
        outsider = _user(db)
        g = svc.create_group(db, name="G", slug="g")
        svc.create_speltak(db, group_id=g.id, name="S", slug="s")
        _login(client, outsider)
        r = client.get("/groups/g/speltakken/s", follow_redirects=False)
        assert r.status_code == 303
        assert r.headers["location"] == "/groups/g"

    def test_speltakleider_returns_200(self, client, db):
        leider = _user(db)
        g = svc.create_group(db, name="G", slug="g")
        s = svc.create_speltak(db, group_id=g.id, name="S", slug="s")
        _speltakleider_add(db, leider.id, g.id, s.id)
        _login(client, leider)
        r = client.get("/groups/g/speltakken/s")
        assert r.status_code == 200


# ── GET /groups/{slug}/speltakken/{slug}/progress ─────────────────────────────

class TestSpeltakProgressPage:
    def _setup(self, db):
        from insigne import groups as svc
        g = svc.create_group(db, name="G", slug="g")
        s = svc.create_speltak(db, group_id=g.id, name="S", slug="s")
        leider = _speltakleider(db, g.id, s.id)
        scout = _scout_user(db, g.id, s.id)
        return g, s, leider, scout

    def test_leider_sees_progress_page(self, client, db):
        g, s, leider, scout = self._setup(db)
        _login(client, leider)
        r = client.get(f"/groups/g/speltakken/s/progress")
        assert r.status_code == 200

    def test_jaarinsigne_links_to_scout_not_user(self, client, db):
        """#143: a jaarinsigne in the speltak overview must link to each scout's
        jaarinsigne (speltak context), not the leader's own /badges page."""
        g, s, leider, scout = self._setup(db)
        _login(client, leider)
        r = client.get("/groups/g/speltakken/s/progress")
        assert r.status_code == 200
        assert 'href="/badges/jaarinsigne_2026"' not in r.text
        assert f"/scouts/{scout.id}/badges/jaarinsigne_2026" in r.text

    def test_jaarinsigne_card_explains_offline_unavailable(self, client, db):
        """The per-scout jaarinsigne pages aren't pre-cached, so offline the
        list is hidden (online-only) and an offline-only note explains why."""
        g, s, leider, scout = self._setup(db)
        _login(client, leider)
        r = client.get("/groups/g/speltakken/s/progress")
        assert 'class="offline-only"' in r.text
        assert "offline niet beschikbaar" in r.text

    def test_scout_cannot_access(self, client, db):
        g, s, leider, scout = self._setup(db)
        _login(client, scout)
        r = client.get("/groups/g/speltakken/s/progress", follow_redirects=False)
        assert r.status_code == 303

    def test_unauthenticated_redirects(self, client, db):
        from insigne import groups as svc
        g = svc.create_group(db, name="G", slug="g")
        svc.create_speltak(db, group_id=g.id, name="S", slug="s")
        r = client.get("/groups/g/speltakken/s/progress", follow_redirects=False)
        assert r.status_code == 303
        assert "/login" in r.headers["location"]

    def test_peer_signoff_shows_no_hx_post(self, client, db):
        from insigne import groups as svc
        g = svc.create_group(db, name="G", slug="g")
        s = svc.create_speltak(db, group_id=g.id, name="S", slug="s", peer_signoff=True)
        leider = _speltakleider(db, g.id, s.id)
        _scout_user(db, g.id, s.id)
        _login(client, leider)
        r = client.get("/groups/g/speltakken/s/progress")
        assert r.status_code == 200
        assert "hx-post" not in r.text


# ── POST …/scouts/{id}/progress/set ──────────────────────────────────────────

class TestSetScoutProgressRoute:
    def _setup(self, db):
        from insigne import groups as svc
        g = svc.create_group(db, name="G", slug="g")
        s = svc.create_speltak(db, group_id=g.id, name="S", slug="s")
        leider = _speltakleider(db, g.id, s.id)
        scout = _scout_user(db, g.id, s.id)
        return g, s, leider, scout

    def _post(self, client, scout_id, status="in_progress", badge_slug="b",
              level_index=0, step_index=0):
        return client.post(
            f"/groups/g/speltakken/s/scouts/{scout_id}/progress/set",
            data={"badge_slug": badge_slug, "level_index": level_index,
                  "step_index": step_index, "status": status},
        )

    def test_set_in_progress_returns_partial(self, client, db):
        g, s, leider, scout = self._setup(db)
        _login(client, leider)
        r = self._post(client, scout.id)
        assert r.status_code == 200
        assert "step-check" in r.text
        assert "in_progress" in r.text

    def test_reset_to_none_deletes_entry(self, client, db):
        from insigne.models import ProgressEntry
        g, s, leider, scout = self._setup(db)
        _progress(db, scout.id)
        _login(client, leider)
        r = self._post(client, scout.id, status="none")
        assert r.status_code == 200
        assert db.query(ProgressEntry).filter_by(user_id=scout.id).count() == 0

    def test_self_edit_returns_unchanged_state(self, client, db):
        g, s, leider, scout = self._setup(db)
        _login(client, leider)
        r = self._post(client, leider.id)
        assert r.status_code == 200
        assert "in_progress" not in r.text

    def test_outsider_gets_redirect(self, client, db):
        g, s, leider, scout = self._setup(db)
        outsider = _user(db, email="out@x.com")
        _login(client, outsider)
        r = self._post(client, scout.id)
        assert r.status_code in (200, 403, 404)

    def test_conflict_on_pending_signoff_returns_unchanged(self, client, db):
        from insigne.models import ProgressEntry
        g, s, leider, scout = self._setup(db)
        _progress(db, scout.id, status="pending_signoff")
        _login(client, leider)
        r = self._post(client, scout.id, status="work_done")
        assert r.status_code == 200
        assert db.query(ProgressEntry).filter_by(
            user_id=scout.id, status="pending_signoff"
        ).count() == 1


# ── POST …/favorite-badge ─────────────────────────────────────────────────────

class TestFavoriteBadgeToggle:
    def _setup(self, db):
        from insigne import groups as svc
        g = svc.create_group(db, name="G", slug="g")
        s = svc.create_speltak(db, group_id=g.id, name="S", slug="s")
        leider = _speltakleider(db, g.id, s.id)
        return g, s, leider

    def test_leider_toggles_on(self, client, db):
        from insigne import groups as svc
        g, s, leider = self._setup(db)
        _login(client, leider)
        r = client.post(f"/groups/g/speltakken/s/favorite-badge",
                        data={"badge_slug": "internationaal"})
        assert r.status_code == 200
        assert "★" in r.text
        assert "internationaal" in svc.get_speltak_favorite_slugs(db, s.id)

    def test_leider_toggles_off(self, client, db):
        from insigne import groups as svc
        g, s, leider = self._setup(db)
        svc.toggle_speltak_favorite_badge(db, s.id, "internationaal")
        _login(client, leider)
        r = client.post(f"/groups/g/speltakken/s/favorite-badge",
                        data={"badge_slug": "internationaal"})
        assert r.status_code == 200
        assert "☆" in r.text
        assert "internationaal" not in svc.get_speltak_favorite_slugs(db, s.id)

    def test_scout_cannot_toggle(self, client, db):
        from insigne import groups as svc
        g, s, leider = self._setup(db)
        scout = _scout_user(db, g.id, s.id)
        _login(client, scout)
        r = client.post(f"/groups/g/speltakken/s/favorite-badge",
                        data={"badge_slug": "internationaal"})
        assert r.status_code == 403


# ── GET /groups/{slug}/progress ───────────────────────────────────────────────

class TestGroupProgressPage:
    def test_groepsleider_sees_page(self, client, db):
        from insigne import groups as svc
        gl = _user(db, email="gl@x.com")
        g = svc.create_group(db, name="G", slug="g", created_by_id=gl.id)
        svc.create_speltak(db, group_id=g.id, name="S", slug="s")
        _login(client, gl)
        r = client.get("/groups/g/progress")
        assert r.status_code == 200
        assert "S" in r.text

    def test_speltakleider_redirected(self, client, db):
        from insigne import groups as svc
        g = svc.create_group(db, name="G", slug="g")
        s = svc.create_speltak(db, group_id=g.id, name="S", slug="s")
        leider = _speltakleider(db, g.id, s.id)
        _login(client, leider)
        r = client.get("/groups/g/progress", follow_redirects=False)
        assert r.status_code == 303

    def test_unauthenticated_redirects(self, client, db):
        from insigne import groups as svc
        svc.create_group(db, name="G", slug="g")
        r = client.get("/groups/g/progress", follow_redirects=False)
        assert r.status_code == 303
        assert "/login" in r.headers["location"]


class TestSpeltakSetMemberEmailTakeoverGuard:
    """The set-email endpoint must not let a leader overwrite an arbitrary
    user's email (account takeover). See SECURITY-REVIEW / fix.
    """

    def test_cannot_hijack_user_with_existing_email(self, client, db):
        leader = _user(db, email="leader@example.com")
        victim = _user(db, email="victim@example.com", name="Victim")
        g = svc.create_group(db, name="G", slug="g", created_by_id=leader.id)
        s = svc.create_speltak(db, group_id=g.id, name="S", slug="s")
        _login(client, leader)

        r = client.post(
            f"/groups/g/speltakken/s/members/{victim.id}/set-email",
            data={"email": "attacker@example.com"}, follow_redirects=False,
        )
        # Handler renders an error page (200), does not mutate the victim.
        assert r.status_code == 200
        db.refresh(victim)
        assert victim.email == "victim@example.com"
        assert victim.status == "active"

    def test_cannot_target_scout_from_another_speltak(self, client, db):
        leader = _user(db, email="leader@example.com")
        g = svc.create_group(db, name="G", slug="g", created_by_id=leader.id)
        s1 = svc.create_speltak(db, group_id=g.id, name="S1", slug="s1")
        s2 = svc.create_speltak(db, group_id=g.id, name="S2", slug="s2")
        scout = _scout_user(db, g.id, s2.id)  # member of s2, not s1
        _login(client, leader)

        r = client.post(
            f"/groups/g/speltakken/s1/members/{scout.id}/set-email",
            data={"email": "new@example.com"}, follow_redirects=False,
        )
        assert r.status_code == 200
        db.refresh(scout)
        assert scout.email is None

    def test_legit_emailless_member_still_works(self, client, db):
        leader = _user(db, email="leader@example.com")
        g = svc.create_group(db, name="G", slug="g", created_by_id=leader.id)
        s = svc.create_speltak(db, group_id=g.id, name="S", slug="s")
        scout = _scout_user(db, g.id, s.id)
        _login(client, leader)

        r = client.post(
            f"/groups/g/speltakken/s/members/{scout.id}/set-email",
            data={"email": "scout@example.com"}, follow_redirects=False,
        )
        assert r.status_code == 200
        db.refresh(scout)
        assert scout.email == "scout@example.com"
        assert scout.status == "pending"


class TestMembershipRequestApprovalAuthz:
    """A membership request may only be approved/rejected by a manager of its
    group. Guards against self-approval into an arbitrary group.
    """

    def test_self_approval_blocked(self, client, db):
        from insigne.models import MembershipRequest
        scout = _user(db, email="scout@example.com")
        g = svc.create_group(db, name="G", slug="g")  # scout is not a leader
        req = svc.create_membership_request(db, user_id=scout.id, group_id=g.id)
        _login(client, scout)

        r = client.post(f"/requests/{req.id}/approve", follow_redirects=False)
        assert r.status_code == 303  # handler swallows the ValueError, redirects back
        # Nothing mutated: request still pending, no membership created.
        assert db.query(MembershipRequest).filter_by(id=req.id).first().status == "pending"
        assert svc.get_group_role(db, scout.id, g.id) is None

    def test_other_user_cannot_reject(self, client, db):
        from insigne.models import MembershipRequest
        outsider = _user(db, email="outsider@example.com")
        scout = _user(db, email="scout@example.com")
        g = svc.create_group(db, name="G", slug="g")
        req = svc.create_membership_request(db, user_id=scout.id, group_id=g.id)
        _login(client, outsider)

        r = client.post(f"/requests/{req.id}/reject", follow_redirects=False)
        assert r.status_code == 303
        assert db.query(MembershipRequest).filter_by(id=req.id).first().status == "pending"

    def test_leader_can_approve(self, client, db):
        leider = _user(db, email="leider@example.com")
        scout = _user(db, email="scout@example.com")
        g = svc.create_group(db, name="G", slug="g", created_by_id=leider.id)
        req = svc.create_membership_request(db, user_id=scout.id, group_id=g.id)
        _login(client, leider)

        r = client.post(f"/requests/{req.id}/approve", follow_redirects=False)
        assert r.status_code == 303
        assert svc.get_group_role(db, scout.id, g.id) == "member"

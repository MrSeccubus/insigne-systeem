"""Behavioural tests for the HTML badge/progress routes (routers/html_badges.py).

We test status codes, redirects, HX-Trigger headers, and error text —
not exact HTML markup.
"""
from unittest.mock import patch

from insigne import users as user_svc
from insigne.auth import create_access_token
from insigne.models import ConfirmationToken, ProgressEntry, SignoffRequest, User


# ── helpers ───────────────────────────────────────────────────────────────────

_BADGE = "vredeslicht"
_LEVEL = 0
_STEP = 0


def _active_user(db, email="scout@example.com", name="Scout Jan"):
    user = User(email=email, name=name, status="active", password_hash="x")
    db.add(user)
    db.commit()
    return user


def _entry(db, user, *, status="in_progress", badge_slug=_BADGE, level_index=_LEVEL, step_index=_STEP):
    e = ProgressEntry(
        user_id=user.id,
        badge_slug=badge_slug,
        level_index=level_index,
        step_index=step_index,
        status=status,
    )
    db.add(e)
    db.commit()
    return e


def _set_auth(client, user):
    token, _ = create_access_token(user.id)
    client.cookies.set("access_token", token)


# ── badge detail ──────────────────────────────────────────────────────────────

class TestBadgeDetail:
    def test_known_badge_returns_200(self, client, db):
        r = client.get(f"/badges/{_BADGE}")
        assert r.status_code == 200

    def test_unknown_badge_redirects_to_home(self, client, db):
        r = client.get("/badges/doesnotexist", follow_redirects=False)
        assert r.status_code == 303
        assert r.headers["location"] == "/"

    def test_niveau_filter_returns_200(self, client, db):
        r = client.get(f"/badges/{_BADGE}?niveau=1")
        assert r.status_code == 200


# ── log step ──────────────────────────────────────────────────────────────────

class TestLogStep:
    def test_without_auth_redirects_to_login(self, client, db):
        r = client.post(
            f"/badges/{_BADGE}/log",
            data={"level_index": 0, "step_index": 0, "status": "in_progress"},
            follow_redirects=False,
        )
        assert r.status_code == 303
        assert "/login" in r.headers["location"]

    def test_with_auth_returns_step_card(self, client, db):
        user = _active_user(db)
        _set_auth(client, user)
        r = client.post(
            f"/badges/{_BADGE}/log",
            data={"level_index": _LEVEL, "step_index": _STEP, "status": "in_progress"},
        )
        assert r.status_code == 200
        assert "HX-Trigger" in r.headers

    def test_sets_hx_trigger_niveau_updated(self, client, db):
        user = _active_user(db)
        _set_auth(client, user)
        r = client.post(
            f"/badges/{_BADGE}/log",
            data={"level_index": _LEVEL, "step_index": _STEP, "status": "work_done"},
        )
        assert r.headers.get("HX-Trigger") == "niveau-updated"

    def test_out_of_bounds_level_index_redirects_to_home(self, client, db):
        user = _active_user(db)
        _set_auth(client, user)
        r = client.post(
            f"/badges/{_BADGE}/log",
            data={"level_index": 999, "step_index": _STEP, "status": "in_progress"},
            follow_redirects=False,
        )
        assert r.status_code == 303
        assert r.headers["location"] == "/"

    def test_out_of_bounds_step_index_redirects_to_home(self, client, db):
        user = _active_user(db)
        _set_auth(client, user)
        r = client.post(
            f"/badges/{_BADGE}/log",
            data={"level_index": _LEVEL, "step_index": 999, "status": "in_progress"},
            follow_redirects=False,
        )
        assert r.status_code == 303
        assert r.headers["location"] == "/"

    def test_negative_level_index_redirects_to_home(self, client, db):
        user = _active_user(db)
        _set_auth(client, user)
        r = client.post(
            f"/badges/{_BADGE}/log",
            data={"level_index": -1, "step_index": _STEP, "status": "in_progress"},
            follow_redirects=False,
        )
        assert r.status_code == 303
        assert r.headers["location"] == "/"


# ── request signoff ───────────────────────────────────────────────────────────

class TestRequestSignoff:
    def test_without_auth_redirects_to_login(self, client, db):
        r = client.post("/progress/fake-id/request-signoff",
                        data={"mentor_email": "m@example.com"},
                        follow_redirects=False)
        assert r.status_code == 303
        assert "/login" in r.headers["location"]

    def test_unknown_entry_redirects_to_home(self, client, db):
        user = _active_user(db)
        _set_auth(client, user)
        r = client.post("/progress/nonexistent/request-signoff",
                        data={"mentor_email": "m@example.com"},
                        follow_redirects=False)
        assert r.status_code == 303
        assert r.headers["location"] == "/"

    def test_successful_invite_returns_step_card(self, client, db):
        scout = _active_user(db)
        _set_auth(client, scout)
        e = _entry(db, scout, status="work_done")
        with patch("insigne.email.send"):
            r = client.post(f"/progress/{e.id}/request-signoff",
                            data={"mentor_email": "mentor@example.com", "notes": ""})
        assert r.status_code == 200
        db.refresh(e)
        assert e.status == "pending_signoff"

    def test_duplicate_mentor_returns_error_text(self, client, db):
        scout = _active_user(db)
        mentor = _active_user(db, "mentor@example.com", "Leider")
        _set_auth(client, scout)
        e = _entry(db, scout, status="work_done")
        # First invite
        with patch("insigne.email.send"):
            client.post(f"/progress/{e.id}/request-signoff",
                        data={"mentor_email": "mentor@example.com"})
        # Second invite same mentor
        with patch("insigne.email.send"):
            r = client.post(f"/progress/{e.id}/request-signoff",
                            data={"mentor_email": "mentor@example.com"})
        assert r.status_code == 200
        assert "uitgenodigd" in r.text.lower()

    def test_entry_not_work_done_returns_error_text(self, client, db):
        scout = _active_user(db)
        _set_auth(client, scout)
        e = _entry(db, scout, status="in_progress")
        with patch("insigne.email.send"):
            r = client.post(f"/progress/{e.id}/request-signoff",
                            data={"mentor_email": "mentor@example.com"})
        assert r.status_code == 200
        assert "klaar" in r.text.lower()


# ── cancel signoff ────────────────────────────────────────────────────────────

class TestCancelSignoff:
    def test_without_auth_redirects_to_login(self, client, db):
        r = client.post("/progress/fake/cancel-signoff", follow_redirects=False)
        assert r.status_code == 303
        assert "/login" in r.headers["location"]

    def test_cancels_and_returns_step_card(self, client, db):
        scout = _active_user(db)
        mentor = _active_user(db, "mentor@example.com")
        _set_auth(client, scout)
        e = _entry(db, scout, status="pending_signoff")
        db.add(SignoffRequest(progress_entry_id=e.id, mentor_id=mentor.id))
        db.commit()
        r = client.post(f"/progress/{e.id}/cancel-signoff")
        assert r.status_code == 200
        db.refresh(e)
        assert e.status == "work_done"


# ── delete progress ───────────────────────────────────────────────────────────

class TestDeleteProgress:
    def test_without_auth_redirects_to_login(self, client, db):
        r = client.post("/progress/fake/delete", follow_redirects=False)
        assert r.status_code == 303

    def test_deletes_entry_returns_empty_step_card(self, client, db):
        scout = _active_user(db)
        _set_auth(client, scout)
        e = _entry(db, scout, status="in_progress")
        r = client.post(f"/progress/{e.id}/delete")
        assert r.status_code == 200
        assert db.query(ProgressEntry).filter_by(id=e.id).first() is None

    def test_unknown_entry_returns_empty_html(self, client, db):
        scout = _active_user(db)
        _set_auth(client, scout)
        r = client.post("/progress/nonexistent/delete")
        assert r.status_code == 200
        assert r.text.strip() == ""


# ── signoff requests (mentor view) ───────────────────────────────────────────

class TestSignoffRequestsCount:
    def test_without_auth_returns_empty(self, client, db):
        r = client.get("/signoff-requests/count")
        assert r.status_code == 200
        assert r.text.strip() == ""

    def test_with_no_requests_returns_empty(self, client, db):
        mentor = _active_user(db, "mentor@example.com")
        _set_auth(client, mentor)
        r = client.get("/signoff-requests/count")
        assert r.status_code == 200
        assert r.text.strip() == ""

    def test_with_pending_request_returns_count(self, client, db):
        scout = _active_user(db)
        mentor = _active_user(db, "mentor@example.com")
        _set_auth(client, mentor)
        e = _entry(db, scout, status="pending_signoff")
        db.add(SignoffRequest(progress_entry_id=e.id, mentor_id=mentor.id))
        db.commit()
        r = client.get("/signoff-requests/count")
        assert r.status_code == 200
        assert "1" in r.text


class TestSignoffRequestsPage:
    def test_without_auth_redirects_to_login(self, client, db):
        r = client.get("/signoff-requests", follow_redirects=False)
        assert r.status_code == 303
        assert "/login" in r.headers["location"]

    def test_with_auth_returns_200(self, client, db):
        mentor = _active_user(db, "mentor@example.com")
        _set_auth(client, mentor)
        r = client.get("/signoff-requests")
        assert r.status_code == 200

    def test_lists_pending_request(self, client, db):
        scout = _active_user(db)
        mentor = _active_user(db, "mentor@example.com")
        _set_auth(client, mentor)
        e = _entry(db, scout, status="pending_signoff")
        db.add(SignoffRequest(progress_entry_id=e.id, mentor_id=mentor.id))
        db.commit()
        r = client.get("/signoff-requests")
        assert r.status_code == 200
        assert scout.name in r.text


# ── confirm signoff ───────────────────────────────────────────────────────────

class TestConfirmSignoff:
    def _setup(self, db):
        scout = _active_user(db)
        mentor = _active_user(db, "mentor@example.com", "Leider Piet")
        e = _entry(db, scout, status="pending_signoff")
        db.add(SignoffRequest(progress_entry_id=e.id, mentor_id=mentor.id))
        db.commit()
        return scout, mentor, e

    def test_without_auth_redirects_to_login(self, client, db):
        r = client.post("/progress/fake/confirm-signoff", follow_redirects=False)
        assert r.status_code == 303
        assert "/login" in r.headers["location"]

    def test_confirm_marks_entry_signed_off(self, client, db):
        scout, mentor, e = self._setup(db)
        _set_auth(client, mentor)
        with patch("insigne.email.send"):
            r = client.post(f"/progress/{e.id}/confirm-signoff", data={"comment": ""})
        assert r.status_code == 200
        db.refresh(e)
        assert e.status == "signed_off"

    def test_wrong_mentor_returns_error(self, client, db):
        scout, mentor, e = self._setup(db)
        uninvited = _active_user(db, "uninvited@example.com")
        _set_auth(client, uninvited)
        with patch("insigne.email.send"):
            r = client.post(f"/progress/{e.id}/confirm-signoff", data={"comment": ""})
        assert r.status_code == 200
        assert "aftekenen" in r.text.lower()

    def test_already_confirmed_returns_error(self, client, db):
        scout, mentor, e = self._setup(db)
        e.status = "signed_off"
        e.signed_off_by_id = mentor.id
        db.commit()
        _set_auth(client, mentor)
        with patch("insigne.email.send"):
            r = client.post(f"/progress/{e.id}/confirm-signoff", data={"comment": ""})
        assert r.status_code == 200
        assert "afgetekend" in r.text.lower()


# ── reject signoff ────────────────────────────────────────────────────────────

class TestRejectSignoff:
    def _setup(self, db):
        scout = _active_user(db)
        mentor = _active_user(db, "mentor@example.com", "Leider Piet")
        e = _entry(db, scout, status="pending_signoff")
        db.add(SignoffRequest(progress_entry_id=e.id, mentor_id=mentor.id))
        db.commit()
        return scout, mentor, e

    def test_without_auth_redirects_to_login(self, client, db):
        r = client.post("/progress/fake/reject-signoff", follow_redirects=False)
        assert r.status_code == 303
        assert "/login" in r.headers["location"]

    def test_reject_reverts_entry_to_work_done(self, client, db):
        scout, mentor, e = self._setup(db)
        _set_auth(client, mentor)
        with patch("insigne.email.send"):
            r = client.post(f"/progress/{e.id}/reject-signoff",
                            data={"message": "Nog niet klaar"})
        assert r.status_code == 200
        db.refresh(e)
        assert e.status == "work_done"

    def test_wrong_mentor_returns_error(self, client, db):
        scout, mentor, e = self._setup(db)
        uninvited = _active_user(db, "uninvited@example.com")
        _set_auth(client, uninvited)
        with patch("insigne.email.send"):
            r = client.post(f"/progress/{e.id}/reject-signoff",
                            data={"message": "Nope"})
        assert r.status_code == 200
        assert "afwijzen" in r.text.lower()


# ── niveau checks partial ─────────────────────────────────────────────────────

class TestRibbon:
    def _sign_off_all_eisen(self, db, user, badge_slug=_BADGE, step_index=0):
        """Sign off all 5 eisen at a given niveau (step_index) for a badge."""
        for level_index in range(5):
            e = ProgressEntry(
                user_id=user.id,
                badge_slug=badge_slug,
                level_index=level_index,
                step_index=step_index,
                status="signed_off",
            )
            db.add(e)
        db.commit()

    def test_ribbon_hidden_when_nothing_signed_off(self, client, db):
        user = _active_user(db)
        _set_auth(client, user)
        r = client.get("/")
        assert "ribbon" not in r.text.lower() or "Jouw insignes" not in r.text

    def test_ribbon_shown_when_niveau_fully_signed_off(self, client, db):
        user = _active_user(db)
        _set_auth(client, user)
        self._sign_off_all_eisen(db, user)
        r = client.get("/")
        assert "Jouw insignes" in r.text

    def test_ribbon_links_to_badge_at_correct_niveau(self, client, db):
        user = _active_user(db)
        _set_auth(client, user)
        self._sign_off_all_eisen(db, user, step_index=1)  # niveau 2
        r = client.get("/")
        assert f"/badges/{_BADGE}?niveau=2" in r.text

    def test_partial_niveau_not_in_ribbon(self, client, db):
        user = _active_user(db)
        _set_auth(client, user)
        # Sign off only 4 of 5 eisen at niveau 0
        for level_index in range(4):
            db.add(ProgressEntry(user_id=user.id, badge_slug=_BADGE,
                                 level_index=level_index, step_index=0, status="signed_off"))
        db.commit()
        r = client.get("/")
        assert "Jouw insignes" not in r.text

    def test_ribbon_not_shown_for_anonymous(self, client, db):
        r = client.get("/")
        assert "Jouw insignes" not in r.text


class TestNiveauChecks:
    def test_unauthenticated_returns_401(self, client, db):
        r = client.get(f"/badges/{_BADGE}/niveau-checks/0")
        assert r.status_code == 401

    def test_unknown_badge_returns_empty_when_authenticated(self, client, db):
        user = _active_user(db)
        _set_auth(client, user)
        r = client.get("/badges/doesnotexist/niveau-checks/0")
        assert r.status_code == 200
        assert r.text.strip() == ""

    def test_known_badge_returns_200_when_authenticated(self, client, db):
        user = _active_user(db)
        _set_auth(client, user)
        r = client.get(f"/badges/{_BADGE}/niveau-checks/0")
        assert r.status_code == 200


# ── per-scout progress (leider view) ─────────────────────────────────────────

from insigne import groups as groups_svc
from insigne.models import GroupMembership, SpeltakMembership


def _make_speltak_with_leider_and_scout(db, peer_signoff=False):
    leider = _active_user(db, email="leider@x.com", name="Leider")
    scout = _active_user(db, email="scout@x.com", name="Scout")
    g = groups_svc.create_group(db, name="G", slug="g-scout-test", created_by_id=leider.id)
    s = groups_svc.create_speltak(db, group_id=g.id, name="S", slug="s-scout-test", peer_signoff=peer_signoff)
    db.add(SpeltakMembership(user_id=leider.id, speltak_id=s.id, role="speltakleider", approved=True))
    db.add(SpeltakMembership(user_id=scout.id, speltak_id=s.id, role="scout", approved=True))
    db.commit()
    return leider, scout, g, s


class TestScoutProgressHome:
    def test_redirects_to_login_when_unauthenticated(self, client, db):
        scout = _active_user(db)
        r = client.get(f"/scouts/{scout.id}", follow_redirects=False)
        assert r.status_code == 303
        assert "/login" in r.headers["location"]

    def test_redirects_to_home_for_own_id(self, client, db):
        user = _active_user(db)
        _set_auth(client, user)
        r = client.get(f"/scouts/{user.id}", follow_redirects=False)
        assert r.status_code == 303
        assert r.headers["location"] == "/"

    def test_redirects_for_no_access(self, client, db):
        user = _active_user(db, email="a@x.com")
        stranger = _active_user(db, email="b@x.com")
        _set_auth(client, user)
        r = client.get(f"/scouts/{stranger.id}", follow_redirects=False)
        assert r.status_code == 303

    def test_returns_200_for_speltakleider(self, client, db):
        leider, scout, g, s = _make_speltak_with_leider_and_scout(db)
        _set_auth(client, leider)
        r = client.get(f"/scouts/{scout.id}")
        assert r.status_code == 200
        assert scout.name in r.text

    def test_shows_read_only_notice_for_peer_signoff(self, client, db):
        leider, scout, g, s = _make_speltak_with_leider_and_scout(db, peer_signoff=True)
        _set_auth(client, leider)
        r = client.get(f"/scouts/{scout.id}")
        assert r.status_code == 200
        assert "alleen bekijken" in r.text

    def test_badge_links_point_to_scout_route(self, client, db):
        leider, scout, g, s = _make_speltak_with_leider_and_scout(db)
        _set_auth(client, leider)
        r = client.get(f"/scouts/{scout.id}")
        assert f"/scouts/{scout.id}/badges/" in r.text


class TestScoutBadgeDetail:
    def test_returns_200_for_speltakleider(self, client, db):
        leider, scout, g, s = _make_speltak_with_leider_and_scout(db)
        _set_auth(client, leider)
        r = client.get(f"/scouts/{scout.id}/badges/{_BADGE}")
        assert r.status_code == 200

    def test_unknown_badge_redirects_to_scout_home(self, client, db):
        leider, scout, g, s = _make_speltak_with_leider_and_scout(db)
        _set_auth(client, leider)
        r = client.get(f"/scouts/{scout.id}/badges/doesnotexist", follow_redirects=False)
        assert r.status_code == 303
        assert f"/scouts/{scout.id}" in r.headers["location"]

    def test_read_only_for_peer_signoff(self, client, db):
        leider, scout, g, s = _make_speltak_with_leider_and_scout(db, peer_signoff=True)
        _set_auth(client, leider)
        r = client.get(f"/scouts/{scout.id}/badges/{_BADGE}")
        assert r.status_code == 200
        assert "alleen bekijken" in r.text


class TestScoutSetProgress:
    def test_speltakleider_can_set_progress(self, client, db):
        leider, scout, g, s = _make_speltak_with_leider_and_scout(db)
        _set_auth(client, leider)
        r = client.post(
            f"/scouts/{scout.id}/set-progress",
            data={"badge_slug": _BADGE, "level_index": _LEVEL, "step_index": _STEP, "status": "in_progress"},
        )
        assert r.status_code == 200
        entry = db.query(ProgressEntry).filter_by(user_id=scout.id).first()
        assert entry is not None
        assert entry.status == "in_progress"

    def test_groepsleider_cannot_edit(self, client, db):
        groepsleider = _active_user(db, email="gl@x.com", name="GL")
        scout = _active_user(db, email="sc2@x.com", name="Scout2")
        g = groups_svc.create_group(db, name="GG", slug="gg-t", created_by_id=groepsleider.id)
        s = groups_svc.create_speltak(db, group_id=g.id, name="SS", slug="ss-t")
        db.add(SpeltakMembership(user_id=scout.id, speltak_id=s.id, role="scout", approved=True))
        db.commit()
        _set_auth(client, groepsleider)
        r = client.post(
            f"/scouts/{scout.id}/set-progress",
            data={"badge_slug": _BADGE, "level_index": _LEVEL, "step_index": _STEP, "status": "in_progress"},
        )
        assert r.status_code == 403

    def test_signed_off_downgrade_requires_message(self, client, db):
        leider, scout, g, s = _make_speltak_with_leider_and_scout(db)
        _set_auth(client, leider)
        # First sign off
        db.add(ProgressEntry(user_id=scout.id, badge_slug=_BADGE, level_index=_LEVEL,
                             step_index=_STEP, status="signed_off"))
        db.commit()
        r = client.post(
            f"/scouts/{scout.id}/set-progress",
            data={"badge_slug": _BADGE, "level_index": _LEVEL, "step_index": _STEP,
                  "status": "work_done", "message": ""},
        )
        assert r.status_code == 200
        entry = db.query(ProgressEntry).filter_by(user_id=scout.id).first()
        assert entry.status == "signed_off"  # unchanged; message required

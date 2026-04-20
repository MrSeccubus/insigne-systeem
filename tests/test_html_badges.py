"""Behavioural tests for the HTML badge/progress routes (routers/html_badges.py).

We test status codes, redirects, HX-Trigger headers, and error text —
not exact HTML markup.
"""
from unittest.mock import patch

from insigne import users as user_svc
from insigne.auth import create_access_token
from insigne.models import ConfirmationToken, ProgressEntry, SignoffRequest, User


# ── helpers ───────────────────────────────────────────────────────────────────

_BADGE = "cybersecurity"
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

class TestNiveauChecks:
    def test_known_badge_returns_200(self, client, db):
        r = client.get(f"/badges/{_BADGE}/niveau-checks/0")
        assert r.status_code == 200

    def test_unknown_badge_returns_empty(self, client, db):
        r = client.get("/badges/doesnotexist/niveau-checks/0")
        assert r.status_code == 200
        assert r.text.strip() == ""

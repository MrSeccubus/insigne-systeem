"""HTML endpoint tests for jaarinsigne_2026 batch sign-off."""
from insigne.auth import create_access_token
from insigne import groups as groups_svc
from insigne.models import (
    GroupMembership,
    ProgressEntry,
    SignoffRequest,
    SpeltakMembership,
    User,
)


def _auth(user):
    token, _ = create_access_token(user.id)
    return {"access_token": token}


def _user(db, email, name="X"):
    u = User(email=email, name=name, status="active", password_hash="x")
    db.add(u)
    db.commit()
    return u


def _entry(db, user_id, level_index, step_index, status):
    e = ProgressEntry(
        user_id=user_id, badge_slug="jaarinsigne_2026",
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


class TestRequestSignoffSpeltakEndpoint:
    def test_creates_pending_signoffs_and_returns_body(self, client, db):
        scout = _user(db, "scout@x.com", "Scout")
        leider = _user(db, "leider@x.com", "Leider")
        _, speltak = _speltak_with_leider(db, leider, scout)
        # welpen has 3 eisen — create work_done entries for all so we hit "ready"
        _entry(db, scout.id, 1, 0, "work_done")
        _entry(db, scout.id, 1, 1, "work_done")
        _entry(db, scout.id, 1, 2, "work_done")

        client.cookies.update(_auth(scout))
        r = client.post(
            "/badges/jaarinsigne_2026/request-signoff-speltak",
            data={"speltak_id": speltak.id},
            headers={"HX-Request": "true"},
            follow_redirects=False,
        )
        assert r.status_code == 200
        assert 'id="jaarinsigne-2026-body"' in r.text
        assert db.query(SignoffRequest).count() == 3
        for e in db.query(ProgressEntry).filter_by(user_id=scout.id).all():
            assert e.status == "pending_signoff"

    def test_redirect_without_htmx(self, client, db):
        scout = _user(db, "scout@x.com", "Scout")
        leider = _user(db, "leider@x.com", "Leider")
        _, speltak = _speltak_with_leider(db, leider, scout)
        _entry(db, scout.id, 1, 0, "work_done")

        client.cookies.update(_auth(scout))
        r = client.post(
            "/badges/jaarinsigne_2026/request-signoff-speltak",
            data={"speltak_id": speltak.id},
            follow_redirects=False,
        )
        assert r.status_code == 303
        assert r.headers["location"] == "/badges/jaarinsigne_2026"


class TestCancelSignoffEndpoint:
    def test_reverts_pending_to_work_done(self, client, db):
        scout = _user(db, "scout@x.com", "Scout")
        leider = _user(db, "leider@x.com", "Leider")
        _, speltak = _speltak_with_leider(db, leider, scout)
        _entry(db, scout.id, 1, 0, "work_done")
        _entry(db, scout.id, 1, 1, "work_done")
        _entry(db, scout.id, 1, 2, "work_done")

        client.cookies.update(_auth(scout))
        client.post(
            "/badges/jaarinsigne_2026/request-signoff-speltak",
            data={"speltak_id": speltak.id},
            headers={"HX-Request": "true"},
        )
        assert db.query(SignoffRequest).count() == 3

        r = client.post(
            "/badges/jaarinsigne_2026/cancel-signoff",
            headers={"HX-Request": "true"},
        )
        assert r.status_code == 200
        assert db.query(SignoffRequest).count() == 0
        for e in db.query(ProgressEntry).filter_by(user_id=scout.id).all():
            assert e.status == "work_done"


class TestToggleBlockedWhenPending:
    def test_toggle_inclusion_no_op_when_pending(self, client, db):
        from insigne.models import Jaarinsigne2026Inclusion

        scout = _user(db, "scout@x.com", "Scout")
        leider = _user(db, "leider@x.com", "Leider")
        _, speltak = _speltak_with_leider(db, leider, scout)
        _entry(db, scout.id, 1, 0, "work_done")

        # Create a signed-off eis on a gewoon badge that the scout could toggle
        regular = ProgressEntry(
            user_id=scout.id, badge_slug="kamperen",
            level_index=0, step_index=0, status="signed_off",
        )
        db.add(regular)
        db.commit()

        client.cookies.update(_auth(scout))
        # Move scout into pending state
        client.post(
            "/badges/jaarinsigne_2026/request-signoff-speltak",
            data={"speltak_id": speltak.id},
            headers={"HX-Request": "true"},
        )
        # Try to add a kamperen eis to the inclusion list while pending — must be a no-op.
        before = db.query(Jaarinsigne2026Inclusion).count()
        r = client.post(
            "/badges/jaarinsigne_2026/toggle-inclusion",
            data={"badge_slug": "kamperen", "level_index": 0, "step_index": 0},
            headers={"HX-Request": "true"},
            follow_redirects=False,
        )
        assert r.status_code == 200
        after = db.query(Jaarinsigne2026Inclusion).count()
        assert after == before


class TestSelfSignoffSurfaceError:
    def test_direct_self_signoff_returns_error_in_body(self, client, db):
        scout = _user(db, "scout@x.com", "Scout")
        _entry(db, scout.id, 1, 0, "work_done")
        client.cookies.update(_auth(scout))
        r = client.post(
            "/badges/jaarinsigne_2026/request-signoff",
            data={"mentor_email": "scout@x.com"},
            headers={"HX-Request": "true"},
        )
        assert r.status_code == 200
        assert "Je kunt jezelf niet uitnodigen" in r.text
        # Entry must still be work_done (not flipped to pending_signoff)
        e = db.query(ProgressEntry).filter_by(user_id=scout.id).first()
        assert e.status == "work_done"


class TestMentorConfirmRejectEndpoints:
    def test_confirm_signs_off_all(self, client, db):
        scout = _user(db, "scout@x.com", "Scout")
        leider = _user(db, "leider@x.com", "Leider")
        _, speltak = _speltak_with_leider(db, leider, scout)
        _entry(db, scout.id, 1, 0, "work_done")
        _entry(db, scout.id, 1, 1, "work_done")
        _entry(db, scout.id, 1, 2, "work_done")

        client.cookies.update(_auth(scout))
        client.post(
            "/badges/jaarinsigne_2026/request-signoff-speltak",
            data={"speltak_id": speltak.id},
            headers={"HX-Request": "true"},
        )
        client.cookies.clear()

        client.cookies.update(_auth(leider))
        r = client.post(
            f"/scouts/{scout.id}/jaarinsigne_2026/confirm-signoff",
            data={"comment": "Goed gedaan"},
        )
        assert r.status_code == 200
        for e in db.query(ProgressEntry).filter_by(user_id=scout.id).all():
            assert e.status == "signed_off"
            assert e.signed_off_by_id == leider.id

    def test_reject_creates_rejections_and_reverts(self, client, db):
        from insigne.models import SignoffRejection

        scout = _user(db, "scout@x.com", "Scout")
        leider = _user(db, "leider@x.com", "Leider")
        _, speltak = _speltak_with_leider(db, leider, scout)
        _entry(db, scout.id, 1, 0, "work_done")
        _entry(db, scout.id, 1, 1, "work_done")
        _entry(db, scout.id, 1, 2, "work_done")

        client.cookies.update(_auth(scout))
        client.post(
            "/badges/jaarinsigne_2026/request-signoff-speltak",
            data={"speltak_id": speltak.id},
            headers={"HX-Request": "true"},
        )
        client.cookies.clear()

        client.cookies.update(_auth(leider))
        r = client.post(
            f"/scouts/{scout.id}/jaarinsigne_2026/reject-signoff",
            data={"message": "Probeer nog eens"},
        )
        assert r.status_code == 200
        for e in db.query(ProgressEntry).filter_by(user_id=scout.id).all():
            assert e.status == "work_done"
        assert db.query(SignoffRejection).count() == 3

"""HTML integration tests for per-badge-niveau batch sign-off (#102)."""
import re

import insigne.auth as auth_svc
from insigne import groups as groups_svc
from insigne import progress as progress_svc
from insigne.models import (
    GroupMembership,
    ProgressEntry,
    SignoffRequest,
    SpeltakMembership,
    User,
)


# ── Helpers ───────────────────────────────────────────────────────────────────

def _user(db, email, name="X"):
    u = User(email=email, name=name, status="active", password_hash="x")
    db.add(u); db.commit()
    return u


def _entry(db, user_id, badge_slug, level_index, step_index, status="work_done"):
    e = ProgressEntry(
        user_id=user_id, badge_slug=badge_slug,
        level_index=level_index, step_index=step_index, status=status,
    )
    db.add(e); db.commit()
    return e


def _speltak_with_leider(db, leider, scout, speltak_type="welpen"):
    g = groups_svc.create_group(db, name="G", slug="g", created_by_id=leider.id)
    s = groups_svc.create_speltak(
        db, group_id=g.id, name="Welpen", slug="welpen", speltak_type=speltak_type,
    )
    db.add(GroupMembership(user_id=leider.id, group_id=g.id,
                           role="groepsleider", approved=True))
    db.add(SpeltakMembership(user_id=leider.id, speltak_id=s.id,
                             role="speltakleider", approved=True))
    db.add(GroupMembership(user_id=scout.id, group_id=g.id,
                           role="member", approved=True))
    db.add(SpeltakMembership(user_id=scout.id, speltak_id=s.id,
                             role="scout", approved=True))
    db.commit()
    return g, s


def _login(client, user):
    token, _ = auth_svc.create_access_token(user.id)
    return {"access_token": token}


# ── Scout-side POST endpoints ────────────────────────────────────────────────

class TestBatchSignoffSpeltakHTML:
    def test_creates_signoff_requests_and_redirects(self, client, db):
        scout = _user(db, "s@x.com")
        leider = _user(db, "l@x.com", "Leider")
        _, speltak = _speltak_with_leider(db, leider, scout)
        _entry(db, scout.id, "kamperen", 0, 0, "work_done")
        _entry(db, scout.id, "kamperen", 1, 0, "work_done")

        client.cookies.update(_login(client, scout))
        r = client.post(
            "/badges/kamperen/niveau/0/request-signoff-speltak",
            data={"speltak_id": speltak.id},
            headers={"Origin": "http://localhost:8000"},
            follow_redirects=False,
        )
        assert r.status_code == 303
        assert r.headers["location"] == "/badges/kamperen"
        assert db.query(SignoffRequest).count() == 2


class TestBatchSignoffCancelHTML:
    def test_cancel_drops_pending_requests(self, client, db):
        scout = _user(db, "s@x.com")
        leider = _user(db, "l@x.com", "Leider")
        _, speltak = _speltak_with_leider(db, leider, scout)
        _entry(db, scout.id, "kamperen", 0, 0, "work_done")
        progress_svc.request_badge_niveau_signoff_speltak(
            db, scout.id, "kamperen", 0, speltak.id,
        )
        assert db.query(SignoffRequest).count() == 1

        client.cookies.update(_login(client, scout))
        r = client.post(
            "/badges/kamperen/niveau/0/cancel-signoff",
            headers={"Origin": "http://localhost:8000"},
            follow_redirects=False,
        )
        assert r.status_code == 303
        assert db.query(SignoffRequest).count() == 0


class TestBatchSignoffDirectHTML:
    def test_direct_email_creates_pending_signoff(self, client, db):
        scout = _user(db, "s@x.com")
        _entry(db, scout.id, "kamperen", 0, 0, "work_done")
        client.cookies.update(_login(client, scout))
        r = client.post(
            "/badges/kamperen/niveau/0/request-signoff",
            data={"mentor_email": "new@x.com"},
            headers={"Origin": "http://localhost:8000"},
            follow_redirects=False,
        )
        assert r.status_code == 303
        assert db.query(User).filter_by(email="new@x.com").first() is not None
        assert db.query(SignoffRequest).count() == 1


# ── Mentor-side confirm / reject ─────────────────────────────────────────────

class TestBatchConfirmHTML:
    def test_confirm_signs_off_all_eisen_at_niveau(self, client, db):
        scout = _user(db, "s@x.com")
        leider = _user(db, "l@x.com", "Leider")
        _, speltak = _speltak_with_leider(db, leider, scout)
        _entry(db, scout.id, "kamperen", 0, 0, "work_done")
        _entry(db, scout.id, "kamperen", 1, 0, "work_done")
        progress_svc.request_badge_niveau_signoff_speltak(
            db, scout.id, "kamperen", 0, speltak.id,
        )

        client.cookies.update(_login(client, leider))
        r = client.post(
            f"/scouts/{scout.id}/badges/kamperen/niveau/0/confirm-signoff",
            data={"comment": "Goed gedaan!"},
            headers={"HX-Request": "true", "Origin": "http://localhost:8000"},
        )
        assert r.status_code == 200
        # Both ProgressEntry rows must now be signed_off.
        statuses = [
            e.status for e in db.query(ProgressEntry)
            .filter_by(user_id=scout.id, badge_slug="kamperen", step_index=0)
            .all()
        ]
        assert statuses == ["signed_off", "signed_off"]


class TestBatchRejectHTML:
    def test_reject_reverts_to_work_done_with_message(self, client, db):
        scout = _user(db, "s@x.com")
        leider = _user(db, "l@x.com", "Leider")
        _, speltak = _speltak_with_leider(db, leider, scout)
        _entry(db, scout.id, "kamperen", 0, 0, "work_done")
        progress_svc.request_badge_niveau_signoff_speltak(
            db, scout.id, "kamperen", 0, speltak.id,
        )

        client.cookies.update(_login(client, leider))
        r = client.post(
            f"/scouts/{scout.id}/badges/kamperen/niveau/0/reject-signoff",
            data={"message": "Nog niet goed"},
            headers={"HX-Request": "true", "Origin": "http://localhost:8000"},
        )
        assert r.status_code == 200
        e = db.query(ProgressEntry).filter_by(
            user_id=scout.id, badge_slug="kamperen", step_index=0,
        ).first()
        assert e.status == "work_done"


# ── Inbox view shows the group card ──────────────────────────────────────────

class TestSignoffRequestsPageGroup:
    def test_inbox_renders_badge_niveau_group_card(self, client, db):
        scout = _user(db, "scout@x.com", "Scout")
        leider = _user(db, "leider@x.com", "Leider")
        _, speltak = _speltak_with_leider(db, leider, scout)
        _entry(db, scout.id, "kamperen", 0, 0, "work_done")
        _entry(db, scout.id, "kamperen", 1, 0, "work_done")
        progress_svc.request_badge_niveau_signoff_speltak(
            db, scout.id, "kamperen", 0, speltak.id,
        )

        client.cookies.update(_login(client, leider))
        r = client.get("/signoff-requests")
        assert r.status_code == 200
        # The badge-niveau group card has a stable id we can grep for.
        assert re.search(
            rf'id="request-badge-niveau-{scout.id}-kamperen-0"',
            r.text,
        ), "Expected a badge_niveau_group card in the inbox"
        # Singleton per-eis cards must NOT render alongside the group.
        # The group card heading mentions the niveau.
        assert "Niveau 1" in r.text


# ── Scout badge page shows the batch panel when ready ────────────────────────

class TestBatchPanelVisibility:
    def test_panel_appears_when_all_eisen_work_done(self, client, db):
        scout = _user(db, "s@x.com")
        # Set every level's niveau 0 (step_index=0) to work_done.
        # The "kamperen" badge has multiple eisen — touch them all.
        # For the test we only need ONE eis to satisfy the "all eisen at this
        # niveau are work_done OR signed_off" rule, but kamperen has 5 eisen,
        # so we must mark all of them at niveau 0.
        from insigne.badges import BadgeCatalogue
        from pathlib import Path
        cat = BadgeCatalogue(Path(__file__).parent.parent.parent / "api" / "data")
        badge = cat.get("kamperen")
        for ei, level in enumerate(badge["levels"]):
            if level["steps"][0]["text"].strip():
                _entry(db, scout.id, "kamperen", ei, 0, "work_done")

        client.cookies.update(_login(client, scout))
        r = client.get("/badges/kamperen?niveau=1")
        assert r.status_code == 200
        assert "Vraag aftekening" in r.text or "Aftekenen…" in r.text
        # Form action pointing at the batch endpoint.
        assert "/badges/kamperen/niveau/0/request-signoff" in r.text

    def test_panel_absent_when_no_eisen_done(self, client, db):
        scout = _user(db, "s@x.com")
        client.cookies.update(_login(client, scout))
        r = client.get("/badges/kamperen?niveau=1")
        assert r.status_code == 200
        # No batch endpoint URL on the page.
        assert "/badges/kamperen/niveau/0/request-signoff" not in r.text

"""Tests for the per-badge-niveau batch sign-off service functions (#102)."""
import pytest

from insigne import groups as groups_svc
from insigne import progress as progress_svc
from insigne.models import (
    GroupMembership,
    ProgressEntry,
    SignoffRejection,
    SignoffRequest,
    SpeltakMembership,
    User,
)


# ── Helpers ───────────────────────────────────────────────────────────────────

def _user(db, email="scout@example.com", name="Scout"):
    u = User(email=email, name=name, status="active", password_hash="x")
    db.add(u); db.commit()
    return u


def _entry(db, user_id, badge_slug, level_index, step_index, status):
    """A regular-badge ProgressEntry where step_index = niveau."""
    e = ProgressEntry(
        user_id=user_id, badge_slug=badge_slug,
        level_index=level_index, step_index=step_index, status=status,
    )
    db.add(e); db.commit()
    return e


def _speltak_with_leider(db, leider, scout, speltak_type="welpen"):
    g = groups_svc.create_group(db, name="G", slug="g", created_by_id=leider.id)
    s = groups_svc.create_speltak(db, group_id=g.id, name="Welpen", slug="welpen",
                                  speltak_type=speltak_type)
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


# ── request_badge_niveau_signoff_speltak ─────────────────────────────────────

class TestRequestSignoffSpeltak:
    def test_invites_leider_for_each_work_done_eis_at_niveau(self, db):
        scout = _user(db, "s@x.com")
        leider = _user(db, "l@x.com", "Leider")
        _, speltak = _speltak_with_leider(db, leider, scout)

        # Two eisen at niveau 1 (step_index=1), one at niveau 2 (step_index=2).
        e1 = _entry(db, scout.id, "kamperen", 0, 1, "work_done")
        e2 = _entry(db, scout.id, "kamperen", 1, 1, "work_done")
        _entry(db, scout.id, "kamperen", 0, 2, "work_done")  # different niveau

        entries, invited = progress_svc.request_badge_niveau_signoff_speltak(
            db, scout.id, "kamperen", 1, speltak.id,
        )
        # Only niveau-1 eisen included.
        assert {e.id for e in entries} == {e1.id, e2.id}
        for e in entries:
            assert e.status == "pending_signoff"
        assert [m.id for m in invited] == [leider.id]
        assert db.query(SignoffRequest).count() == 2

    def test_raises_when_no_eligible_entries(self, db):
        scout = _user(db, "s@x.com")
        leider = _user(db, "l@x.com", "Leider")
        _, speltak = _speltak_with_leider(db, leider, scout)
        _entry(db, scout.id, "kamperen", 0, 0, "in_progress")
        with pytest.raises(progress_svc.NotFound, match="no_entries"):
            progress_svc.request_badge_niveau_signoff_speltak(
                db, scout.id, "kamperen", 0, speltak.id,
            )

    def test_rejects_speltak_scout_is_not_member_of(self, db):
        scout = _user(db, "s@x.com")
        _entry(db, scout.id, "kamperen", 0, 0, "work_done")
        # Speltak in a different group; scout has no membership.
        other_leider = _user(db, "ol@x.com", "Other")
        og = groups_svc.create_group(db, name="O", slug="other",
                                     created_by_id=other_leider.id)
        os_ = groups_svc.create_speltak(db, group_id=og.id, name="X", slug="x",
                                        speltak_type="welpen")
        db.add(GroupMembership(user_id=other_leider.id, group_id=og.id,
                               role="groepsleider", approved=True))
        db.add(SpeltakMembership(user_id=other_leider.id, speltak_id=os_.id,
                                 role="speltakleider", approved=True))
        db.commit()
        with pytest.raises(progress_svc.Forbidden, match="not_member"):
            progress_svc.request_badge_niveau_signoff_speltak(
                db, scout.id, "kamperen", 0, os_.id,
            )

    def test_dedup_on_repeat_call(self, db):
        scout = _user(db, "s@x.com")
        leider = _user(db, "l@x.com", "Leider")
        _, speltak = _speltak_with_leider(db, leider, scout)
        _entry(db, scout.id, "kamperen", 0, 0, "work_done")
        progress_svc.request_badge_niveau_signoff_speltak(
            db, scout.id, "kamperen", 0, speltak.id,
        )
        progress_svc.request_badge_niveau_signoff_speltak(
            db, scout.id, "kamperen", 0, speltak.id,
        )
        assert db.query(SignoffRequest).count() == 1


# ── request_badge_niveau_signoff_members ─────────────────────────────────────

class TestRequestSignoffMembers:
    def test_invites_each_peer(self, db):
        scout = _user(db, "s@x.com")
        peer1 = _user(db, "p1@x.com", "P1")
        peer2 = _user(db, "p2@x.com", "P2")
        g = groups_svc.create_group(db, name="G", slug="g", created_by_id=scout.id)
        s = groups_svc.create_speltak(db, group_id=g.id, name="R", slug="r",
                                      speltak_type="roverscouts", peer_signoff=True)
        for u in (scout, peer1, peer2):
            db.add(GroupMembership(user_id=u.id, group_id=g.id,
                                   role="member", approved=True))
            db.add(SpeltakMembership(user_id=u.id, speltak_id=s.id,
                                     role="scout", approved=True))
        db.commit()
        _entry(db, scout.id, "kamperen", 0, 0, "work_done")
        _entry(db, scout.id, "kamperen", 1, 0, "work_done")
        entries, invited = progress_svc.request_badge_niveau_signoff_members(
            db, scout.id, "kamperen", 0, [peer1.id, peer2.id],
        )
        assert {m.id for m in invited} == {peer1.id, peer2.id}
        assert db.query(SignoffRequest).count() == 4  # 2 eisen × 2 mentors

    def test_filters_mentor_outside_scout_speltak(self, db):
        scout = _user(db, "s@x.com")
        leider = _user(db, "l@x.com", "Leider")
        _speltak_with_leider(db, leider, scout)
        stranger = _user(db, "stranger@x.com")  # no shared speltak
        _entry(db, scout.id, "kamperen", 0, 0, "work_done")
        with pytest.raises(progress_svc.NotFound, match="no_eligible_mentors"):
            progress_svc.request_badge_niveau_signoff_members(
                db, scout.id, "kamperen", 0, [stranger.id],
            )


# ── request_badge_niveau_signoff (direct e-mail) ─────────────────────────────

class TestRequestSignoffDirect:
    def test_creates_mentor_when_email_unknown(self, db):
        scout = _user(db, "s@x.com")
        _entry(db, scout.id, "kamperen", 0, 0, "work_done")
        entries, mentor, created = progress_svc.request_badge_niveau_signoff(
            db, scout.id, "kamperen", 0, "new@x.com",
        )
        assert created is True
        assert mentor.email == "new@x.com"
        assert all(e.status == "pending_signoff" for e in entries)

    def test_self_signoff_forbidden(self, db):
        scout = _user(db, "s@x.com")
        _entry(db, scout.id, "kamperen", 0, 0, "work_done")
        with pytest.raises(progress_svc.Forbidden, match="self_signoff"):
            progress_svc.request_badge_niveau_signoff(
                db, scout.id, "kamperen", 0, "s@x.com",
            )

    def test_invalid_email_rejected(self, db):
        scout = _user(db, "s@x.com")
        _entry(db, scout.id, "kamperen", 0, 0, "work_done")
        with pytest.raises(progress_svc.Conflict, match="invalid_email"):
            progress_svc.request_badge_niveau_signoff(
                db, scout.id, "kamperen", 0, "not-an-email",
            )


# ── cancel_badge_niveau_signoff_requests ─────────────────────────────────────

class TestCancelSignoffRequests:
    def test_removes_pending_and_restores_work_done(self, db):
        scout = _user(db, "s@x.com")
        leider = _user(db, "l@x.com", "Leider")
        _, speltak = _speltak_with_leider(db, leider, scout)
        e1 = _entry(db, scout.id, "kamperen", 0, 0, "work_done")
        e2 = _entry(db, scout.id, "kamperen", 1, 0, "work_done")
        progress_svc.request_badge_niveau_signoff_speltak(
            db, scout.id, "kamperen", 0, speltak.id,
        )
        affected = progress_svc.cancel_badge_niveau_signoff_requests(
            db, scout.id, "kamperen", 0,
        )
        assert {e.id for e in affected} == {e1.id, e2.id}
        assert db.query(SignoffRequest).count() == 0
        for e in (e1, e2):
            db.refresh(e)
            assert e.status == "work_done"

    def test_does_not_affect_other_niveaus(self, db):
        scout = _user(db, "s@x.com")
        leider = _user(db, "l@x.com", "Leider")
        _, speltak = _speltak_with_leider(db, leider, scout)
        _entry(db, scout.id, "kamperen", 0, 0, "work_done")
        _entry(db, scout.id, "kamperen", 0, 1, "work_done")
        progress_svc.request_badge_niveau_signoff_speltak(
            db, scout.id, "kamperen", 0, speltak.id,
        )
        progress_svc.request_badge_niveau_signoff_speltak(
            db, scout.id, "kamperen", 1, speltak.id,
        )
        assert db.query(SignoffRequest).count() == 2
        # Cancel only niveau 0 — niveau 1 invite stays.
        progress_svc.cancel_badge_niveau_signoff_requests(
            db, scout.id, "kamperen", 0,
        )
        assert db.query(SignoffRequest).count() == 1


# ── confirm_badge_niveau_signoff ─────────────────────────────────────────────

class TestConfirmSignoff:
    def test_signs_off_all_eisen_at_niveau(self, db):
        scout = _user(db, "s@x.com")
        leider = _user(db, "l@x.com", "Leider")
        _, speltak = _speltak_with_leider(db, leider, scout)
        _entry(db, scout.id, "kamperen", 0, 0, "work_done")
        _entry(db, scout.id, "kamperen", 1, 0, "work_done")
        progress_svc.request_badge_niveau_signoff_speltak(
            db, scout.id, "kamperen", 0, speltak.id,
        )
        affected = progress_svc.confirm_badge_niveau_signoff(
            db, leider.id, scout.id, "kamperen", 0,
        )
        assert len(affected) == 2
        for e in affected:
            assert e.status == "signed_off"
            assert e.signed_off_by_id == leider.id

    def test_self_signoff_forbidden(self, db):
        scout = _user(db, "s@x.com")
        _entry(db, scout.id, "kamperen", 0, 0, "work_done")
        with pytest.raises(progress_svc.Forbidden, match="self_signoff"):
            progress_svc.confirm_badge_niveau_signoff(
                db, scout.id, scout.id, "kamperen", 0,
            )

    def test_not_invited_forbidden(self, db):
        scout = _user(db, "s@x.com")
        other = _user(db, "o@x.com")
        _entry(db, scout.id, "kamperen", 0, 0, "work_done")
        with pytest.raises(progress_svc.Forbidden, match="not_invited"):
            progress_svc.confirm_badge_niveau_signoff(
                db, other.id, scout.id, "kamperen", 0,
            )


# ── reject_badge_niveau_signoff ──────────────────────────────────────────────

class TestRejectSignoff:
    def test_removes_invite_and_reverts_to_work_done(self, db):
        scout = _user(db, "s@x.com")
        leider = _user(db, "l@x.com", "Leider")
        _, speltak = _speltak_with_leider(db, leider, scout)
        _entry(db, scout.id, "kamperen", 0, 0, "work_done")
        _entry(db, scout.id, "kamperen", 1, 0, "work_done")
        progress_svc.request_badge_niveau_signoff_speltak(
            db, scout.id, "kamperen", 0, speltak.id,
        )
        affected = progress_svc.reject_badge_niveau_signoff(
            db, leider.id, scout.id, "kamperen", 0, "Niet nu",
        )
        assert len(affected) == 2
        for e in affected:
            assert e.status == "work_done"
        assert db.query(SignoffRequest).count() == 0
        rejections = db.query(SignoffRejection).all()
        assert len(rejections) == 2
        assert all(r.message == "Niet nu" for r in rejections)


# ── list_signoff_requests_grouped auto-grouping ──────────────────────────────

class TestAutoGroupingBadgeNiveau:
    def test_two_or_more_siblings_form_a_group(self, db):
        scout = _user(db, "s@x.com")
        leider = _user(db, "l@x.com", "Leider")
        _, speltak = _speltak_with_leider(db, leider, scout)
        # 2 eisen at niveau 0 — should auto-group.
        _entry(db, scout.id, "kamperen", 0, 0, "work_done")
        _entry(db, scout.id, "kamperen", 1, 0, "work_done")
        progress_svc.request_badge_niveau_signoff_speltak(
            db, scout.id, "kamperen", 0, speltak.id,
        )

        items = progress_svc.list_signoff_requests_grouped(db, leider.id)
        groups = [it for it in items if isinstance(it, dict)]
        assert len(groups) == 1
        g = groups[0]
        assert g["type"] == "badge_niveau_group"
        assert g["badge_slug"] == "kamperen"
        assert g["niveau_index"] == 0
        assert len(g["requests"]) == 2

    def test_singleton_per_eis_renders_as_plain_request(self, db):
        """A single per-eis invite (no batchable sibling) should keep the
        existing per-eis card behaviour, not be wrapped in a 1-item group."""
        scout = _user(db, "s@x.com")
        leider = _user(db, "l@x.com", "Leider")
        _, speltak = _speltak_with_leider(db, leider, scout)
        e = _entry(db, scout.id, "kamperen", 0, 0, "work_done")
        # Invite via the legacy per-eis function — only one request created.
        progress_svc.request_signoff_for_speltak(db, scout.id, e.id, speltak.id)

        items = progress_svc.list_signoff_requests_grouped(db, leider.id)
        groups = [it for it in items if isinstance(it, dict)]
        plain = [it for it in items if not isinstance(it, dict)]
        assert len(groups) == 0
        assert len(plain) == 1

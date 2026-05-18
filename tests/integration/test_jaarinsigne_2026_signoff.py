"""Tests for the jaarinsigne_2026 batch sign-off service functions."""
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
    db.add(u)
    db.commit()
    return u


def _entry(db, user_id, level_index, step_index, status):
    e = ProgressEntry(
        user_id=user_id,
        badge_slug="jaarinsigne_2026",
        level_index=level_index,
        step_index=step_index,
        status=status,
    )
    db.add(e)
    db.commit()
    return e


def _speltak_with_leider(db, leider_user, scout_user, speltak_type="welpen"):
    """Create a group + speltak with leider, plus a scout membership."""
    g = groups_svc.create_group(db, name="Groep X", slug="groep-x", created_by_id=leider_user.id)
    s = groups_svc.create_speltak(
        db, group_id=g.id, name="Welpen", slug="welpen", speltak_type=speltak_type,
    )
    db.add(GroupMembership(user_id=leider_user.id, group_id=g.id, role="groepsleider", approved=True))
    db.add(SpeltakMembership(user_id=leider_user.id, speltak_id=s.id, role="speltakleider", approved=True))
    db.add(GroupMembership(user_id=scout_user.id, group_id=g.id, role="member", approved=True))
    db.add(SpeltakMembership(user_id=scout_user.id, speltak_id=s.id, role="scout", approved=True))
    db.commit()
    return g, s


# ── request_jaarinsigne_2026_signoff_speltak ─────────────────────────────────

class TestRequestSignoffSpeltak:
    def test_creates_signoff_requests_for_all_work_done_eisen(self, db):
        scout = _user(db, "scout@x.com", "Scout")
        leider = _user(db, "leider@x.com", "Leider")
        _, speltak = _speltak_with_leider(db, leider, scout)

        e1 = _entry(db, scout.id, 1, 0, "work_done")
        e2 = _entry(db, scout.id, 1, 1, "work_done")

        entries, invited = progress_svc.request_jaarinsigne_2026_signoff_speltak(
            db, scout.id, speltak.id,
        )
        assert len(entries) == 2
        assert {e.id for e in entries} == {e1.id, e2.id}
        for e in entries:
            assert e.status == "pending_signoff"
        assert [m.id for m in invited] == [leider.id]
        assert db.query(SignoffRequest).count() == 2

    def test_raises_when_no_eligible_entries(self, db):
        scout = _user(db, "scout@x.com", "Scout")
        leider = _user(db, "leider@x.com", "Leider")
        _, speltak = _speltak_with_leider(db, leider, scout)
        # Only an in_progress entry — not eligible.
        _entry(db, scout.id, 1, 0, "in_progress")
        with pytest.raises(progress_svc.NotFound, match="no_entries"):
            progress_svc.request_jaarinsigne_2026_signoff_speltak(
                db, scout.id, speltak.id,
            )

    def test_raises_when_no_eligible_mentors(self, db):
        scout = _user(db, "scout@x.com", "Scout")
        leider = _user(db, "leider@x.com", "Leider")
        _, speltak = _speltak_with_leider(db, leider, scout)
        _entry(db, scout.id, 1, 0, "work_done")
        # Move scout to be their own leider; only-leider matching is the scout themselves
        # → effectively empty leider list (after self-filter).
        # Easier: delete the leider's membership.
        db.query(SpeltakMembership).filter_by(user_id=leider.id, speltak_id=speltak.id).delete()
        db.commit()
        with pytest.raises(progress_svc.NotFound, match="no_eligible_mentors"):
            progress_svc.request_jaarinsigne_2026_signoff_speltak(
                db, scout.id, speltak.id,
            )

    def test_dedup_when_called_twice(self, db):
        scout = _user(db, "scout@x.com", "Scout")
        leider = _user(db, "leider@x.com", "Leider")
        _, speltak = _speltak_with_leider(db, leider, scout)
        _entry(db, scout.id, 1, 0, "work_done")

        progress_svc.request_jaarinsigne_2026_signoff_speltak(db, scout.id, speltak.id)
        # Calling again should not duplicate the SignoffRequest rows.
        progress_svc.request_jaarinsigne_2026_signoff_speltak(db, scout.id, speltak.id)
        assert db.query(SignoffRequest).count() == 1


# ── request_jaarinsigne_2026_signoff_members ─────────────────────────────────

class TestRequestSignoffMembers:
    def test_invites_each_peer(self, db):
        scout = _user(db, "scout@x.com", "Scout")
        peer1 = _user(db, "peer1@x.com", "Peer1")
        peer2 = _user(db, "peer2@x.com", "Peer2")
        _entry(db, scout.id, 1, 0, "work_done")
        _entry(db, scout.id, 1, 1, "work_done")

        entries, invited = progress_svc.request_jaarinsigne_2026_signoff_members(
            db, scout.id, [peer1.id, peer2.id],
        )
        assert len(entries) == 2
        assert {m.id for m in invited} == {peer1.id, peer2.id}
        assert db.query(SignoffRequest).count() == 4  # 2 eisen × 2 mentors

    def test_filters_self_mentor(self, db):
        scout = _user(db, "scout@x.com", "Scout")
        _entry(db, scout.id, 1, 0, "work_done")
        with pytest.raises(progress_svc.NotFound, match="no_eligible_mentors"):
            progress_svc.request_jaarinsigne_2026_signoff_members(
                db, scout.id, [scout.id],
            )

    def test_raises_when_no_entries(self, db):
        scout = _user(db, "scout@x.com", "Scout")
        peer = _user(db, "peer@x.com", "Peer")
        with pytest.raises(progress_svc.NotFound, match="no_entries"):
            progress_svc.request_jaarinsigne_2026_signoff_members(
                db, scout.id, [peer.id],
            )


# ── request_jaarinsigne_2026_signoff (direct e-mail) ─────────────────────────

class TestRequestSignoffDirect:
    def test_creates_mentor_when_email_unknown(self, db):
        scout = _user(db, "scout@x.com", "Scout")
        _entry(db, scout.id, 1, 0, "work_done")
        entries, mentor, created = progress_svc.request_jaarinsigne_2026_signoff(
            db, scout.id, "new@x.com",
        )
        assert created is True
        assert mentor.email == "new@x.com"
        assert len(entries) == 1
        assert entries[0].status == "pending_signoff"

    def test_uses_existing_mentor(self, db):
        scout = _user(db, "scout@x.com", "Scout")
        existing = _user(db, "mentor@x.com", "Mentor")
        _entry(db, scout.id, 1, 0, "work_done")
        entries, mentor, created = progress_svc.request_jaarinsigne_2026_signoff(
            db, scout.id, "mentor@x.com",
        )
        assert created is False
        assert mentor.id == existing.id

    def test_self_signoff_forbidden(self, db):
        scout = _user(db, "scout@x.com", "Scout")
        _entry(db, scout.id, 1, 0, "work_done")
        with pytest.raises(progress_svc.Forbidden, match="self_signoff"):
            progress_svc.request_jaarinsigne_2026_signoff(db, scout.id, "scout@x.com")

    def test_raises_invalid_email_for_garbage_input(self, db):
        from insigne.models import User
        scout = _user(db, "scout@x.com", "Scout")
        _entry(db, scout.id, 1, 0, "work_done")
        users_before = db.query(User).count()
        with pytest.raises(progress_svc.Conflict, match="invalid_email"):
            progress_svc.request_jaarinsigne_2026_signoff(db, scout.id, "not-an-email")
        assert db.query(User).count() == users_before


# ── cancel_jaarinsigne_2026_signoff_requests ─────────────────────────────────

class TestCancelSignoffRequests:
    def test_removes_pending_and_restores_work_done(self, db):
        scout = _user(db, "scout@x.com", "Scout")
        leider = _user(db, "leider@x.com", "Leider")
        _, speltak = _speltak_with_leider(db, leider, scout)
        _entry(db, scout.id, 1, 0, "work_done")
        _entry(db, scout.id, 1, 1, "work_done")

        progress_svc.request_jaarinsigne_2026_signoff_speltak(db, scout.id, speltak.id)
        assert db.query(SignoffRequest).count() == 2

        affected = progress_svc.cancel_jaarinsigne_2026_signoff_requests(db, scout.id)
        assert len(affected) == 2
        assert db.query(SignoffRequest).count() == 0
        for e in db.query(ProgressEntry).filter_by(user_id=scout.id).all():
            assert e.status == "work_done"

    def test_leaves_signed_off_entries_untouched(self, db):
        scout = _user(db, "scout@x.com", "Scout")
        _entry(db, scout.id, 1, 0, "signed_off")
        affected = progress_svc.cancel_jaarinsigne_2026_signoff_requests(db, scout.id)
        assert affected == []
        e = db.query(ProgressEntry).filter_by(user_id=scout.id).first()
        assert e.status == "signed_off"


# ── confirm_jaarinsigne_2026_signoff ─────────────────────────────────────────

class TestConfirmSignoff:
    def test_signs_off_every_invited_eis(self, db):
        scout = _user(db, "scout@x.com", "Scout")
        leider = _user(db, "leider@x.com", "Leider")
        _, speltak = _speltak_with_leider(db, leider, scout)
        _entry(db, scout.id, 1, 0, "work_done")
        _entry(db, scout.id, 1, 1, "work_done")
        progress_svc.request_jaarinsigne_2026_signoff_speltak(db, scout.id, speltak.id)

        affected = progress_svc.confirm_jaarinsigne_2026_signoff(
            db, leider.id, scout.id, comment="Goed gedaan",
        )
        assert len(affected) == 2
        for e in affected:
            assert e.status == "signed_off"
            assert e.signed_off_by_id == leider.id
            assert e.mentor_comment == "Goed gedaan"
        # All SignoffRequest rows for these entries removed.
        assert db.query(SignoffRequest).count() == 0

    def test_self_signoff_forbidden(self, db):
        scout = _user(db, "scout@x.com", "Scout")
        with pytest.raises(progress_svc.Forbidden, match="self_signoff"):
            progress_svc.confirm_jaarinsigne_2026_signoff(db, scout.id, scout.id)

    def test_not_invited_raises(self, db):
        scout = _user(db, "scout@x.com", "Scout")
        bystander = _user(db, "bystander@x.com", "Bystander")
        with pytest.raises(progress_svc.Forbidden, match="not_invited"):
            progress_svc.confirm_jaarinsigne_2026_signoff(db, bystander.id, scout.id)


# ── reject_jaarinsigne_2026_signoff ──────────────────────────────────────────

class TestRejectSignoff:
    def test_rejects_and_reverts_to_work_done(self, db):
        scout = _user(db, "scout@x.com", "Scout")
        leider = _user(db, "leider@x.com", "Leider")
        _, speltak = _speltak_with_leider(db, leider, scout)
        _entry(db, scout.id, 1, 0, "work_done")
        _entry(db, scout.id, 1, 1, "work_done")
        progress_svc.request_jaarinsigne_2026_signoff_speltak(db, scout.id, speltak.id)

        affected = progress_svc.reject_jaarinsigne_2026_signoff(
            db, leider.id, scout.id, "Doe het nog eens",
        )
        assert len(affected) == 2
        for e in affected:
            assert e.status == "work_done"
        assert db.query(SignoffRejection).count() == 2
        assert db.query(SignoffRequest).count() == 0

    def test_self_signoff_forbidden(self, db):
        scout = _user(db, "scout@x.com", "Scout")
        with pytest.raises(progress_svc.Forbidden, match="self_signoff"):
            progress_svc.reject_jaarinsigne_2026_signoff(db, scout.id, scout.id, "nope")

    def test_keeps_pending_when_other_mentor_still_invited(self, db):
        scout = _user(db, "scout@x.com", "Scout")
        m1 = _user(db, "m1@x.com", "M1")
        m2 = _user(db, "m2@x.com", "M2")
        _entry(db, scout.id, 1, 0, "work_done")
        progress_svc.request_jaarinsigne_2026_signoff_members(
            db, scout.id, [m1.id, m2.id],
        )
        affected = progress_svc.reject_jaarinsigne_2026_signoff(
            db, m1.id, scout.id, "nope",
        )
        assert len(affected) == 1
        # m2 still pending → entry stays pending_signoff
        assert affected[0].status == "pending_signoff"


# ── list_previous_mentors filters self ───────────────────────────────────────

class TestListPreviousMentorsFiltersSelf:
    def test_self_signoff_excluded(self, db):
        u = _user(db, "scout@x.com", "Scout")
        # Simulate a self-signoff sneaking into the data (e.g. import / migration).
        e = ProgressEntry(
            user_id=u.id, badge_slug="kamperen",
            level_index=0, step_index=0, status="signed_off",
            signed_off_by_id=u.id,
        )
        db.add(e)
        db.commit()
        mentors = progress_svc.list_previous_mentors(db, u.id)
        assert all(m.id != u.id for m in mentors)


# ── list_signoff_requests_grouped ────────────────────────────────────────────

class TestListSignoffRequestsGrouped:
    def test_groups_jaarinsigne_per_scout(self, db):
        scout_a = _user(db, "a@x.com", "A")
        scout_b = _user(db, "b@x.com", "B")
        mentor = _user(db, "mentor@x.com", "Mentor")
        _entry(db, scout_a.id, 1, 0, "work_done")
        _entry(db, scout_a.id, 1, 1, "work_done")
        _entry(db, scout_b.id, 1, 0, "work_done")
        progress_svc.request_jaarinsigne_2026_signoff_members(
            db, scout_a.id, [mentor.id],
        )
        progress_svc.request_jaarinsigne_2026_signoff_members(
            db, scout_b.id, [mentor.id],
        )

        items = progress_svc.list_signoff_requests_grouped(db, mentor.id)
        groups = [it for it in items if isinstance(it, dict)]
        assert len(groups) == 2  # one per scout
        scout_ids = {g["scout"].id for g in groups}
        assert scout_ids == {scout_a.id, scout_b.id}
        scout_a_group = next(g for g in groups if g["scout"].id == scout_a.id)
        assert len(scout_a_group["requests"]) == 2

    def test_keeps_regular_badges_as_individual_items(self, db):
        scout = _user(db, "scout@x.com", "Scout")
        mentor = _user(db, "mentor@x.com", "Mentor")
        # Regular badge entry
        regular = ProgressEntry(
            user_id=scout.id, badge_slug="kamperen",
            level_index=0, step_index=0, status="work_done",
        )
        db.add(regular)
        db.commit()
        db.add(SignoffRequest(progress_entry_id=regular.id, mentor_id=mentor.id))
        regular.status = "pending_signoff"
        db.commit()

        # And a jaarinsigne entry
        _entry(db, scout.id, 1, 0, "work_done")
        progress_svc.request_jaarinsigne_2026_signoff_members(
            db, scout.id, [mentor.id],
        )

        items = progress_svc.list_signoff_requests_grouped(db, mentor.id)
        # Should have 1 group + 1 individual
        groups = [it for it in items if isinstance(it, dict)]
        singles = [it for it in items if not isinstance(it, dict)]
        assert len(groups) == 1
        assert len(singles) == 1

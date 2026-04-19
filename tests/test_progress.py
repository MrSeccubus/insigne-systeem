import pytest

from insigne import progress as progress_svc
from insigne.models import ConfirmationToken, ProgressEntry, SignoffRejection, SignoffRequest, User


# ── helpers ──────────────────────────────────────────────────────────────────

def _active_user(db, email="scout@example.com", name="Scout Jan") -> User:
    user = User(email=email, name=name, status="active", password_hash="x")
    db.add(user)
    db.commit()
    return user


def _entry(db, user, *, badge_slug="cybersecurity", level_index=0, step_index=0, notes=None):
    e = ProgressEntry(
        user_id=user.id,
        badge_slug=badge_slug,
        level_index=level_index,
        step_index=step_index,
        notes=notes,
    )
    db.add(e)
    db.commit()
    return e


# ── list_progress ─────────────────────────────────────────────────────────────

class TestListProgress:
    def test_returns_own_entries(self, db):
        scout = _active_user(db)
        _entry(db, scout)
        assert len(progress_svc.list_progress(db, scout.id)) == 1

    def test_does_not_return_other_users_entries(self, db):
        scout = _active_user(db)
        other = _active_user(db, "other@example.com")
        _entry(db, other)
        assert progress_svc.list_progress(db, scout.id) == []

    def test_filter_by_badge_slug(self, db):
        scout = _active_user(db)
        _entry(db, scout, badge_slug="cybersecurity")
        _entry(db, scout, badge_slug="kantklossen", level_index=0, step_index=1)
        result = progress_svc.list_progress(db, scout.id, badge_slug="cybersecurity")
        assert all(e.badge_slug == "cybersecurity" for e in result)
        assert len(result) == 1

    def test_filter_by_status(self, db):
        scout = _active_user(db)
        e = _entry(db, scout)
        e.status = "signed_off"
        db.commit()
        _entry(db, scout, step_index=1)
        signed_off = progress_svc.list_progress(db, scout.id, status="signed_off")
        assert len(signed_off) == 1
        assert signed_off[0].status == "signed_off"

    def test_returns_newest_first(self, db):
        scout = _active_user(db)
        e1 = _entry(db, scout, step_index=0)
        e2 = _entry(db, scout, step_index=1)
        result = progress_svc.list_progress(db, scout.id)
        assert result[0].id == e2.id


# ── create_progress ───────────────────────────────────────────────────────────

class TestCreateProgress:
    def test_creates_entry(self, db):
        scout = _active_user(db)
        entry = progress_svc.create_progress(db, scout.id, badge_slug="cybersecurity", level_index=0, step_index=0)
        assert entry.id is not None
        assert entry.status == "in_progress"

    def test_stores_notes(self, db):
        scout = _active_user(db)
        entry = progress_svc.create_progress(
            db, scout.id, badge_slug="cybersecurity", level_index=0, step_index=0, notes="Zomerkamp"
        )
        assert entry.notes == "Zomerkamp"

    def test_allows_same_step_if_not_completed(self, db):
        scout = _active_user(db)
        progress_svc.create_progress(db, scout.id, badge_slug="cybersecurity", level_index=0, step_index=0)
        # Second entry for same step is allowed if first is not completed
        entry = progress_svc.create_progress(db, scout.id, badge_slug="cybersecurity", level_index=0, step_index=0)
        assert entry is not None

    def test_raises_conflict_if_step_already_completed(self, db):
        scout = _active_user(db)
        e = _entry(db, scout)
        e.status = "signed_off"
        db.commit()
        with pytest.raises(progress_svc.Conflict):
            progress_svc.create_progress(db, scout.id, badge_slug="cybersecurity", level_index=0, step_index=0)

    def test_different_steps_do_not_conflict(self, db):
        scout = _active_user(db)
        e = _entry(db, scout, step_index=0)
        e.status = "signed_off"
        db.commit()
        entry = progress_svc.create_progress(db, scout.id, badge_slug="cybersecurity", level_index=0, step_index=1)
        assert entry is not None


# ── get_progress ──────────────────────────────────────────────────────────────

class TestGetProgress:
    def test_returns_own_entry(self, db):
        scout = _active_user(db)
        e = _entry(db, scout)
        result = progress_svc.get_progress(db, scout.id, e.id)
        assert result.id == e.id

    def test_raises_not_found_for_wrong_user(self, db):
        scout = _active_user(db)
        other = _active_user(db, "other@example.com")
        e = _entry(db, other)
        with pytest.raises(progress_svc.NotFound):
            progress_svc.get_progress(db, scout.id, e.id)

    def test_raises_not_found_for_unknown_id(self, db):
        scout = _active_user(db)
        with pytest.raises(progress_svc.NotFound):
            progress_svc.get_progress(db, scout.id, "nonexistent-id")


# ── update_progress ───────────────────────────────────────────────────────────

class TestUpdateProgress:
    def test_updates_notes(self, db):
        scout = _active_user(db)
        e = _entry(db, scout, notes="old")
        result = progress_svc.update_progress(db, scout.id, e.id, notes="new")
        assert result.notes == "new"

    def test_allows_update_when_pending_signoff(self, db):
        scout = _active_user(db)
        e = _entry(db, scout)
        e.status = "pending_signoff"
        db.commit()
        result = progress_svc.update_progress(db, scout.id, e.id, notes="updated")
        assert result.notes == "updated"

    def test_raises_forbidden_when_completed(self, db):
        scout = _active_user(db)
        e = _entry(db, scout)
        e.status = "signed_off"
        db.commit()
        with pytest.raises(progress_svc.Forbidden):
            progress_svc.update_progress(db, scout.id, e.id, notes="updated")

    def test_raises_not_found_for_wrong_user(self, db):
        scout = _active_user(db)
        other = _active_user(db, "other@example.com")
        e = _entry(db, other)
        with pytest.raises(progress_svc.NotFound):
            progress_svc.update_progress(db, scout.id, e.id, notes="hacked")


# ── delete_progress ───────────────────────────────────────────────────────────

class TestDeleteProgress:
    def test_deletes_open_entry(self, db):
        scout = _active_user(db)
        e = _entry(db, scout)
        progress_svc.delete_progress(db, scout.id, e.id)
        assert db.query(ProgressEntry).filter_by(id=e.id).first() is None

    def test_deletes_pending_signoff_entry(self, db):
        scout = _active_user(db)
        e = _entry(db, scout)
        e.status = "pending_signoff"
        db.commit()
        progress_svc.delete_progress(db, scout.id, e.id)
        assert db.query(ProgressEntry).filter_by(id=e.id).first() is None

    def test_raises_forbidden_when_completed(self, db):
        scout = _active_user(db)
        e = _entry(db, scout)
        e.status = "signed_off"
        db.commit()
        with pytest.raises(progress_svc.Forbidden):
            progress_svc.delete_progress(db, scout.id, e.id)

    def test_raises_not_found_for_wrong_user(self, db):
        scout = _active_user(db)
        other = _active_user(db, "other@example.com")
        e = _entry(db, other)
        with pytest.raises(progress_svc.NotFound):
            progress_svc.delete_progress(db, scout.id, e.id)


# ── request_signoff ───────────────────────────────────────────────────────────

class TestRequestSignoff:
    def test_creates_signoff_request(self, db):
        scout = _active_user(db)
        mentor = _active_user(db, "mentor@example.com", "Leider Piet")
        e = _entry(db, scout)
        e.status = "work_done"
        db.commit()
        progress_svc.request_signoff(db, scout.id, e.id, "mentor@example.com")
        assert db.query(SignoffRequest).filter_by(progress_entry_id=e.id).count() == 1

    def test_sets_status_to_pending_signoff(self, db):
        scout = _active_user(db)
        _active_user(db, "mentor@example.com", "Leider Piet")
        e = _entry(db, scout)
        e.status = "work_done"
        db.commit()
        progress_svc.request_signoff(db, scout.id, e.id, "mentor@example.com")
        db.refresh(e)
        assert e.status == "pending_signoff"

    def test_creates_pending_user_for_unknown_mentor(self, db):
        scout = _active_user(db)
        e = _entry(db, scout)
        e.status = "work_done"
        db.commit()
        _, mentor, created = progress_svc.request_signoff(db, scout.id, e.id, "new@example.com")
        assert created is True
        assert mentor.status == "pending"

    def test_returns_created_false_for_existing_mentor(self, db):
        scout = _active_user(db)
        _active_user(db, "mentor@example.com")
        e = _entry(db, scout)
        e.status = "work_done"
        db.commit()
        _, mentor, created = progress_svc.request_signoff(db, scout.id, e.id, "mentor@example.com")
        assert created is False

    def test_normalises_mentor_email(self, db):
        scout = _active_user(db)
        e = _entry(db, scout)
        e.status = "work_done"
        db.commit()
        _, mentor, _ = progress_svc.request_signoff(db, scout.id, e.id, "  MENTOR@EXAMPLE.COM  ")
        assert mentor.email == "mentor@example.com"

    def test_multiple_mentors_can_be_invited(self, db):
        scout = _active_user(db)
        e = _entry(db, scout)
        e.status = "work_done"
        db.commit()
        progress_svc.request_signoff(db, scout.id, e.id, "mentor1@example.com")
        progress_svc.request_signoff(db, scout.id, e.id, "mentor2@example.com")
        assert db.query(SignoffRequest).filter_by(progress_entry_id=e.id).count() == 2

    def test_raises_conflict_if_mentor_already_invited(self, db):
        scout = _active_user(db)
        e = _entry(db, scout)
        e.status = "work_done"
        db.commit()
        progress_svc.request_signoff(db, scout.id, e.id, "mentor@example.com")
        with pytest.raises(progress_svc.Conflict):
            progress_svc.request_signoff(db, scout.id, e.id, "mentor@example.com")

    def test_raises_conflict_if_entry_completed(self, db):
        scout = _active_user(db)
        e = _entry(db, scout)
        e.status = "signed_off"
        db.commit()
        with pytest.raises(progress_svc.Conflict):
            progress_svc.request_signoff(db, scout.id, e.id, "mentor@example.com")

    def test_raises_not_found_for_wrong_user(self, db):
        scout = _active_user(db)
        other = _active_user(db, "other@example.com")
        e = _entry(db, other)
        with pytest.raises(progress_svc.NotFound):
            progress_svc.request_signoff(db, scout.id, e.id, "mentor@example.com")


# ── confirm_signoff ───────────────────────────────────────────────────────────

class TestConfirmSignoff:
    def _invite(self, db, scout, mentor, e):
        db.add(SignoffRequest(progress_entry_id=e.id, mentor_id=mentor.id))
        e.status = "pending_signoff"
        db.commit()

    def test_marks_entry_completed(self, db):
        scout = _active_user(db)
        mentor = _active_user(db, "mentor@example.com")
        e = _entry(db, scout)
        self._invite(db, scout, mentor, e)
        progress_svc.confirm_signoff(db, mentor.id, e.id)
        db.refresh(e)
        assert e.status == "signed_off"

    def test_records_signed_off_by(self, db):
        scout = _active_user(db)
        mentor = _active_user(db, "mentor@example.com")
        e = _entry(db, scout)
        self._invite(db, scout, mentor, e)
        progress_svc.confirm_signoff(db, mentor.id, e.id)
        db.refresh(e)
        assert e.signed_off_by_id == mentor.id

    def test_records_signed_off_at(self, db):
        scout = _active_user(db)
        mentor = _active_user(db, "mentor@example.com")
        e = _entry(db, scout)
        self._invite(db, scout, mentor, e)
        progress_svc.confirm_signoff(db, mentor.id, e.id)
        db.refresh(e)
        assert e.signed_off_at is not None

    def test_removes_all_signoff_requests(self, db):
        scout = _active_user(db)
        mentor = _active_user(db, "mentor@example.com")
        other_mentor = _active_user(db, "other@example.com")
        e = _entry(db, scout)
        self._invite(db, scout, mentor, e)
        db.add(SignoffRequest(progress_entry_id=e.id, mentor_id=other_mentor.id))
        db.commit()
        progress_svc.confirm_signoff(db, mentor.id, e.id)
        assert db.query(SignoffRequest).filter_by(progress_entry_id=e.id).count() == 0

    def test_raises_forbidden_if_not_invited(self, db):
        scout = _active_user(db)
        mentor = _active_user(db, "mentor@example.com")
        uninvited = _active_user(db, "uninvited@example.com")
        e = _entry(db, scout)
        self._invite(db, scout, mentor, e)
        with pytest.raises(progress_svc.Forbidden):
            progress_svc.confirm_signoff(db, uninvited.id, e.id)

    def test_raises_conflict_if_already_completed(self, db):
        scout = _active_user(db)
        mentor = _active_user(db, "mentor@example.com")
        e = _entry(db, scout)
        e.status = "signed_off"
        e.signed_off_by_id = mentor.id
        db.commit()
        with pytest.raises(progress_svc.Conflict):
            progress_svc.confirm_signoff(db, mentor.id, e.id)

    def test_raises_not_found_for_unknown_entry(self, db):
        mentor = _active_user(db, "mentor@example.com")
        with pytest.raises(progress_svc.NotFound):
            progress_svc.confirm_signoff(db, mentor.id, "nonexistent")


# ── cancel_signoff_requests ───────────────────────────────────────────────────

class TestCancelSignoffRequests:
    def _invite(self, db, scout, mentor, e):
        db.add(SignoffRequest(progress_entry_id=e.id, mentor_id=mentor.id))
        e.status = "pending_signoff"
        db.commit()

    def test_reverts_entry_to_work_done(self, db):
        scout = _active_user(db)
        mentor = _active_user(db, "mentor@example.com")
        e = _entry(db, scout)
        self._invite(db, scout, mentor, e)
        progress_svc.cancel_signoff_requests(db, scout.id, e.id)
        db.refresh(e)
        assert e.status == "work_done"

    def test_removes_all_signoff_requests(self, db):
        scout = _active_user(db)
        mentor1 = _active_user(db, "mentor1@example.com")
        mentor2 = _active_user(db, "mentor2@example.com")
        e = _entry(db, scout)
        self._invite(db, scout, mentor1, e)
        db.add(SignoffRequest(progress_entry_id=e.id, mentor_id=mentor2.id))
        db.commit()
        progress_svc.cancel_signoff_requests(db, scout.id, e.id)
        assert db.query(SignoffRequest).filter_by(progress_entry_id=e.id).count() == 0

    def test_raises_not_found_for_wrong_user(self, db):
        scout = _active_user(db)
        other = _active_user(db, "other@example.com")
        mentor = _active_user(db, "mentor@example.com")
        e = _entry(db, scout)
        self._invite(db, scout, mentor, e)
        with pytest.raises(progress_svc.NotFound):
            progress_svc.cancel_signoff_requests(db, other.id, e.id)

    def test_raises_forbidden_when_signed_off(self, db):
        scout = _active_user(db)
        mentor = _active_user(db, "mentor@example.com")
        e = _entry(db, scout)
        e.status = "signed_off"
        e.signed_off_by_id = mentor.id
        db.commit()
        with pytest.raises(progress_svc.Forbidden):
            progress_svc.cancel_signoff_requests(db, scout.id, e.id)

    def test_raises_conflict_when_not_pending(self, db):
        scout = _active_user(db)
        e = _entry(db, scout)
        e.status = "work_done"
        db.commit()
        with pytest.raises(progress_svc.Conflict):
            progress_svc.cancel_signoff_requests(db, scout.id, e.id)


# ── reject_signoff ───────────────────────────────────────────────────────────

class TestRejectSignoff:
    def _invite(self, db, scout, mentor, e):
        db.add(SignoffRequest(progress_entry_id=e.id, mentor_id=mentor.id))
        e.status = "pending_signoff"
        db.commit()

    def test_reverts_entry_to_work_done(self, db):
        scout = _active_user(db)
        mentor = _active_user(db, "mentor@example.com", "Leider Piet")
        e = _entry(db, scout)
        self._invite(db, scout, mentor, e)
        progress_svc.reject_signoff(db, mentor.id, e.id, "Nog niet af")
        db.refresh(e)
        assert e.status == "work_done"

    def test_creates_rejection_record(self, db):
        scout = _active_user(db)
        mentor = _active_user(db, "mentor@example.com", "Leider Piet")
        e = _entry(db, scout)
        self._invite(db, scout, mentor, e)
        progress_svc.reject_signoff(db, mentor.id, e.id, "Nog niet af")
        rejection = db.query(SignoffRejection).filter_by(progress_entry_id=e.id).first()
        assert rejection is not None
        assert rejection.message == "Nog niet af"
        assert rejection.mentor_name == "Leider Piet"

    def test_removes_all_signoff_requests(self, db):
        scout = _active_user(db)
        mentor = _active_user(db, "mentor@example.com", "Leider Piet")
        other_mentor = _active_user(db, "other@example.com", "Leider Klaas")
        e = _entry(db, scout)
        self._invite(db, scout, mentor, e)
        db.add(SignoffRequest(progress_entry_id=e.id, mentor_id=other_mentor.id))
        db.commit()
        progress_svc.reject_signoff(db, mentor.id, e.id, "Nog niet af")
        assert db.query(SignoffRequest).filter_by(progress_entry_id=e.id).count() == 0

    def test_reverts_to_work_done_even_with_multiple_mentors(self, db):
        scout = _active_user(db)
        mentor = _active_user(db, "mentor@example.com", "Leider Piet")
        other_mentor = _active_user(db, "other@example.com", "Leider Klaas")
        e = _entry(db, scout)
        self._invite(db, scout, mentor, e)
        db.add(SignoffRequest(progress_entry_id=e.id, mentor_id=other_mentor.id))
        db.commit()
        progress_svc.reject_signoff(db, mentor.id, e.id, "Nog niet af")
        db.refresh(e)
        assert e.status == "work_done"

    def test_raises_forbidden_if_not_invited(self, db):
        scout = _active_user(db)
        mentor = _active_user(db, "mentor@example.com")
        uninvited = _active_user(db, "uninvited@example.com")
        e = _entry(db, scout)
        self._invite(db, scout, mentor, e)
        with pytest.raises(progress_svc.Forbidden):
            progress_svc.reject_signoff(db, uninvited.id, e.id, "Nope")

    def test_raises_conflict_if_already_signed_off(self, db):
        scout = _active_user(db)
        mentor = _active_user(db, "mentor@example.com")
        e = _entry(db, scout)
        e.status = "signed_off"
        e.signed_off_by_id = mentor.id
        db.commit()
        with pytest.raises(progress_svc.Conflict):
            progress_svc.reject_signoff(db, mentor.id, e.id, "Te laat")

    def test_raises_not_found_for_unknown_entry(self, db):
        mentor = _active_user(db, "mentor@example.com")
        with pytest.raises(progress_svc.NotFound):
            progress_svc.reject_signoff(db, mentor.id, "nonexistent", "Nope")


# ── list_signoff_requests ─────────────────────────────────────────────────────

class TestListSignoffRequests:
    def test_returns_pending_requests_for_mentor(self, db):
        scout = _active_user(db)
        mentor = _active_user(db, "mentor@example.com")
        e = _entry(db, scout)
        db.add(SignoffRequest(progress_entry_id=e.id, mentor_id=mentor.id))
        e.status = "pending_signoff"
        db.commit()
        result = progress_svc.list_signoff_requests(db, mentor.id)
        assert len(result) == 1

    def test_excludes_completed_entries(self, db):
        scout = _active_user(db)
        mentor = _active_user(db, "mentor@example.com")
        e = _entry(db, scout)
        db.add(SignoffRequest(progress_entry_id=e.id, mentor_id=mentor.id))
        e.status = "signed_off"
        db.commit()
        assert progress_svc.list_signoff_requests(db, mentor.id) == []

    def test_does_not_return_other_mentors_requests(self, db):
        scout = _active_user(db)
        mentor = _active_user(db, "mentor@example.com")
        other = _active_user(db, "other@example.com")
        e = _entry(db, scout)
        db.add(SignoffRequest(progress_entry_id=e.id, mentor_id=other.id))
        e.status = "pending_signoff"
        db.commit()
        assert progress_svc.list_signoff_requests(db, mentor.id) == []


# ── list_previous_mentors ─────────────────────────────────────────────────────

class TestListPreviousMentors:
    def test_returns_mentors_who_signed_off(self, db):
        scout = _active_user(db)
        mentor = _active_user(db, "mentor@example.com")
        e = _entry(db, scout)
        e.status = "signed_off"
        e.signed_off_by_id = mentor.id
        db.commit()
        result = progress_svc.list_previous_mentors(db, scout.id)
        assert len(result) == 1
        assert result[0].id == mentor.id

    def test_deduplicates_mentors(self, db):
        scout = _active_user(db)
        mentor = _active_user(db, "mentor@example.com")
        for i in range(3):
            e = _entry(db, scout, step_index=i)
            e.status = "signed_off"
            e.signed_off_by_id = mentor.id
        db.commit()
        result = progress_svc.list_previous_mentors(db, scout.id)
        assert len(result) == 1

    def test_ordered_by_most_recent_first(self, db):
        from datetime import datetime, timedelta, timezone
        scout = _active_user(db)
        mentor1 = _active_user(db, "first@example.com")
        mentor2 = _active_user(db, "second@example.com")
        now = datetime.now(timezone.utc)
        e1 = _entry(db, scout, step_index=0)
        e1.status = "completed"
        e1.signed_off_by_id = mentor1.id
        e1.signed_off_at = now - timedelta(days=5)
        e2 = _entry(db, scout, step_index=1)
        e2.status = "completed"
        e2.signed_off_by_id = mentor2.id
        e2.signed_off_at = now - timedelta(days=1)
        db.commit()
        result = progress_svc.list_previous_mentors(db, scout.id)
        assert result[0].id == mentor2.id
        assert result[1].id == mentor1.id

    def test_returns_empty_for_no_signoffs(self, db):
        scout = _active_user(db)
        assert progress_svc.list_previous_mentors(db, scout.id) == []

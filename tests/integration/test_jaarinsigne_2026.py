"""Tests for the jaarinsigne_2026 service."""
import pytest

from insigne import jaarinsigne_2026 as svc
from insigne.models import (
    Jaarinsigne2026Inclusion,
    ProgressEntry,
    User,
)


# ── Helpers ───────────────────────────────────────────────────────────────────

def _user(db, email="scout@example.com", name="Scout"):
    u = User(email=email, name=name, status="active", password_hash="x")
    db.add(u)
    db.commit()
    return u


def _signed_off_entry(db, user_id, badge_slug, level_index, step_index):
    """Create a signed-off ProgressEntry."""
    e = ProgressEntry(
        user_id=user_id,
        badge_slug=badge_slug,
        level_index=level_index,
        step_index=step_index,
        status="signed_off",
    )
    db.add(e)
    db.commit()
    return e


def _in_progress_entry(db, user_id, badge_slug, level_index, step_index):
    """Create an in_progress ProgressEntry."""
    e = ProgressEntry(
        user_id=user_id,
        badge_slug=badge_slug,
        level_index=level_index,
        step_index=step_index,
        status="in_progress",
    )
    db.add(e)
    db.commit()
    return e


# ── toggle_inclusion ──────────────────────────────────────────────────────────

class TestToggleInclusion:
    def test_adds_row_when_absent(self, db):
        u = _user(db)
        result = svc.toggle_inclusion(db, u.id, "kamperen", 0, 0)
        assert result is True
        rows = db.query(Jaarinsigne2026Inclusion).filter_by(user_id=u.id).all()
        assert len(rows) == 1
        assert rows[0].badge_slug == "kamperen"
        assert rows[0].level_index == 0
        assert rows[0].step_index == 0

    def test_removes_row_when_present(self, db):
        u = _user(db)
        svc.toggle_inclusion(db, u.id, "kamperen", 0, 0)
        result = svc.toggle_inclusion(db, u.id, "kamperen", 0, 0)
        assert result is False
        rows = db.query(Jaarinsigne2026Inclusion).filter_by(user_id=u.id).all()
        assert len(rows) == 0

    def test_multiple_inclusions_coexist(self, db):
        u = _user(db)
        svc.toggle_inclusion(db, u.id, "kamperen", 0, 0)
        svc.toggle_inclusion(db, u.id, "kamperen", 0, 1)
        svc.toggle_inclusion(db, u.id, "knopen", 1, 0)
        rows = db.query(Jaarinsigne2026Inclusion).filter_by(user_id=u.id).all()
        assert len(rows) == 3

    def test_isolated_per_user(self, db):
        u1 = _user(db, "a@x.com", "A")
        u2 = _user(db, "b@x.com", "B")
        svc.toggle_inclusion(db, u1.id, "kamperen", 0, 0)
        rows_u2 = db.query(Jaarinsigne2026Inclusion).filter_by(user_id=u2.id).all()
        assert len(rows_u2) == 0


# ── compute_score ─────────────────────────────────────────────────────────────

class TestComputeScore:
    def test_empty_score_when_no_inclusions(self, db):
        u = _user(db)
        score = svc.compute_score(db, u.id)
        assert score["total_punten"] == 0
        assert score["total_groen"] == 0
        assert score["distinct_insignes"] == 0
        assert score["inclusions"] == []

    def test_counts_signed_off_inclusion(self, db):
        u = _user(db)
        _signed_off_entry(db, u.id, "kamperen", 0, 0)  # niveau 1 = 1 punt
        svc.toggle_inclusion(db, u.id, "kamperen", 0, 0)
        score = svc.compute_score(db, u.id)
        assert score["total_punten"] == 1
        assert score["distinct_insignes"] == 1
        assert len(score["inclusions"]) == 1

    def test_skips_non_signed_off_when_signed_off_only(self, db):
        u = _user(db)
        _in_progress_entry(db, u.id, "kamperen", 0, 0)
        svc.toggle_inclusion(db, u.id, "kamperen", 0, 0)
        score = svc.compute_score(db, u.id, signed_off_only=True)
        assert score["total_punten"] == 0
        assert len(score["inclusions"]) == 0

    def test_counts_non_signed_off_when_signed_off_only_false(self, db):
        u = _user(db)
        _in_progress_entry(db, u.id, "kamperen", 0, 0)
        svc.toggle_inclusion(db, u.id, "kamperen", 0, 0)
        score = svc.compute_score(db, u.id, signed_off_only=False)
        assert score["total_punten"] == 1

    def test_niveau2_counted(self, db):
        u = _user(db)
        _signed_off_entry(db, u.id, "kamperen", 0, 1)  # step_index=1 -> niveau 2
        svc.toggle_inclusion(db, u.id, "kamperen", 0, 1)
        score = svc.compute_score(db, u.id)
        assert score["total_punten"] == 2
        assert score["total_niveau2"] == 1
        assert score["total_niveau3"] == 0

    def test_niveau3_counted(self, db):
        u = _user(db)
        _signed_off_entry(db, u.id, "kamperen", 0, 2)  # step_index=2 -> niveau 3
        svc.toggle_inclusion(db, u.id, "kamperen", 0, 2)
        score = svc.compute_score(db, u.id)
        assert score["total_punten"] == 3
        assert score["total_niveau2"] == 1
        assert score["total_niveau3"] == 1

    def test_distinct_insignes_counts_badge_slugs(self, db):
        u = _user(db)
        _signed_off_entry(db, u.id, "kamperen", 0, 0)
        _signed_off_entry(db, u.id, "kamperen", 1, 0)
        _signed_off_entry(db, u.id, "knopen", 0, 0)
        svc.toggle_inclusion(db, u.id, "kamperen", 0, 0)
        svc.toggle_inclusion(db, u.id, "kamperen", 1, 0)
        svc.toggle_inclusion(db, u.id, "knopen", 0, 0)
        score = svc.compute_score(db, u.id)
        assert score["distinct_insignes"] == 2  # kamperen + knopen

    def test_total_punten_accumulates(self, db):
        u = _user(db)
        _signed_off_entry(db, u.id, "kamperen", 0, 0)  # 1 pt
        _signed_off_entry(db, u.id, "kamperen", 0, 1)  # 2 pts
        _signed_off_entry(db, u.id, "knopen", 0, 2)    # 3 pts
        svc.toggle_inclusion(db, u.id, "kamperen", 0, 0)
        svc.toggle_inclusion(db, u.id, "kamperen", 0, 1)
        svc.toggle_inclusion(db, u.id, "knopen", 0, 2)
        score = svc.compute_score(db, u.id)
        assert score["total_punten"] == 6


# ── compute_eis_status ────────────────────────────────────────────────────────

class TestComputeEisStatus:
    def _score(self, punten=0, groen=0, niveau2=0, niveau3=0, insignes=0):
        return {
            "total_punten": punten,
            "total_groen": groen,
            "total_niveau2": niveau2,
            "total_niveau3": niveau3,
            "distinct_insignes": insignes,
            "inclusions": [],
        }

    def test_none_drempel_returns_none(self):
        score = self._score(punten=10)
        assert svc.compute_eis_status(score, None) is None

    def test_punten_none_when_zero(self):
        score = self._score(punten=0)
        assert svc.compute_eis_status(score, {"type": "punten", "minimum": 5}) == "none"

    def test_punten_in_progress_below_minimum(self):
        score = self._score(punten=3)
        assert svc.compute_eis_status(score, {"type": "punten", "minimum": 5}) == "in_progress"

    def test_punten_work_done_at_minimum(self):
        score = self._score(punten=5)
        assert svc.compute_eis_status(score, {"type": "punten", "minimum": 5}) == "work_done"

    def test_punten_work_done_above_minimum(self):
        score = self._score(punten=8)
        assert svc.compute_eis_status(score, {"type": "punten", "minimum": 5}) == "work_done"

    def test_leiding_bepaald_uses_speltak_min(self):
        score = self._score(punten=3)
        assert svc.compute_eis_status(score, {"type": "leiding_bepaald"}, speltak_min_punten=3) == "work_done"

    def test_leiding_bepaald_in_progress(self):
        score = self._score(punten=2)
        assert svc.compute_eis_status(score, {"type": "leiding_bepaald"}, speltak_min_punten=3) == "in_progress"

    def test_groen_none_when_zero(self):
        score = self._score(groen=0)
        assert svc.compute_eis_status(score, {"type": "groen", "minimum": 1}) == "none"

    def test_groen_work_done_at_minimum(self):
        score = self._score(groen=1)
        assert svc.compute_eis_status(score, {"type": "groen", "minimum": 1}) == "work_done"

    def test_groen_in_progress_below_minimum(self):
        score = self._score(groen=1)
        assert svc.compute_eis_status(score, {"type": "groen", "minimum": 2}) == "in_progress"

    def test_niveau2_work_done(self):
        score = self._score(niveau2=1)
        assert svc.compute_eis_status(score, {"type": "niveau2", "minimum": 1}) == "work_done"

    def test_niveau3_none_when_zero(self):
        score = self._score(niveau3=0)
        assert svc.compute_eis_status(score, {"type": "niveau3", "minimum": 1}) == "none"

    def test_insignes_work_done(self):
        score = self._score(insignes=3)
        assert svc.compute_eis_status(score, {"type": "insignes", "minimum": 3}) == "work_done"

    def test_insignes_in_progress(self):
        score = self._score(insignes=1)
        assert svc.compute_eis_status(score, {"type": "insignes", "minimum": 2}) == "in_progress"


# ── update_progress_entries ───────────────────────────────────────────────────

class TestUpdateProgressEntries:
    def test_sets_in_progress_when_below_threshold(self, db):
        u = _user(db)
        # Include 1 signed-off eis at niveau 1 (1 punt) — scouts need 8 punten
        _signed_off_entry(db, u.id, "kamperen", 0, 0)
        svc.toggle_inclusion(db, u.id, "kamperen", 0, 0)
        svc.update_progress_entries(db, u.id, "scouts")
        entry = db.query(ProgressEntry).filter_by(
            user_id=u.id, badge_slug="jaarinsigne_2026"
        ).first()
        # Insignepunten eis: 1 punt, needs 8 -> in_progress
        assert entry is not None
        assert entry.status == "in_progress"

    def test_sets_work_done_when_threshold_met(self, db):
        u = _user(db)
        # Include 8 signed-off eisen at niveau 1 (each 1 punt = 8 total)
        for eis_idx in range(8):
            _signed_off_entry(db, u.id, "kamperen", eis_idx, 0)
            svc.toggle_inclusion(db, u.id, "kamperen", eis_idx, 0)
        svc.update_progress_entries(db, u.id, "scouts")
        # Find the "Insignepunten" entry (step_index=0, level_index=2 for scouts)
        entries = db.query(ProgressEntry).filter_by(
            user_id=u.id, badge_slug="jaarinsigne_2026"
        ).all()
        # At least the punten eis should be work_done
        punten_entry = next(
            (e for e in entries if e.step_index == 0 and e.level_index == 2), None
        )
        assert punten_entry is not None
        assert punten_entry.status == "work_done"

    def test_does_not_touch_signed_off_entry(self, db):
        u = _user(db)
        # Manually sign off the jaarinsigne_2026 eis
        signed_off = ProgressEntry(
            user_id=u.id,
            badge_slug="jaarinsigne_2026",
            level_index=2,
            step_index=0,
            status="signed_off",
        )
        db.add(signed_off)
        db.commit()
        # Include 1 punt (below 8 threshold for scouts)
        _signed_off_entry(db, u.id, "kamperen", 0, 0)
        svc.toggle_inclusion(db, u.id, "kamperen", 0, 0)
        svc.update_progress_entries(db, u.id, "scouts")
        db.refresh(signed_off)
        assert signed_off.status == "signed_off"

    def test_deletes_entry_when_status_is_none(self, db):
        u = _user(db)
        # Create an in_progress entry first
        existing = ProgressEntry(
            user_id=u.id,
            badge_slug="jaarinsigne_2026",
            level_index=2,
            step_index=0,
            status="in_progress",
        )
        db.add(existing)
        db.commit()
        # No inclusions -> score = 0 -> status "none" -> entry deleted
        svc.update_progress_entries(db, u.id, "scouts")
        remaining = db.query(ProgressEntry).filter_by(
            user_id=u.id,
            badge_slug="jaarinsigne_2026",
            level_index=2,
            step_index=0,
        ).first()
        assert remaining is None

    def test_noop_for_unknown_speltak(self, db):
        u = _user(db)
        # Should not raise; no entries created
        svc.update_progress_entries(db, u.id, "unknown_speltak")
        entries = db.query(ProgressEntry).filter_by(
            user_id=u.id, badge_slug="jaarinsigne_2026"
        ).all()
        assert entries == []

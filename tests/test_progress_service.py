"""Tests for leider-side progress service functions."""
import pytest

from insigne import groups as groups_svc
from insigne import progress as svc
from insigne.models import (
    Group,
    GroupMembership,
    ProgressEntry,
    Speltak,
    SpeltakMembership,
    User,
)


# ── Fixtures ──────────────────────────────────────────────────────────────────

def _user(db, email="user@example.com", name="User"):
    u = User(email=email, name=name, status="active", password_hash="x")
    db.add(u)
    db.commit()
    return u


def _group_and_speltak(db):
    g = groups_svc.create_group(db, name="G", slug="g")
    s = groups_svc.create_speltak(db, group_id=g.id, name="S", slug="s")
    return g, s


def _speltakleider(db, speltak_id, group_id, email="leider@example.com"):
    leider = _user(db, email=email, name="Leider")
    db.add(GroupMembership(user_id=leider.id, group_id=group_id, role="member", approved=True))
    db.add(SpeltakMembership(user_id=leider.id, speltak_id=speltak_id, role="speltakleider", approved=True))
    db.commit()
    return leider


def _scout(db, speltak_id, group_id, email=None, name="Scout"):
    scout = User(email=email, name=name, status="active")
    db.add(scout)
    db.flush()
    db.add(GroupMembership(user_id=scout.id, group_id=group_id, role="member", approved=True))
    db.add(SpeltakMembership(user_id=scout.id, speltak_id=speltak_id, role="scout", approved=True))
    db.commit()
    return scout


def _entry(db, user_id, status="in_progress", badge_slug="badge", level_index=0, step_index=0):
    e = ProgressEntry(
        user_id=user_id, badge_slug=badge_slug,
        level_index=level_index, step_index=step_index, status=status,
    )
    db.add(e)
    db.commit()
    return e


# ── list_progress_for_scouts ──────────────────────────────────────────────────

def test_list_progress_for_scouts_empty_list(db):
    assert svc.list_progress_for_scouts(db, []) == {}


def test_list_progress_for_scouts_correct_keying(db):
    g, s = _group_and_speltak(db)
    scout = _scout(db, s.id, g.id)
    e = _entry(db, scout.id, level_index=1, step_index=2)
    result = svc.list_progress_for_scouts(db, [scout.id])
    assert result[scout.id][("badge", 1, 2)].id == e.id


def test_list_progress_for_scouts_excludes_other_users(db):
    g, s = _group_and_speltak(db)
    s1 = _scout(db, s.id, g.id, email="s1@x.com")
    s2 = _scout(db, s.id, g.id, email="s2@x.com")
    _entry(db, s2.id, level_index=0, step_index=0)
    result = svc.list_progress_for_scouts(db, [s1.id])
    assert result[s1.id] == {}


# ── set_scout_progress ────────────────────────────────────────────────────────

def test_set_scout_progress_in_progress(db):
    g, s = _group_and_speltak(db)
    leider = _speltakleider(db, s.id, g.id)
    scout = _scout(db, s.id, g.id)
    entry = svc.set_scout_progress(db, leider_id=leider.id, scout_id=scout.id,
                                   speltak_id=s.id, badge_slug="b", level_index=0,
                                   step_index=0, status="in_progress")
    assert entry.status == "in_progress"
    assert entry.user_id == scout.id


def test_set_scout_progress_work_done(db):
    g, s = _group_and_speltak(db)
    leider = _speltakleider(db, s.id, g.id)
    scout = _scout(db, s.id, g.id)
    entry = svc.set_scout_progress(db, leider_id=leider.id, scout_id=scout.id,
                                   speltak_id=s.id, badge_slug="b", level_index=0,
                                   step_index=0, status="work_done")
    assert entry.status == "work_done"


def test_set_scout_progress_none_deletes_entry(db):
    g, s = _group_and_speltak(db)
    leider = _speltakleider(db, s.id, g.id)
    scout = _scout(db, s.id, g.id)
    _entry(db, scout.id)
    result = svc.set_scout_progress(db, leider_id=leider.id, scout_id=scout.id,
                                    speltak_id=s.id, badge_slug="badge", level_index=0,
                                    step_index=0, status="none")
    assert result is None
    assert db.query(ProgressEntry).filter_by(user_id=scout.id).count() == 0


def test_set_scout_progress_none_on_nonexistent_is_noop(db):
    g, s = _group_and_speltak(db)
    leider = _speltakleider(db, s.id, g.id)
    scout = _scout(db, s.id, g.id)
    result = svc.set_scout_progress(db, leider_id=leider.id, scout_id=scout.id,
                                    speltak_id=s.id, badge_slug="b", level_index=0,
                                    step_index=0, status="none")
    assert result is None


def test_set_scout_progress_signed_off_sets_attribution(db):
    g, s = _group_and_speltak(db)
    leider = _speltakleider(db, s.id, g.id)
    scout = _scout(db, s.id, g.id)
    result = svc.set_scout_progress(db, leider_id=leider.id, scout_id=scout.id,
                                    speltak_id=s.id, badge_slug="badge", level_index=0,
                                    step_index=0, status="signed_off")
    assert result.status == "signed_off"
    assert result.signed_off_by_id == leider.id
    assert result.signed_off_at is not None


def test_set_scout_progress_reverts_signed_off(db):
    g, s = _group_and_speltak(db)
    leider = _speltakleider(db, s.id, g.id)
    scout = _scout(db, s.id, g.id)
    e = _entry(db, scout.id, status="signed_off")
    e.signed_off_by_id = leider.id
    db.commit()
    result = svc.set_scout_progress(db, leider_id=leider.id, scout_id=scout.id,
                                    speltak_id=s.id, badge_slug="badge", level_index=0,
                                    step_index=0, status="work_done")
    assert result.status == "work_done"
    assert result.signed_off_by_id is None
    assert result.signed_off_at is None


def test_set_scout_progress_forbidden_non_leider(db):
    g, s = _group_and_speltak(db)
    outsider = _user(db, email="out@x.com")
    scout = _scout(db, s.id, g.id)
    with pytest.raises(svc.Forbidden, match="not_authorized"):
        svc.set_scout_progress(db, leider_id=outsider.id, scout_id=scout.id,
                               speltak_id=s.id, badge_slug="b", level_index=0,
                               step_index=0, status="in_progress")


def test_set_scout_progress_forbidden_self_edit(db):
    g, s = _group_and_speltak(db)
    leider = _speltakleider(db, s.id, g.id)
    with pytest.raises(svc.Forbidden, match="self_edit"):
        svc.set_scout_progress(db, leider_id=leider.id, scout_id=leider.id,
                               speltak_id=s.id, badge_slug="b", level_index=0,
                               step_index=0, status="in_progress")


def test_set_scout_progress_forbidden_scout_not_in_speltak(db):
    g, s = _group_and_speltak(db)
    leider = _speltakleider(db, s.id, g.id)
    outsider = _user(db, email="out@x.com")
    with pytest.raises(svc.Forbidden, match="scout_not_in_speltak"):
        svc.set_scout_progress(db, leider_id=leider.id, scout_id=outsider.id,
                               speltak_id=s.id, badge_slug="b", level_index=0,
                               step_index=0, status="in_progress")


def test_set_scout_progress_conflict_pending_signoff(db):
    g, s = _group_and_speltak(db)
    leider = _speltakleider(db, s.id, g.id)
    scout = _scout(db, s.id, g.id)
    _entry(db, scout.id, status="pending_signoff")
    with pytest.raises(svc.Conflict, match="pending_signoff"):
        svc.set_scout_progress(db, leider_id=leider.id, scout_id=scout.id,
                               speltak_id=s.id, badge_slug="badge", level_index=0,
                               step_index=0, status="work_done")


def test_set_scout_progress_invalid_status(db):
    g, s = _group_and_speltak(db)
    leider = _speltakleider(db, s.id, g.id)
    scout = _scout(db, s.id, g.id)
    with pytest.raises(ValueError, match="invalid_status"):
        svc.set_scout_progress(db, leider_id=leider.id, scout_id=scout.id,
                               speltak_id=s.id, badge_slug="b", level_index=0,
                               step_index=0, status="completely_invalid")


def test_set_scout_progress_groepsleider_can_also_edit(db):
    """Groepsleiders can also manage progress for scouts in their group's speltakken."""
    groepsleider = _user(db, email="gl@x.com")
    g = groups_svc.create_group(db, name="G", slug="g", created_by_id=groepsleider.id)
    s = groups_svc.create_speltak(db, group_id=g.id, name="S", slug="s")
    scout = _scout(db, s.id, g.id)
    entry = svc.set_scout_progress(db, leider_id=groepsleider.id, scout_id=scout.id,
                                   speltak_id=s.id, badge_slug="b", level_index=0,
                                   step_index=0, status="in_progress")
    assert entry.status == "in_progress"

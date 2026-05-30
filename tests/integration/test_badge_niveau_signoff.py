"""Mentor-inbox auto-grouping for per-eis sign-off requests that share a
``(scout, badge, niveau)`` triple (#102).

Per the design decision on #102, no new server-side batch endpoints exist —
the scout-side UI loops over the existing per-eis
``/progress/{entry_id}/request-signoff-*`` routes. The grouping is the one
piece of #102 that lives server-side: ``list_signoff_requests_grouped``
coalesces ≥ 2 sibling per-eis ``SignoffRequest`` rows into one
``badge_niveau_group`` dict so the mentor sees a single card."""
from insigne import groups as groups_svc
from insigne import progress as progress_svc
from insigne.models import (
    GroupMembership,
    ProgressEntry,
    SpeltakMembership,
    User,
)


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


def _speltak_with_leider(db, leider, scout):
    g = groups_svc.create_group(db, name="G", slug="g", created_by_id=leider.id)
    s = groups_svc.create_speltak(db, group_id=g.id, name="Welpen", slug="welpen",
                                  speltak_type="welpen")
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


class TestAutoGroupingBadgeNiveau:
    def test_two_or_more_siblings_form_a_group(self, db):
        """Two per-eis requests at the same (badge, niveau) coalesce."""
        scout = _user(db, "s@x.com")
        leider = _user(db, "l@x.com", "Leider")
        _, speltak = _speltak_with_leider(db, leider, scout)
        e1 = _entry(db, scout.id, "kamperen", 0, 0, "work_done")
        e2 = _entry(db, scout.id, "kamperen", 1, 0, "work_done")
        # Use the existing per-eis service to create the requests — same as
        # the new scout-side UI loop does.
        progress_svc.request_signoff_for_speltak(db, scout.id, e1.id, speltak.id)
        progress_svc.request_signoff_for_speltak(db, scout.id, e2.id, speltak.id)

        items = progress_svc.list_signoff_requests_grouped(db, leider.id)
        groups = [it for it in items if isinstance(it, dict)]
        assert len(groups) == 1
        g = groups[0]
        assert g["type"] == "badge_niveau_group"
        assert g["badge_slug"] == "kamperen"
        assert g["niveau_index"] == 0
        assert len(g["requests"]) == 2

    def test_singleton_per_eis_renders_as_plain_request(self, db):
        """A single per-eis invite (no batchable sibling) stays as a plain
        SignoffRequest item — current behaviour, no auto-wrapping into a
        one-element group."""
        scout = _user(db, "s@x.com")
        leider = _user(db, "l@x.com", "Leider")
        _, speltak = _speltak_with_leider(db, leider, scout)
        e = _entry(db, scout.id, "kamperen", 0, 0, "work_done")
        progress_svc.request_signoff_for_speltak(db, scout.id, e.id, speltak.id)

        items = progress_svc.list_signoff_requests_grouped(db, leider.id)
        groups = [it for it in items if isinstance(it, dict)]
        plain = [it for it in items if not isinstance(it, dict)]
        assert groups == []
        assert len(plain) == 1

    def test_different_niveaus_do_not_merge(self, db):
        """Requests at the same badge but different niveau (= step_index)
        do NOT coalesce — they're separate niveau cards."""
        scout = _user(db, "s@x.com")
        leider = _user(db, "l@x.com", "Leider")
        _, speltak = _speltak_with_leider(db, leider, scout)
        e1 = _entry(db, scout.id, "kamperen", 0, 0, "work_done")
        e2 = _entry(db, scout.id, "kamperen", 0, 1, "work_done")  # different niveau
        progress_svc.request_signoff_for_speltak(db, scout.id, e1.id, speltak.id)
        progress_svc.request_signoff_for_speltak(db, scout.id, e2.id, speltak.id)

        items = progress_svc.list_signoff_requests_grouped(db, leider.id)
        groups = [it for it in items if isinstance(it, dict)]
        plain = [it for it in items if not isinstance(it, dict)]
        assert groups == []
        assert len(plain) == 2

    def test_different_badges_do_not_merge(self, db):
        scout = _user(db, "s@x.com")
        leider = _user(db, "l@x.com", "Leider")
        _, speltak = _speltak_with_leider(db, leider, scout)
        e1 = _entry(db, scout.id, "kamperen", 0, 0, "work_done")
        e2 = _entry(db, scout.id, "sport_spel", 0, 0, "work_done")  # different badge
        progress_svc.request_signoff_for_speltak(db, scout.id, e1.id, speltak.id)
        progress_svc.request_signoff_for_speltak(db, scout.id, e2.id, speltak.id)

        items = progress_svc.list_signoff_requests_grouped(db, leider.id)
        groups = [it for it in items if isinstance(it, dict)]
        plain = [it for it in items if not isinstance(it, dict)]
        assert groups == []
        assert len(plain) == 2

    def test_jaarinsigne_still_takes_precedence(self, db):
        """Jaarinsigne_2026 requests use their own ``jaarinsigne_2026_group``
        type — they're never wrapped into a ``badge_niveau_group``."""
        scout = _user(db, "s@x.com")
        leider = _user(db, "l@x.com", "Leider")
        _, speltak = _speltak_with_leider(db, leider, scout)
        _entry(db, scout.id, "jaarinsigne_2026", 1, 0, "work_done")
        _entry(db, scout.id, "jaarinsigne_2026", 1, 1, "work_done")
        progress_svc.request_jaarinsigne_2026_signoff_speltak(
            db, scout.id, speltak.id,
        )

        items = progress_svc.list_signoff_requests_grouped(db, leider.id)
        groups = [it for it in items if isinstance(it, dict)]
        assert len(groups) == 1
        assert groups[0]["type"] == "jaarinsigne_2026_group"

"""User-controlled free-text fields are length-capped at the model layer, so
overlong display names / sign-off notes can't bloat rendered e-mails regardless
of which endpoint writes them (SQLite doesn't enforce column lengths)."""
from insigne.models import (
    MAX_FREETEXT_LENGTH,
    MAX_NAME_LENGTH,
    ProgressEntry,
    User,
)


def test_user_name_is_capped_on_assignment():
    u = User(email="x@example.com", name="a" * 5000, status="active")
    assert len(u.name) == MAX_NAME_LENGTH

    u.name = "b" * 5000  # also on later assignment
    assert len(u.name) == MAX_NAME_LENGTH


def test_user_name_none_and_short_untouched():
    assert User(email="x@example.com", name=None).name is None
    assert User(email="y@example.com", name="Jan").name == "Jan"


def test_progress_notes_and_mentor_comment_capped():
    e = ProgressEntry(user_id="u", badge_slug="b", level_index=0, step_index=0,
                      notes="n" * 9000, mentor_comment="m" * 9000)
    assert len(e.notes) == MAX_FREETEXT_LENGTH
    assert len(e.mentor_comment) == MAX_FREETEXT_LENGTH


def test_progress_notes_none_untouched():
    e = ProgressEntry(user_id="u", badge_slug="b", level_index=0, step_index=0)
    assert e.notes is None and e.mentor_comment is None


def test_cap_persists_through_the_orm(db):
    """The cap fires on the ORM attribute set, so the truncated value is what
    gets stored (verified via a round-trip)."""
    u = User(email="z@example.com", name="q" * 500, status="active")
    db.add(u)
    db.commit()
    db.refresh(u)
    assert len(u.name) == MAX_NAME_LENGTH

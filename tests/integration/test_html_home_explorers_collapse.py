"""Home-page rendering: the Explorers category section is collapsed (rendered
as ``<details>``) when the visitor isn't in an explorers speltak. (#110)"""
import re

from insigne.models import GroupMembership, SpeltakMembership, User
from insigne import groups as groups_svc
import insigne.auth as auth_svc


def _user_in_speltak(db, speltak_type: str, *, email: str | None = None):
    """Create a fresh user with a single active membership of the given speltak type."""
    email = email or f"{speltak_type}@example.com"
    g = groups_svc.create_group(db, name=f"G-{speltak_type}", slug=f"g-{speltak_type}")
    s = groups_svc.create_speltak(
        db, group_id=g.id, name=speltak_type.title(),
        slug=speltak_type, speltak_type=speltak_type,
    )
    u = User(email=email, name=speltak_type.title(), status="active", password_hash="x")
    db.add(u); db.flush()
    db.add(GroupMembership(user_id=u.id, group_id=g.id, role="member", approved=True))
    db.add(SpeltakMembership(user_id=u.id, speltak_id=s.id, role="scout", approved=True))
    db.commit()
    return u


def _token(user):
    token, _ = auth_svc.create_access_token(user.id)
    return token


_EXPLORERS_H2 = re.compile(r'<h2 class="section-header">\s*Explorers\s*</h2>')
_EXPLORERS_SUMMARY = re.compile(r'<summary class="section-header">\s*Explorers\s*</summary>')


class TestExplorersCategoryAutoCollapse:
    def test_explorers_speltak_member_sees_open_section(self, client, db):
        """A user whose primary speltak is `explorers` sees the Explorers
        category as a plain `<h2>` heading (always open, no disclosure)."""
        u = _user_in_speltak(db, "explorers")
        r = client.get("/", cookies={"access_token": _token(u)})
        assert r.status_code == 200
        assert _EXPLORERS_H2.search(r.text), "Explorers section should render as <h2> for explorer users"
        assert not _EXPLORERS_SUMMARY.search(r.text), "Explorers section should not be wrapped in <details>"

    def test_non_explorer_user_sees_collapsed_section(self, client, db):
        """A user in a non-explorers speltak sees the Explorers category
        wrapped in a `<details>` element (collapsed by default)."""
        u = _user_in_speltak(db, "welpen")
        r = client.get("/", cookies={"access_token": _token(u)})
        assert r.status_code == 200
        assert _EXPLORERS_SUMMARY.search(r.text), "Non-explorer should see <details><summary> for Explorers"
        assert not _EXPLORERS_H2.search(r.text), "Non-explorer should not see Explorers as plain <h2>"

    def test_anonymous_visitor_sees_open_section(self, client, db):
        """Anonymous visitors don't have a speltak type to scope this UX against
        — show them all categories open, including Explorers."""
        r = client.get("/")
        assert r.status_code == 200
        assert _EXPLORERS_H2.search(r.text), "Anonymous should see Explorers as plain <h2>"
        assert not _EXPLORERS_SUMMARY.search(r.text), "Anonymous should not see Explorers collapsed"

    def test_other_categories_unchanged(self, client, db):
        """The collapse logic only applies to the Explorers category — the
        Gewone insignes / Buitengewone insignes sections still render as
        plain `<h2>` for everyone."""
        u = _user_in_speltak(db, "welpen")
        r = client.get("/", cookies={"access_token": _token(u)})
        # The exact label depends on category_labels; "Gewone" is a stable token.
        assert re.search(r'<h2 class="section-header">\s*Gewone insignes\s*</h2>', r.text)

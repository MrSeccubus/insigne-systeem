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


def _login_as(client, user):
    """Set the access_token cookie on the client instance.

    Set cookies on the client instance, not per-request — httpx deprecates
    the per-request ``cookies=`` kwarg because the persistence semantics are
    ambiguous (does it stick? does it merge? does the session jar see it?).
    """
    token, _ = auth_svc.create_access_token(user.id)
    client.cookies.set("access_token", token)


_EXPLORERS_H2 = re.compile(r'<h2 class="section-header">\s*Explorers\s*</h2>')
_EXPLORERS_SUMMARY = re.compile(r'<summary class="section-header">\s*Explorers\s*</summary>')


class TestExplorersCategoryAutoCollapse:
    def test_explorers_speltak_member_sees_open_section(self, client, db):
        """A user whose primary speltak is `explorers` sees the Explorers
        category as a plain `<h2>` heading (always open, no disclosure)."""
        u = _user_in_speltak(db, "explorers")
        _login_as(client, u)
        r = client.get("/")
        assert r.status_code == 200
        assert _EXPLORERS_H2.search(r.text), "Explorers section should render as <h2> for explorer users"
        assert not _EXPLORERS_SUMMARY.search(r.text), "Explorers section should not be wrapped in <details>"

    def test_non_explorer_user_sees_collapsed_section(self, client, db):
        """A user in a non-explorers speltak sees the Explorers category
        wrapped in a `<details>` element (collapsed by default)."""
        u = _user_in_speltak(db, "welpen")
        _login_as(client, u)
        r = client.get("/")
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
        _login_as(client, u)
        r = client.get("/")
        # The exact label depends on category_labels; "Gewone" is a stable token.
        assert re.search(r'<h2 class="section-header">\s*Gewone insignes\s*</h2>', r.text)

    def test_explorer_with_higher_age_band_membership_still_sees_open(self, client, db):
        """A user who's an explorer AND a roverscout (parallel memberships)
        should still see the Explorers section open. Rule: any active
        explorers-typed membership wins, regardless of higher-age-band
        memberships."""
        u = _user_in_speltak(db, "roverscouts")  # primary speltak is roverscouts
        # Also add an explorers membership.
        g2 = groups_svc.create_group(db, name="G2", slug="g2")
        s2 = groups_svc.create_speltak(db, group_id=g2.id, name="Explorers",
                                       slug="explorers2", speltak_type="explorers")
        db.add(GroupMembership(user_id=u.id, group_id=g2.id, role="member", approved=True))
        db.add(SpeltakMembership(user_id=u.id, speltak_id=s2.id, role="scout", approved=True))
        db.commit()

        _login_as(client, u)
        r = client.get("/")
        assert r.status_code == 200
        assert _EXPLORERS_H2.search(r.text), \
            "User with parallel explorer membership should see Explorers open"
        assert not _EXPLORERS_SUMMARY.search(r.text)

    def test_speltakleider_of_explorers_sees_open(self, client, db):
        """A user whose only explorer-related membership is as speltakleider
        (no scout role anywhere) still counts as 'an explorer' for this UX."""
        g = groups_svc.create_group(db, name="GL", slug="gl")
        s = groups_svc.create_speltak(db, group_id=g.id, name="Explorers",
                                      slug="explorers-leider", speltak_type="explorers")
        u = User(email="leider@example.com", name="Leider", status="active", password_hash="x")
        db.add(u); db.flush()
        db.add(GroupMembership(user_id=u.id, group_id=g.id,
                               role="groepsleider", approved=True))
        db.add(SpeltakMembership(user_id=u.id, speltak_id=s.id,
                                 role="speltakleider", approved=True))
        db.commit()

        _login_as(client, u)
        r = client.get("/")
        assert r.status_code == 200
        assert _EXPLORERS_H2.search(r.text), \
            "Speltakleider of an explorers speltak should see Explorers open"
        assert not _EXPLORERS_SUMMARY.search(r.text)

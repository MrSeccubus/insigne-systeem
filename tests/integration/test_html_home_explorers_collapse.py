"""Home-page rendering: every category section is collapsible (rendered as
``<details><summary class="section-header">``); the Explorers section is the
only one whose default-open state depends on the visitor (#110)."""
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
    """Set the access_token cookie on the client instance (not per-request)."""
    token, _ = auth_svc.create_access_token(user.id)
    client.cookies.set("access_token", token)


# Each category section is a <details> wrapper with a <summary class="section-header">
# heading. The `open` attribute on the <details> tag drives the default state.
def _section_open(html: str, label: str) -> bool:
    return bool(re.search(
        rf'<details class="category-collapsible" open>\s*<summary class="section-header">\s*{re.escape(label)}\s*</summary>',
        html,
    ))


def _section_collapsed(html: str, label: str) -> bool:
    return bool(re.search(
        rf'<details class="category-collapsible">\s*<summary class="section-header">\s*{re.escape(label)}\s*</summary>',
        html,
    ))


class TestExplorersCategoryAutoCollapse:
    def test_explorers_speltak_member_sees_open_section(self, client, db):
        u = _user_in_speltak(db, "explorers")
        _login_as(client, u)
        r = client.get("/")
        assert r.status_code == 200
        assert _section_open(r.text, "Explorers")
        assert not _section_collapsed(r.text, "Explorers")

    def test_non_explorer_user_sees_collapsed_section(self, client, db):
        u = _user_in_speltak(db, "welpen")
        _login_as(client, u)
        r = client.get("/")
        assert r.status_code == 200
        assert _section_collapsed(r.text, "Explorers")
        assert not _section_open(r.text, "Explorers")

    def test_anonymous_visitor_sees_open_section(self, client, db):
        """Anonymous visitors don't have a speltak type to scope this UX
        against — Explorers (like everything else) open by default."""
        r = client.get("/")
        assert r.status_code == 200
        assert _section_open(r.text, "Explorers")

    def test_other_categories_are_collapsible_details_open_by_default(self, client, db):
        """Every category is now a collapsible <details><summary> pair;
        non-Explorers categories open by default for everyone."""
        u = _user_in_speltak(db, "welpen")
        _login_as(client, u)
        r = client.get("/")
        assert _section_open(r.text, "Gewone insignes")

    def test_explorer_with_higher_age_band_membership_still_sees_open(self, client, db):
        """Parallel memberships: any active explorer-typed membership wins,
        regardless of higher-age-band memberships."""
        u = _user_in_speltak(db, "roverscouts")
        g2 = groups_svc.create_group(db, name="G2", slug="g2")
        s2 = groups_svc.create_speltak(db, group_id=g2.id, name="Explorers",
                                       slug="explorers2", speltak_type="explorers")
        db.add(GroupMembership(user_id=u.id, group_id=g2.id, role="member", approved=True))
        db.add(SpeltakMembership(user_id=u.id, speltak_id=s2.id, role="scout", approved=True))
        db.commit()

        _login_as(client, u)
        r = client.get("/")
        assert r.status_code == 200
        assert _section_open(r.text, "Explorers")

    def test_non_explorer_with_explorer_favorite_sees_open(self, client, db):
        """A non-explorer who has favorited an Explorer-category badge sees
        the section open by default — favorites are another reason to want
        the section visible."""
        from insigne import users as users_svc
        from pathlib import Path
        from insigne.badges import BadgeCatalogue
        cat = BadgeCatalogue(Path(__file__).parent.parent.parent / "api" / "data")
        explorer_slugs = [b["slug"] for b in cat.list().get("explorers", [])]
        assert explorer_slugs, "Test setup: at least one explorer badge must exist"

        u = _user_in_speltak(db, "welpen")  # would otherwise collapse
        users_svc.toggle_user_favorite_badge(db, u.id, explorer_slugs[0])
        _login_as(client, u)
        r = client.get("/")
        assert r.status_code == 200
        assert _section_open(r.text, "Explorers")
        assert not _section_collapsed(r.text, "Explorers")

    def test_speltakleider_of_explorers_sees_open(self, client, db):
        """Speltakleider of an explorers-typed speltak (no scout role anywhere)
        still counts as 'an explorer' for this UX."""
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
        assert _section_open(r.text, "Explorers")

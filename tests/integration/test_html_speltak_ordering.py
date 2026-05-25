"""Rendering: speltakken in HTML listings are sorted by speltak_type_order
(bevers → plusscouts), then by name (#119)."""
import re

from insigne.models import GroupMembership, SpeltakMembership, User
from insigne import groups as groups_svc
import insigne.auth as auth_svc


def _group_with_speltakken_in_creation_order(db, name="Test", slug="test-grp"):
    """Make a group + speltakken created in *reverse* age order to verify the
    UI re-sorts on render (rather than depending on creation order)."""
    g = groups_svc.create_group(db, name=name, slug=slug)
    # Insert in reverse age order: plusscouts → bevers
    for st in ("plusscouts", "roverscouts", "explorers", "scouts", "welpen", "bevers"):
        groups_svc.create_speltak(
            db, group_id=g.id, name=st.title(), slug=f"{slug}-{st}",
            speltak_type=st,
        )
    db.commit()
    return g


class TestGroupDetailSpeltakOrder:
    def test_speltakken_render_in_age_order(self, client, db):
        # Groepsleider — has can_manage on the group, can view detail page.
        leider = User(email="leider@example.com", name="Leider",
                      status="active", password_hash="x")
        db.add(leider); db.commit()
        g = _group_with_speltakken_in_creation_order(db)
        db.add(GroupMembership(user_id=leider.id, group_id=g.id,
                               role="groepsleider", approved=True))
        db.commit()
        token, _ = auth_svc.create_access_token(leider.id)
        r = client.get(f"/groups/{g.slug}", cookies={"access_token": token})
        assert r.status_code == 200

        # Extract the order of speltak names as they appear in the speltakken list.
        # The list uses `<a href="/groups/<slug>/speltakken/<speltak.slug>">{name}</a>`.
        matches = re.findall(
            rf'<a href="/groups/{g.slug}/speltakken/[a-z0-9-]+">([A-Za-z]+)</a>',
            r.text,
        )
        # Filter to just the speltak names we created (drop breadcrumbs, etc).
        ours = [m for m in matches if m in {"Bevers", "Welpen", "Scouts",
                                             "Explorers", "Roverscouts", "Plusscouts"}]
        # Each appears once for this view; expect age order.
        assert ours == ["Bevers", "Welpen", "Scouts", "Explorers", "Roverscouts", "Plusscouts"], (
            f"Expected age-ordered speltakken; got: {ours}"
        )


class TestHomePageSpeltakOrder:
    def test_my_speltakken_panel_sorted_by_group_then_age(self, client, db):
        """The membership panel on the home page shows speltakken sorted by
        group name first, then by speltak_type_order, then by speltak name."""
        u = User(email="u@example.com", name="U", status="active", password_hash="x")
        db.add(u); db.commit()

        # Two groups: Beta (alphabetically second) and Alfa (first).
        for gname, gslug in [("Beta", "beta-grp"), ("Alfa", "alfa-grp")]:
            grp = groups_svc.create_group(db, name=gname, slug=gslug)
            db.add(GroupMembership(user_id=u.id, group_id=grp.id, role="member", approved=True))
            # Insert in reverse age order; UI should re-sort.
            for st in ("explorers", "welpen", "scouts", "bevers"):
                s = groups_svc.create_speltak(
                    db, group_id=grp.id, name=f"{gname}-{st}", slug=f"{gslug}-{st}",
                    speltak_type=st,
                )
                db.add(SpeltakMembership(user_id=u.id, speltak_id=s.id,
                                         role="scout", approved=True))
        db.commit()

        token, _ = auth_svc.create_access_token(u.id)
        r = client.get("/", cookies={"access_token": token})
        assert r.status_code == 200

        # Speltakken appear in the panel as: <span>{name} <span>— {group}</span></span>
        # Capture (name, group) pairs in document order.
        rows = re.findall(
            r"<span>([A-Za-z-]+) <span[^>]*>— ([A-Za-z]+)</span></span>",
            r.text,
        )
        rows = [row for row in rows if row[0].split("-")[0] in {"Alfa", "Beta"}]
        # Expect: Alfa group first (alphabetical), then within each group:
        # bevers → welpen → scouts → explorers (age order).
        assert rows == [
            ("Alfa-bevers", "Alfa"),
            ("Alfa-welpen", "Alfa"),
            ("Alfa-scouts", "Alfa"),
            ("Alfa-explorers", "Alfa"),
            ("Beta-bevers", "Beta"),
            ("Beta-welpen", "Beta"),
            ("Beta-scouts", "Beta"),
            ("Beta-explorers", "Beta"),
        ], f"Wrong order: {rows}"

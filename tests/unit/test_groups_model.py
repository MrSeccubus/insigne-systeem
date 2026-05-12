"""Tests for Group, Speltak, GroupMembership, SpeltakMembership, MembershipRequest models."""
from insigne.models import (
    Group,
    GroupMembership,
    MembershipRequest,
    Speltak,
    SpeltakMembership,
    User,
)


def _user(db, email="scout@example.com", name="Scout"):
    u = User(email=email, name=name, status="active", password_hash="x")
    db.add(u)
    db.commit()
    return u


def _group(db, name="Groep 1", slug="groep-1"):
    g = Group(name=name, slug=slug)
    db.add(g)
    db.commit()
    return g


def _speltak(db, group, name="Welpen", slug="welpen"):
    s = Speltak(group_id=group.id, name=name, slug=slug)
    db.add(s)
    db.commit()
    return s


# ── Group ─────────────────────────────────────────────────────────────────────

def test_group_create(db):
    g = _group(db)
    assert db.get(Group, g.id).name == "Groep 1"


def test_group_has_speltakken(db):
    g = _group(db)
    s1 = _speltak(db, g, name="Welpen", slug="welpen")
    s2 = _speltak(db, g, name="Scouts", slug="scouts")
    db.refresh(g)
    assert {s.slug for s in g.speltakken} == {"welpen", "scouts"}


def test_group_delete_cascades_to_speltakken(db):
    g = _group(db)
    s = _speltak(db, g)
    db.delete(g)
    db.commit()
    assert db.get(Speltak, s.id) is None


# ── Speltak ───────────────────────────────────────────────────────────────────

def test_speltak_belongs_to_group(db):
    g = _group(db)
    s = _speltak(db, g)
    assert s.group.slug == "groep-1"


# ── GroupMembership ───────────────────────────────────────────────────────────

def test_group_membership_groepsleider(db):
    user = _user(db)
    g = _group(db)
    m = GroupMembership(user_id=user.id, group_id=g.id, role="groepsleider", approved=True)
    db.add(m)
    db.commit()
    db.refresh(g)
    assert g.memberships[0].role == "groepsleider"
    assert g.memberships[0].approved is True


def test_group_membership_deleted_with_user(db):
    user = _user(db)
    g = _group(db)
    m = GroupMembership(user_id=user.id, group_id=g.id, role="member", approved=True)
    db.add(m)
    db.commit()
    mid = m.id
    db.delete(user)
    db.commit()
    assert db.get(GroupMembership, mid) is None


# ── SpeltakMembership ─────────────────────────────────────────────────────────

def test_speltak_membership_scout(db):
    user = _user(db)
    g = _group(db)
    s = _speltak(db, g)
    sm = SpeltakMembership(user_id=user.id, speltak_id=s.id, role="scout", approved=True)
    db.add(sm)
    db.commit()
    db.refresh(user)
    assert len(user.speltak_memberships) == 1
    assert user.speltak_memberships[0].role == "scout"


def test_user_can_be_speltakleider_and_scout_in_different_speltakken(db):
    user = _user(db)
    g = _group(db)
    s1 = _speltak(db, g, name="Welpen", slug="welpen")
    s2 = _speltak(db, g, name="Scouts", slug="scouts")
    db.add(SpeltakMembership(user_id=user.id, speltak_id=s1.id, role="speltakleider", approved=True))
    db.add(SpeltakMembership(user_id=user.id, speltak_id=s2.id, role="scout", approved=True))
    db.commit()
    db.refresh(user)
    roles = {sm.role for sm in user.speltak_memberships}
    assert roles == {"speltakleider", "scout"}


# ── MembershipRequest ─────────────────────────────────────────────────────────

def test_membership_request_for_group(db):
    user = _user(db)
    g = _group(db)
    req = MembershipRequest(user_id=user.id, group_id=g.id, status="pending")
    db.add(req)
    db.commit()
    db.refresh(g)
    assert g.membership_requests[0].status == "pending"


def test_membership_request_for_speltak(db):
    user = _user(db)
    g = _group(db)
    s = _speltak(db, g)
    req = MembershipRequest(user_id=user.id, speltak_id=s.id, status="pending")
    db.add(req)
    db.commit()
    db.refresh(s)
    assert s.membership_requests[0].status == "pending"


def test_membership_request_approval(db):
    reviewer = _user(db, email="leader@example.com")
    scout = _user(db, email="scout@example.com")
    g = _group(db)
    req = MembershipRequest(user_id=scout.id, group_id=g.id, status="pending")
    db.add(req)
    db.commit()
    req.status = "approved"
    req.reviewed_by_id = reviewer.id
    db.commit()
    assert db.get(MembershipRequest, req.id).status == "approved"


# ── Emailless scout ───────────────────────────────────────────────────────────

def test_emailless_scout_created_by_leider(db):
    leider = _user(db, email="leider@example.com")
    scout = User(email=None, name="Anonieme Scout", status="active", created_by_id=leider.id)
    db.add(scout)
    db.commit()
    assert scout.email is None
    assert scout.created_by.email == "leider@example.com"
    db.refresh(leider)
    assert leider.managed_scouts[0].name == "Anonieme Scout"

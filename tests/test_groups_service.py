"""Tests for the insigne.groups service layer."""
import pytest

from insigne import groups as svc
from insigne.models import Group, GroupMembership, Speltak, SpeltakMembership, User


def _user(db, email="user@example.com", name="User", is_admin_email=False):
    u = User(email=email, name=name, status="active", password_hash="x")
    db.add(u)
    db.commit()
    return u


def _admin_user(db):
    from insigne.config import config
    email = "admin@example.com"
    if email not in config.admins:
        config.admins.append(email)
    u = User(email=email, name="Admin", status="active", password_hash="x")
    db.add(u)
    db.commit()
    return u


# ── Group CRUD ────────────────────────────────────────────────────────────────

def test_create_group_auto_groepsleider(db):
    user = _user(db)
    g = svc.create_group(db, name="Groep 1", slug="groep-1", created_by_id=user.id)
    assert g.slug == "groep-1"
    role = svc.get_group_role(db, user.id, g.id)
    assert role == "groepsleider"


def test_create_group_without_creator(db):
    g = svc.create_group(db, name="Groep 2", slug="groep-2")
    assert svc.get_group(db, g.id) is not None


def test_get_group_by_slug(db):
    svc.create_group(db, name="Groep X", slug="groep-x")
    g = svc.get_group_by_slug(db, "groep-x")
    assert g is not None
    assert g.name == "Groep X"


def test_get_group_by_slug_not_found(db):
    assert svc.get_group_by_slug(db, "nonexistent") is None


def test_list_groups_ordered_by_name(db):
    svc.create_group(db, name="Zwolle", slug="zwolle")
    svc.create_group(db, name="Amsterdam", slug="amsterdam")
    names = [g.name for g in svc.list_groups(db)]
    assert names == ["Amsterdam", "Zwolle"]


def test_update_group(db):
    g = svc.create_group(db, name="Oud", slug="oud")
    svc.update_group(db, g, name="Nieuw", slug="nieuw")
    assert svc.get_group_by_slug(db, "nieuw") is not None
    assert svc.get_group_by_slug(db, "oud") is None


def test_delete_group(db):
    g = svc.create_group(db, name="Te verwijderen", slug="weg")
    gid = g.id
    svc.delete_group(db, g)
    assert svc.get_group(db, gid) is None


# ── Speltak CRUD ──────────────────────────────────────────────────────────────

def test_create_and_get_speltak(db):
    g = svc.create_group(db, name="G", slug="g")
    s = svc.create_speltak(db, group_id=g.id, name="Welpen", slug="welpen")
    assert svc.get_speltak(db, s.id) is not None
    assert svc.get_speltak_by_slug(db, g.id, "welpen") is not None


def test_update_speltak(db):
    g = svc.create_group(db, name="G", slug="g")
    s = svc.create_speltak(db, group_id=g.id, name="Oud", slug="oud")
    svc.update_speltak(db, s, name="Nieuw", slug="nieuw")
    assert svc.get_speltak_by_slug(db, g.id, "nieuw") is not None


def test_delete_speltak(db):
    g = svc.create_group(db, name="G", slug="g")
    s = svc.create_speltak(db, group_id=g.id, name="S", slug="s")
    sid = s.id
    svc.delete_speltak(db, s)
    assert svc.get_speltak(db, sid) is None


# ── Authorization ─────────────────────────────────────────────────────────────

def test_can_manage_group_as_groepsleider(db):
    user = _user(db)
    g = svc.create_group(db, name="G", slug="g", created_by_id=user.id)
    assert svc.can_manage_group(user, db, g.id) is True


def test_cannot_manage_group_as_non_member(db):
    user = _user(db)
    other = _user(db, email="other@example.com")
    g = svc.create_group(db, name="G", slug="g", created_by_id=user.id)
    assert svc.can_manage_group(other, db, g.id) is False


def test_can_manage_group_as_admin(db):
    admin = _admin_user(db)
    g = svc.create_group(db, name="G", slug="g")
    assert svc.can_manage_group(admin, db, g.id) is True


def test_can_manage_speltak_as_speltakleider(db):
    user = _user(db)
    g = svc.create_group(db, name="G", slug="g")
    s = svc.create_speltak(db, group_id=g.id, name="S", slug="s")
    svc.set_speltak_role(db, user_id=user.id, speltak_id=s.id, role="speltakleider")
    assert svc.can_manage_speltak(user, db, s.id) is True


def test_can_manage_speltak_as_groepsleider(db):
    user = _user(db)
    g = svc.create_group(db, name="G", slug="g", created_by_id=user.id)
    s = svc.create_speltak(db, group_id=g.id, name="S", slug="s")
    assert svc.can_manage_speltak(user, db, s.id) is True


def test_cannot_manage_speltak_as_scout(db):
    user = _user(db)
    g = svc.create_group(db, name="G", slug="g")
    s = svc.create_speltak(db, group_id=g.id, name="S", slug="s")
    svc.set_speltak_role(db, user_id=user.id, speltak_id=s.id, role="scout")
    assert svc.can_manage_speltak(user, db, s.id) is False


# ── Membership ────────────────────────────────────────────────────────────────

def test_set_group_role_upserts(db):
    user = _user(db)
    g = svc.create_group(db, name="G", slug="g")
    svc.set_group_role(db, user_id=user.id, group_id=g.id, role="member")
    svc.set_group_role(db, user_id=user.id, group_id=g.id, role="groepsleider")
    members = svc.list_group_members(db, g.id)
    assert len(members) == 1
    assert members[0].role == "groepsleider"


def test_remove_group_member(db):
    user = _user(db)
    g = svc.create_group(db, name="G", slug="g", created_by_id=user.id)
    svc.remove_group_member(db, user_id=user.id, group_id=g.id)
    assert svc.list_group_members(db, g.id) == []


def test_set_speltak_role_upserts(db):
    user = _user(db)
    g = svc.create_group(db, name="G", slug="g")
    s = svc.create_speltak(db, group_id=g.id, name="S", slug="s")
    svc.set_speltak_role(db, user_id=user.id, speltak_id=s.id, role="scout")
    svc.set_speltak_role(db, user_id=user.id, speltak_id=s.id, role="speltakleider")
    members = svc.list_speltak_members(db, s.id)
    assert len(members) == 1
    assert members[0].role == "speltakleider"


def test_transfer_scout(db):
    user = _user(db)
    g = svc.create_group(db, name="G", slug="g")
    s1 = svc.create_speltak(db, group_id=g.id, name="A", slug="a")
    s2 = svc.create_speltak(db, group_id=g.id, name="B", slug="b")
    svc.set_speltak_role(db, user_id=user.id, speltak_id=s1.id, role="scout")
    svc.transfer_scout(db, user_id=user.id, from_speltak_id=s1.id, to_speltak_id=s2.id)
    assert svc.list_speltak_members(db, s1.id) == []
    assert len(svc.list_speltak_members(db, s2.id)) == 1


# ── Emailless scout ───────────────────────────────────────────────────────────

def test_create_emailless_scout(db):
    leider = _user(db, email="leider@example.com")
    scout = svc.create_emailless_scout(db, name="Piet", created_by_id=leider.id)
    assert scout.email is None
    assert scout.name == "Piet"
    assert scout.status == "active"

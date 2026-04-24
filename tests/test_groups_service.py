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


def test_name_to_slug_basic(db):
    assert svc.name_to_slug("Groep Amsterdam") == "groep-amsterdam"


def test_name_to_slug_diacritics(db):
    assert svc.name_to_slug("Spültàk Ë") == "spultak-e"


def test_name_to_slug_special_chars(db):
    assert svc.name_to_slug("Groep & Zonen!") == "groep-zonen"


def test_name_to_slug_empty_fallback(db):
    assert svc.name_to_slug("!!!") == "groep"


def test_unique_speltak_slug_no_collision(db):
    g = svc.create_group(db, name="G", slug="g")
    assert svc.unique_speltak_slug(db, g.id, "welpen") == "welpen"


def test_unique_speltak_slug_collision(db):
    g = svc.create_group(db, name="G", slug="g")
    svc.create_speltak(db, group_id=g.id, name="Welpen", slug="welpen")
    assert svc.unique_speltak_slug(db, g.id, "welpen") == "welpen-2"


def test_unique_speltak_slug_same_name_different_groups(db):
    g1 = svc.create_group(db, name="G1", slug="g1")
    g2 = svc.create_group(db, name="G2", slug="g2")
    svc.create_speltak(db, group_id=g1.id, name="Welpen", slug="welpen")
    assert svc.unique_speltak_slug(db, g2.id, "welpen") == "welpen"


def test_unique_group_slug_no_collision(db):
    assert svc.unique_group_slug(db, "groep-a") == "groep-a"


def test_unique_group_slug_single_collision(db):
    svc.create_group(db, name="G", slug="groep-a")
    assert svc.unique_group_slug(db, "groep-a") == "groep-a-2"


def test_unique_group_slug_multiple_collisions(db):
    svc.create_group(db, name="G1", slug="groep-a")
    svc.create_group(db, name="G2", slug="groep-a-2")
    svc.create_group(db, name="G3", slug="groep-a-3")
    assert svc.unique_group_slug(db, "groep-a") == "groep-a-4"


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

def test_activate_account_approves_pending_memberships(db):
    from insigne import users as users_svc
    from insigne.models import GroupMembership
    g = svc.create_group(db, name="G", slug="g")
    code, _, pending_user = users_svc.start_registration(db, "invite@example.com")
    db.add(GroupMembership(user_id=pending_user.id, group_id=g.id,
                           role="groepsleider", approved=False))
    db.commit()
    setup_token = users_svc.confirm_email(db, code)
    users_svc.activate_account(db, setup_token, password="password123", name="Invited")
    db.refresh(pending_user)
    assert svc.can_manage_group(pending_user, db, g.id) is True


def test_list_groups_for_user_groepsleider(db):
    user = _user(db)
    g = svc.create_group(db, name="G", slug="g", created_by_id=user.id)
    svc.create_group(db, name="Other", slug="other")
    result = svc.list_groups_for_user(db, user)
    assert [x.id for x in result] == [g.id]


def test_list_groups_for_user_speltakleider(db):
    user = _user(db)
    g = svc.create_group(db, name="G", slug="g")
    s = svc.create_speltak(db, group_id=g.id, name="S", slug="s")
    svc.set_speltak_role(db, user_id=user.id, speltak_id=s.id, role="speltakleider")
    svc.create_group(db, name="Other", slug="other")
    result = svc.list_groups_for_user(db, user)
    assert [x.id for x in result] == [g.id]


def test_list_groups_for_user_scout_sees_nothing(db):
    user = _user(db)
    g = svc.create_group(db, name="G", slug="g")
    s = svc.create_speltak(db, group_id=g.id, name="S", slug="s")
    svc.set_speltak_role(db, user_id=user.id, speltak_id=s.id, role="scout")
    assert svc.list_groups_for_user(db, user) == []


def test_list_groups_for_user_admin_sees_all(db):
    admin = _admin_user(db)
    svc.create_group(db, name="G1", slug="g1")
    svc.create_group(db, name="G2", slug="g2")
    assert len(svc.list_groups_for_user(db, admin)) == 2


def test_create_emailless_scout(db):
    leider = _user(db, email="leider@example.com")
    scout = svc.create_emailless_scout(db, name="Piet", created_by_id=leider.id)
    assert scout.email is None
    assert scout.name == "Piet"
    assert scout.status == "active"


# ── list_active_memberships_for_user ─────────────────────────────────────────

def test_list_active_memberships_returns_group_and_speltak(db):
    user = _user(db)
    g = svc.create_group(db, name="G", slug="g", created_by_id=user.id)
    s = svc.create_speltak(db, group_id=g.id, name="S", slug="s")
    svc.set_speltak_role(db, user_id=user.id, speltak_id=s.id, role="scout")
    gm, sm = svc.list_active_memberships_for_user(db, user.id)
    assert any(m.group_id == g.id for m in gm)
    assert any(m.speltak_id == s.id for m in sm)


def test_list_active_memberships_excludes_withdrawn(db):
    user = _user(db)
    g = svc.create_group(db, name="G", slug="g", created_by_id=user.id)
    svc.remove_group_member(db, user_id=user.id, group_id=g.id)
    gm, sm = svc.list_active_memberships_for_user(db, user.id)
    assert gm == []
    assert sm == []


# ── list_members_without_speltak ─────────────────────────────────────────────

def test_list_members_without_speltak(db):
    leider = _user(db, email="leider@example.com")
    scout = _user(db, email="scout@example.com")
    g = svc.create_group(db, name="G", slug="g", created_by_id=leider.id)
    svc.set_group_role(db, user_id=scout.id, group_id=g.id, role="member")
    result = svc.list_members_without_speltak(db, g.id)
    assert any(m.user_id == scout.id for m in result)
    assert not any(m.user_id == leider.id for m in result)


def test_list_members_without_speltak_excludes_speltak_member(db):
    leider = _user(db, email="leider@example.com")
    scout = _user(db, email="scout@example.com")
    g = svc.create_group(db, name="G", slug="g", created_by_id=leider.id)
    s = svc.create_speltak(db, group_id=g.id, name="S", slug="s")
    svc.set_speltak_role(db, user_id=scout.id, speltak_id=s.id, role="scout")
    result = svc.list_members_without_speltak(db, g.id)
    assert not any(m.user_id == scout.id for m in result)


# ── cancel_membership_request / cancel_all ───────────────────────────────────

def test_cancel_membership_request_removes_it(db):
    scout = _user(db, email="scout@example.com")
    g = svc.create_group(db, name="G", slug="g")
    req = svc.create_membership_request(db, user_id=scout.id, group_id=g.id)
    svc.cancel_membership_request(db, request_id=req.id, user_id=scout.id)
    from insigne.models import MembershipRequest
    assert db.query(MembershipRequest).filter_by(id=req.id).first() is None


def test_cancel_membership_request_ignores_wrong_user(db):
    scout = _user(db, email="scout@example.com")
    other = _user(db, email="other@example.com")
    g = svc.create_group(db, name="G", slug="g")
    req = svc.create_membership_request(db, user_id=scout.id, group_id=g.id)
    svc.cancel_membership_request(db, request_id=req.id, user_id=other.id)
    from insigne.models import MembershipRequest
    assert db.query(MembershipRequest).filter_by(id=req.id).first() is not None


def test_cancel_all_membership_requests(db):
    scout = _user(db, email="scout@example.com")
    g1 = svc.create_group(db, name="G1", slug="g1")
    g2 = svc.create_group(db, name="G2", slug="g2")
    svc.create_membership_request(db, user_id=scout.id, group_id=g1.id)
    svc.create_membership_request(db, user_id=scout.id, group_id=g2.id)
    svc.cancel_all_membership_requests(db, user_id=scout.id)
    from insigne.models import MembershipRequest
    assert db.query(MembershipRequest).filter_by(user_id=scout.id).count() == 0


# ── list_all_pending_requests_for_leader / group_pending_requests ─────────────

def test_list_all_pending_requests_for_leader(db):
    leider = _user(db, email="leider@example.com")
    scout = _user(db, email="scout@example.com")
    g = svc.create_group(db, name="G", slug="g", created_by_id=leider.id)
    svc.create_membership_request(db, user_id=scout.id, group_id=g.id)
    result = svc.list_all_pending_requests_for_leader(db, leider.id)
    assert len(result) == 1
    assert result[0].user_id == scout.id


def test_list_all_pending_requests_excludes_other_groups(db):
    leider = _user(db, email="leider@example.com")
    scout = _user(db, email="scout@example.com")
    other_g = svc.create_group(db, name="Other", slug="other")
    svc.create_membership_request(db, user_id=scout.id, group_id=other_g.id)
    result = svc.list_all_pending_requests_for_leader(db, leider.id)
    assert result == []


def test_group_pending_requests_groups_by_group_and_speltak(db):
    leider = _user(db, email="leider@example.com")
    scout1 = _user(db, email="scout1@example.com")
    scout2 = _user(db, email="scout2@example.com")
    g = svc.create_group(db, name="G", slug="g", created_by_id=leider.id)
    s = svc.create_speltak(db, group_id=g.id, name="S", slug="s")
    svc.create_membership_request(db, user_id=scout1.id, group_id=g.id)
    svc.create_membership_request(db, user_id=scout2.id, group_id=g.id, speltak_id=s.id)
    flat = svc.list_all_pending_requests_for_leader(db, leider.id)
    grouped = svc.group_pending_requests(flat)
    assert len(grouped) == 1
    assert grouped[0]["group"].id == g.id
    speltakken = grouped[0]["speltakken"]
    assert len(speltakken) == 2
    no_speltak = next(x for x in speltakken if x["speltak"] is None)
    with_speltak = next(x for x in speltakken if x["speltak"] is not None)
    assert len(no_speltak["requests"]) == 1
    assert with_speltak["speltak"].id == s.id


# ── User.is_leader ────────────────────────────────────────────────────────────

def test_is_leader_true_for_groepsleider(db):
    user = _user(db)
    g = svc.create_group(db, name="G", slug="g", created_by_id=user.id)
    db.refresh(user)
    assert user.is_leader is True


def test_is_leader_true_for_speltakleider(db):
    user = _user(db)
    g = svc.create_group(db, name="G", slug="g")
    s = svc.create_speltak(db, group_id=g.id, name="S", slug="s")
    svc.set_speltak_role(db, user_id=user.id, speltak_id=s.id, role="speltakleider")
    db.refresh(user)
    assert user.is_leader is True


def test_is_leader_false_for_scout(db):
    user = _user(db)
    g = svc.create_group(db, name="G", slug="g")
    s = svc.create_speltak(db, group_id=g.id, name="S", slug="s")
    svc.set_speltak_role(db, user_id=user.id, speltak_id=s.id, role="scout")
    db.refresh(user)
    assert user.is_leader is False


def test_is_leader_false_for_non_member(db):
    user = _user(db)
    assert user.is_leader is False


# ── transfer_scout: destination already has user ──────────────────────────────

def test_transfer_scout_when_already_in_destination(db):
    user = _user(db)
    g = svc.create_group(db, name="G", slug="g")
    s1 = svc.create_speltak(db, group_id=g.id, name="A", slug="a")
    s2 = svc.create_speltak(db, group_id=g.id, name="B", slug="b")
    svc.set_speltak_role(db, user_id=user.id, speltak_id=s1.id, role="scout")
    svc.set_speltak_role(db, user_id=user.id, speltak_id=s2.id, role="scout")
    svc.transfer_scout(db, user_id=user.id, from_speltak_id=s1.id, to_speltak_id=s2.id)
    assert svc.list_speltak_members(db, s1.id) == []
    assert len(svc.list_speltak_members(db, s2.id)) == 1


def test_transfer_scout_preserves_group_membership(db):
    user = _user(db)
    g = svc.create_group(db, name="G", slug="g")
    s1 = svc.create_speltak(db, group_id=g.id, name="A", slug="a")
    s2 = svc.create_speltak(db, group_id=g.id, name="B", slug="b")
    # Real membership flow: group membership + speltak membership are both created
    svc.set_group_role(db, user_id=user.id, group_id=g.id, role="member")
    svc.set_speltak_role(db, user_id=user.id, speltak_id=s1.id, role="scout")
    svc.transfer_scout(db, user_id=user.id, from_speltak_id=s1.id, to_speltak_id=s2.id)
    group_members = svc.list_group_members(db, g.id)
    assert any(m.user_id == user.id for m in group_members)


# ── preview_scout_merge ───────────────────────────────────────────────────────

def test_preview_scout_merge_added(db):
    """Step only in scout → type 'added'."""
    scout = _user(db, email=None)
    scout.email = None
    db.commit()
    existing = _user(db, email="ex@example.com")
    _progress(db, scout.id, badge_slug="b", level_index=0, step_index=0, status="work_done")

    changes = svc.preview_scout_merge(db, from_user_id=scout.id, to_user_id=existing.id)
    assert len(changes) == 1
    assert changes[0]["type"] == "added"
    assert changes[0]["scout_status"] == "work_done"
    assert changes[0]["existing_status"] is None


def test_preview_scout_merge_upgraded(db):
    """Scout has higher status → type 'upgraded'."""
    scout = _user(db, email=None)
    scout.email = None
    db.commit()
    existing = _user(db, email="ex@example.com")
    _progress(db, scout.id, badge_slug="b", step_index=0, status="work_done")
    _progress(db, existing.id, badge_slug="b", step_index=0, status="in_progress")

    changes = svc.preview_scout_merge(db, from_user_id=scout.id, to_user_id=existing.id)
    assert len(changes) == 1
    assert changes[0]["type"] == "upgraded"
    assert changes[0]["scout_status"] == "work_done"
    assert changes[0]["existing_status"] == "in_progress"


def test_preview_scout_merge_no_change_when_existing_higher(db):
    """Frank has higher status → no entry in preview."""
    scout = _user(db, email=None)
    scout.email = None
    db.commit()
    existing = _user(db, email="ex@example.com")
    _progress(db, scout.id, badge_slug="b", step_index=0, status="in_progress")
    _progress(db, existing.id, badge_slug="b", step_index=0, status="signed_off")

    changes = svc.preview_scout_merge(db, from_user_id=scout.id, to_user_id=existing.id)
    assert changes == []


def test_preview_scout_merge_no_change_when_equal(db):
    """Equal status → no entry in preview."""
    scout = _user(db, email=None)
    scout.email = None
    db.commit()
    existing = _user(db, email="ex@example.com")
    _progress(db, scout.id, badge_slug="b", step_index=0, status="signed_off")
    _progress(db, existing.id, badge_slug="b", step_index=0, status="signed_off")

    changes = svc.preview_scout_merge(db, from_user_id=scout.id, to_user_id=existing.id)
    assert changes == []


# ── attach_email_to_scout: existing user path ─────────────────────────────────

def _scout(db, group_id, speltak_id, name="Scout"):
    """Create an emailless scout with an approved speltak membership."""
    from insigne.models import ProgressEntry
    scout = User(name=name, status="active", created_by_id=None)
    db.add(scout)
    db.flush()
    m = SpeltakMembership(user_id=scout.id, speltak_id=speltak_id, role="scout", approved=True)
    db.add(m)
    gm = GroupMembership(user_id=scout.id, group_id=group_id, role="member", approved=True)
    db.add(gm)
    db.commit()
    return scout


def _progress(db, user_id, badge_slug="badge", level_index=0, step_index=0, status="in_progress"):
    from insigne.models import ProgressEntry
    e = ProgressEntry(
        user_id=user_id, badge_slug=badge_slug,
        level_index=level_index, step_index=step_index, status=status,
    )
    db.add(e)
    db.commit()
    return e


def test_attach_email_existing_user_creates_pending_invite(db):
    """Linking an email to a scout where the user already exists must NOT merge
    immediately. It should create a pending speltak invite with source_scout_id."""
    leader = _user(db, email="leader@example.com")
    g = svc.create_group(db, name="G", slug="g")
    s = svc.create_speltak(db, group_id=g.id, name="S", slug="s")
    scout = _scout(db, g.id, s.id)
    existing = _user(db, email="existing@example.com", name="Existing")

    kind, returned_user, code = svc.attach_email_to_scout(
        db, scout_user_id=scout.id, email="existing@example.com",
        invited_by_id=leader.id, speltak=s,
    )

    assert kind == "existing_user"
    assert returned_user.id == existing.id
    assert code is None
    # Scout must still exist (not deleted)
    assert db.get(User, scout.id) is not None
    # Pending invite for existing user with source_scout_id
    invite = db.query(SpeltakMembership).filter_by(
        user_id=existing.id, speltak_id=s.id, approved=False
    ).first()
    assert invite is not None
    assert invite.source_scout_id == scout.id


def test_attach_email_existing_user_scout_not_deleted(db):
    """Scout record must survive the attach_email_to_scout call for existing user."""
    leader = _user(db, email="leader@example.com")
    g = svc.create_group(db, name="G", slug="g")
    s = svc.create_speltak(db, group_id=g.id, name="S", slug="s")
    scout = _scout(db, g.id, s.id)
    _user(db, email="ex@example.com")

    svc.attach_email_to_scout(
        db, scout_user_id=scout.id, email="ex@example.com",
        invited_by_id=leader.id, speltak=s,
    )
    assert db.get(User, scout.id) is not None


def test_list_speltak_members_hides_scout_with_pending_invite(db):
    """An emailless scout must not appear in list_speltak_members once a pending
    invite with source_scout_id pointing at it exists — the two represent the
    same person and only the pending invite should be visible."""
    leader = _user(db, email="leader@example.com")
    g = svc.create_group(db, name="G", slug="g")
    s = svc.create_speltak(db, group_id=g.id, name="S", slug="s")
    scout = _scout(db, g.id, s.id)
    existing = _user(db, email="existing@example.com", name="Existing")

    # Before attaching email: scout is in the members list
    assert any(m.user_id == scout.id for m in svc.list_speltak_members(db, s.id))

    svc.attach_email_to_scout(
        db, scout_user_id=scout.id, email="existing@example.com",
        invited_by_id=leader.id, speltak=s,
    )

    # Scout must be hidden from the members list now
    members = svc.list_speltak_members(db, s.id)
    assert not any(m.user_id == scout.id for m in members)

    # Pending invite for the existing user must still appear
    pending = svc.list_pending_speltak_members(db, s.id)
    assert any(m.user_id == existing.id for m in pending)


def test_list_speltak_members_restores_scout_when_invite_withdrawn(db):
    """When a pending invite with source_scout_id is withdrawn, the emailless
    scout must reappear in list_speltak_members."""
    leader = _user(db, email="leader@example.com")
    g = svc.create_group(db, name="G", slug="g")
    s = svc.create_speltak(db, group_id=g.id, name="S", slug="s")
    scout = _scout(db, g.id, s.id)
    existing = _user(db, email="existing@example.com", name="Existing")

    svc.attach_email_to_scout(
        db, scout_user_id=scout.id, email="existing@example.com",
        invited_by_id=leader.id, speltak=s,
    )
    assert not any(m.user_id == scout.id for m in svc.list_speltak_members(db, s.id))

    svc.withdraw_speltak_invite(db, user_id=existing.id, speltak_id=s.id)

    # Scout should reappear after withdrawal
    assert any(m.user_id == scout.id for m in svc.list_speltak_members(db, s.id))


# ── has_scout_progress ────────────────────────────────────────────────────────

def test_has_scout_progress_true(db):
    u = _user(db)
    _progress(db, u.id)
    assert svc.has_scout_progress(db, u.id) is True


def test_has_scout_progress_false(db):
    u = _user(db)
    assert svc.has_scout_progress(db, u.id) is False


# ── accept_speltak_invite_with_merge ──────────────────────────────────────────

def test_accept_with_merge_moves_progress(db):
    leader = _user(db, email="leader@example.com")
    g = svc.create_group(db, name="G", slug="g")
    s = svc.create_speltak(db, group_id=g.id, name="S", slug="s")
    scout = _scout(db, g.id, s.id)
    existing = _user(db, email="ex@example.com")
    _progress(db, scout.id, badge_slug="badge", step_index=0, status="work_done")

    svc.attach_email_to_scout(
        db, scout_user_id=scout.id, email="ex@example.com",
        invited_by_id=leader.id, speltak=s,
    )
    svc.accept_speltak_invite_with_merge(db, user_id=existing.id, speltak_id=s.id)

    from insigne.models import ProgressEntry
    entries = db.query(ProgressEntry).filter_by(user_id=existing.id).all()
    assert len(entries) == 1
    assert entries[0].status == "work_done"
    # Scout deleted, membership approved
    assert db.get(User, scout.id) is None
    m = db.query(SpeltakMembership).filter_by(user_id=existing.id, speltak_id=s.id).first()
    assert m.approved is True
    assert m.source_scout_id is None


def test_accept_with_merge_prefers_higher_status(db):
    leader = _user(db, email="leader@example.com")
    g = svc.create_group(db, name="G", slug="g")
    s = svc.create_speltak(db, group_id=g.id, name="S", slug="s")
    scout = _scout(db, g.id, s.id)
    existing = _user(db, email="ex@example.com")
    _progress(db, scout.id, step_index=0, status="signed_off")
    _progress(db, existing.id, step_index=0, status="in_progress")

    svc.attach_email_to_scout(
        db, scout_user_id=scout.id, email="ex@example.com",
        invited_by_id=leader.id, speltak=s,
    )
    svc.accept_speltak_invite_with_merge(db, user_id=existing.id, speltak_id=s.id)

    from insigne.models import ProgressEntry
    entries = db.query(ProgressEntry).filter_by(user_id=existing.id).all()
    assert len(entries) == 1
    assert entries[0].status == "signed_off"


# ── accept_speltak_invite_without_merge ───────────────────────────────────────

def test_accept_without_merge_deletes_scout_and_progress(db):
    leader = _user(db, email="leader@example.com")
    g = svc.create_group(db, name="G", slug="g")
    s = svc.create_speltak(db, group_id=g.id, name="S", slug="s")
    scout = _scout(db, g.id, s.id)
    existing = _user(db, email="ex@example.com")
    _progress(db, scout.id, step_index=0, status="work_done")

    svc.attach_email_to_scout(
        db, scout_user_id=scout.id, email="ex@example.com",
        invited_by_id=leader.id, speltak=s,
    )
    svc.accept_speltak_invite_without_merge(db, user_id=existing.id, speltak_id=s.id)

    from insigne.models import ProgressEntry
    # Existing user should have no scout-originated progress
    entries = db.query(ProgressEntry).filter_by(user_id=existing.id).all()
    assert entries == []
    # Scout deleted
    assert db.get(User, scout.id) is None
    # Membership approved
    m = db.query(SpeltakMembership).filter_by(user_id=existing.id, speltak_id=s.id).first()
    assert m.approved is True

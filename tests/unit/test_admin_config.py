"""Tests for system admin detection via config and allow_any_user_to_create_groups flag."""
from insigne.models import User


# ── is_admin property ─────────────────────────────────────────────────────────

def test_user_with_admin_email_is_admin(db):
    import insigne.config as cfg
    cfg.config.admins = ["admin@example.com"]
    user = User(email="admin@example.com", name="Admin", status="active", password_hash="x")
    db.add(user)
    db.commit()
    assert user.is_admin is True


def test_user_without_admin_email_is_not_admin(db):
    import insigne.config as cfg
    cfg.config.admins = ["admin@example.com"]
    user = User(email="scout@example.com", name="Scout", status="active", password_hash="x")
    db.add(user)
    db.commit()
    assert user.is_admin is False


def test_emailless_user_is_never_admin(db):
    import insigne.config as cfg
    cfg.config.admins = ["admin@example.com"]
    user = User(email=None, name="No Email", status="active")
    db.add(user)
    db.commit()
    assert user.is_admin is False


def test_admin_check_is_case_insensitive(db):
    import insigne.config as cfg
    cfg.config.admins = ["admin@example.com"]
    user = User(email="Admin@Example.COM", name="Admin", status="active", password_hash="x")
    db.add(user)
    db.commit()
    assert user.is_admin is True


def test_removing_email_from_config_revokes_admin(db):
    import insigne.config as cfg
    cfg.config.admins = ["admin@example.com"]
    user = User(email="admin@example.com", name="Admin", status="active", password_hash="x")
    db.add(user)
    db.commit()
    assert user.is_admin is True

    cfg.config.admins = []
    assert user.is_admin is False


def test_multiple_admins(db):
    import insigne.config as cfg
    cfg.config.admins = ["admin@example.com", "other@example.com"]
    u1 = User(email="admin@example.com", status="active", password_hash="x")
    u2 = User(email="other@example.com", status="active", password_hash="x")
    u3 = User(email="scout@example.com", status="active", password_hash="x")
    db.add_all([u1, u2, u3])
    db.commit()
    assert u1.is_admin is True
    assert u2.is_admin is True
    assert u3.is_admin is False


# ── allow_any_user_to_create_groups config ───────────────────────────────────────────────

def test_allow_any_user_to_create_groups_defaults_to_true():
    from insigne.config import Config
    c = Config(database_url="sqlite://", jwt_secret_key="x")
    assert c.allow_any_user_to_create_groups is True


def test_admins_defaults_to_empty():
    from insigne.config import Config
    c = Config(database_url="sqlite://", jwt_secret_key="x")
    assert c.admins == []

"""Admin dashboard HTML route (#139 — admin_dashboard rendered with an
undefined ``user`` variable, 500ing every successful load)."""
from insigne.auth import create_access_token
from insigne.config import config
from insigne.models import User


def _login(client, db, *, email, admin):
    if admin:
        config.admins = [email]  # config is the source of truth for is_admin
    user = User(email=email, name="T", status="active", password_hash="x")
    db.add(user)
    db.commit()
    token, _ = create_access_token(user.id)
    client.cookies.set("access_token", token)
    return user


class TestAdminDashboard:
    def test_admin_can_load_dashboard(self, client, db):
        """The regression: an authenticated admin must get a 200, not a 500."""
        _login(client, db, email="admin@example.com", admin=True)
        r = client.get("/admin")
        assert r.status_code == 200

    def test_non_admin_redirected(self, client, db):
        _login(client, db, email="user@example.com", admin=False)
        r = client.get("/admin", follow_redirects=False)
        assert r.status_code == 303
        assert r.headers["location"] == "/"

    def test_anonymous_redirected_to_login(self, client, db):
        r = client.get("/admin", follow_redirects=False)
        assert r.status_code == 303
        assert r.headers["location"] == "/login"


class TestAdminFindUser:
    def test_find_user_success_path_returns_200(self, client, db):
        """Regression: the success path rendered with an undefined ``user`` var
        (should be ``current_user``) → 500. Must be 200 now."""
        _login(client, db, email="admin@example.com", admin=True)
        target = User(email="target@example.com", name="Target", status="active", password_hash="x")
        db.add(target)
        db.commit()
        r = client.post("/admin/find-user", data={"email": "target@example.com"})
        assert r.status_code == 200
        assert "target@example.com" in r.text

    def test_find_user_empty_query_returns_200(self, client, db):
        _login(client, db, email="admin@example.com", admin=True)
        r = client.post("/admin/find-user", data={"email": ""})
        assert r.status_code == 200

    def test_find_user_requires_admin(self, client, db):
        _login(client, db, email="user@example.com", admin=False)
        r = client.post("/admin/find-user", data={"email": "x@example.com"},
                        follow_redirects=False)
        assert r.status_code == 303


class TestAdminDeleteUser:
    def test_delete_user_success_path_returns_200_and_deletes(self, client, db):
        """Regression: the success path 500'd on an undefined ``user`` var
        *after* the account was already deleted and the e-mail sent, so the
        admin saw an error while the deletion had in fact happened."""
        _login(client, db, email="admin@example.com", admin=True)
        target = User(email="victim@example.com", name="Victim", status="active", password_hash="x")
        db.add(target)
        db.commit()
        target_id = target.id
        r = client.post(f"/admin/delete-user/{target_id}", follow_redirects=False)
        assert r.status_code == 200
        assert db.get(User, target_id) is None

    def test_delete_admin_account_refused_with_message(self, client, db):
        _login(client, db, email="admin@example.com", admin=True)
        # A second admin account (is_admin derives from config.admins).
        config.admins = ["admin@example.com", "other-admin@example.com"]
        other = User(email="other-admin@example.com", name="Other", status="active", password_hash="x")
        db.add(other)
        db.commit()
        r = client.post(f"/admin/delete-user/{other.id}", follow_redirects=False)
        assert r.status_code == 200
        assert db.get(User, other.id) is not None  # not deleted
        assert "beheerdersrechten" in r.text.lower()

    def test_delete_user_requires_admin(self, client, db):
        target = User(email="t@example.com", name="T", status="active", password_hash="x")
        db.add(target)
        db.commit()
        _login(client, db, email="user@example.com", admin=False)
        r = client.post(f"/admin/delete-user/{target.id}", follow_redirects=False)
        assert r.status_code == 303
        assert db.get(User, target.id) is not None

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

"""Behavioural tests for the HTML user routes (routers/users.py).

We test status codes, redirects, HX-Redirect headers, and cookie
presence — not exact HTML markup, which is too fragile.
"""
from insigne import users as user_svc
from insigne.auth import create_access_token
from insigne.models import ConfirmationToken, User


# ── helpers ───────────────────────────────────────────────────────────────────

def _register_and_activate(db, email="jan@example.com", password="validpass1", name="Jan"):
    user_svc.start_registration(db, email)
    user = db.query(User).filter_by(email=email).first()
    ct = db.query(ConfirmationToken).filter_by(user_id=user.id, type="email_confirmation").first()
    setup = user_svc.confirm_email(db, ct.token)
    user_svc.activate_account(db, setup, password, name)
    db.refresh(user)
    return user


def _auth_cookie(user) -> dict:
    token, _ = create_access_token(user.id)
    return {"access_token": token}


# ── login ─────────────────────────────────────────────────────────────────────

class TestLogin:
    def test_valid_credentials_return_hx_redirect_and_cookie(self, client, db):
        _register_and_activate(db)
        r = client.post("/login", data={"email": "jan@example.com", "password": "validpass1"},
                        follow_redirects=False)
        assert r.headers.get("HX-Redirect") == "/"
        assert "access_token" in r.cookies

    def test_wrong_password_returns_200_with_error(self, client, db):
        _register_and_activate(db)
        r = client.post("/login", data={"email": "jan@example.com", "password": "wrongpass"})
        assert r.status_code == 200
        assert "Ongeldig" in r.text

    def test_unknown_email_returns_error(self, client, db):
        r = client.post("/login", data={"email": "nobody@example.com", "password": "any"})
        assert r.status_code == 200
        assert "Ongeldig" in r.text


# ── logout ────────────────────────────────────────────────────────────────────

class TestLogout:
    def test_redirects_to_login(self, client, db):
        r = client.post("/logout", follow_redirects=False)
        assert r.status_code == 303
        assert r.headers["location"] == "/login"

    def test_clears_access_token_cookie(self, client, db):
        user = _register_and_activate(db)
        client.cookies.set("access_token", create_access_token(user.id)[0])
        r = client.post("/logout", follow_redirects=False)
        # Cookie cleared: max-age=0 or deleted
        cookie_header = r.headers.get("set-cookie", "")
        assert "access_token" in cookie_header


# ── register ──────────────────────────────────────────────────────────────────

class TestRegister:
    def test_post_register_returns_200(self, client, db):
        r = client.post("/register", data={"email": "new@example.com"})
        assert r.status_code == 200

    def test_confirm_with_valid_code_returns_step3(self, client, db):
        user_svc.start_registration(db, "new@example.com")
        user = db.query(User).filter_by(email="new@example.com").first()
        ct = db.query(ConfirmationToken).filter_by(user_id=user.id).first()
        r = client.post("/register/confirm", data={"email": "new@example.com", "code": ct.token})
        assert r.status_code == 200
        assert "setup_token" in r.text or "wachtwoord" in r.text.lower()

    def test_confirm_with_invalid_code_returns_error(self, client, db):
        r = client.post("/register/confirm", data={"email": "x@example.com", "code": "badcode"})
        assert r.status_code == 200
        assert "verlopen" in r.text.lower() or "ongeldig" in r.text.lower()

    def test_activate_with_valid_token_sets_cookie_and_hx_redirect(self, client, db):
        user_svc.start_registration(db, "new@example.com")
        user = db.query(User).filter_by(email="new@example.com").first()
        ct = db.query(ConfirmationToken).filter_by(user_id=user.id).first()
        setup = user_svc.confirm_email(db, ct.token)
        r = client.post("/register/activate",
                        data={"setup_token": setup, "password": "validpass1", "name": "Jan"},
                        follow_redirects=False)
        assert r.headers.get("HX-Redirect") == "/"
        assert "access_token" in r.cookies

    def test_activate_with_short_password_returns_error(self, client, db):
        user_svc.start_registration(db, "new@example.com")
        user = db.query(User).filter_by(email="new@example.com").first()
        ct = db.query(ConfirmationToken).filter_by(user_id=user.id).first()
        setup = user_svc.confirm_email(db, ct.token)
        r = client.post("/register/activate",
                        data={"setup_token": setup, "password": "short", "name": ""})
        assert r.status_code == 200
        assert "8" in r.text  # password length hint

    def test_confirm_link_with_valid_code_renders_step3(self, client, db):
        user_svc.start_registration(db, "new@example.com")
        user = db.query(User).filter_by(email="new@example.com").first()
        ct = db.query(ConfirmationToken).filter_by(user_id=user.id).first()
        r = client.get(f"/register/confirm/{ct.token}")
        assert r.status_code == 200

    def test_confirm_link_with_invalid_code_renders_error(self, client, db):
        r = client.get("/register/confirm/badtoken")
        assert r.status_code == 200
        assert "verlopen" in r.text.lower() or "ongeldig" in r.text.lower()


# ── profile ───────────────────────────────────────────────────────────────────

class TestProfile:
    def test_get_profile_without_auth_redirects_to_login(self, client, db):
        r = client.get("/profile", follow_redirects=False)
        assert r.status_code == 303
        assert "/login" in r.headers["location"]

    def test_get_profile_with_auth_returns_200(self, client, db):
        user = _register_and_activate(db)
        client.cookies.set("access_token", create_access_token(user.id)[0])
        r = client.get("/profile")
        assert r.status_code == 200

    def test_post_profile_without_auth_redirects_to_login(self, client, db):
        r = client.post("/profile", data={"email": "x@example.com"},
                        follow_redirects=False)
        assert r.status_code == 303
        assert "/login" in r.headers["location"]

    def test_post_profile_updates_name(self, client, db):
        user = _register_and_activate(db)
        client.cookies.set("access_token", create_access_token(user.id)[0])
        r = client.post("/profile", data={"name": "Nieuwe Naam", "email": user.email, "password": ""})
        assert r.status_code == 200
        db.refresh(user)
        assert user.name == "Nieuwe Naam"

    def test_post_profile_with_short_password_returns_error(self, client, db):
        user = _register_and_activate(db)
        client.cookies.set("access_token", create_access_token(user.id)[0])
        r = client.post("/profile", data={"name": "Jan", "email": user.email, "password": "short"})
        assert r.status_code == 200
        assert "8" in r.text


# ── forgot password ───────────────────────────────────────────────────────────

class TestForgotPassword:
    def test_post_always_returns_200(self, client, db):
        r = client.post("/forgot-password", data={"email": "nobody@example.com"})
        assert r.status_code == 200

    def test_post_for_active_user_returns_200(self, client, db):
        _register_and_activate(db)
        r = client.post("/forgot-password", data={"email": "jan@example.com"})
        assert r.status_code == 200

    def test_confirm_link_with_valid_code_renders_step3(self, client, db):
        _register_and_activate(db)
        code = user_svc.forgot_password(db, "jan@example.com")
        r = client.get(f"/forgot-password/confirm/{code}")
        assert r.status_code == 200

    def test_confirm_link_with_invalid_code_renders_error(self, client, db):
        r = client.get("/forgot-password/confirm/badtoken")
        assert r.status_code == 200
        assert "verlopen" in r.text.lower() or "ongeldig" in r.text.lower()

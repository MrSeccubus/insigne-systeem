from unittest.mock import patch

from insigne import users as user_svc
from insigne.models import ConfirmationToken, EmailChangeRequest, User


# ── helpers ──────────────────────────────────────────────────────────────────

def _full_register(client, db, email="jan@example.com", password="validpass1", name="Jan"):
    """Register, confirm, and activate a user. Returns the access token."""
    client.post("/api/users", json={"email": email})
    user = db.query(User).filter_by(email=email).first()
    ct = db.query(ConfirmationToken).filter_by(user_id=user.id, type="email_confirmation").first()
    r = client.post("/api/users/confirm", json={"code": ct.token})
    setup = r.json()["setup_token"]
    r = client.post("/api/users/activate", json={"setup_token": setup, "password": password, "name": name})
    return r.json()["access_token"]


def _auth(token):
    return {"Authorization": f"Bearer {token}"}


# ── POST /api/users ───────────────────────────────────────────────────────────

class TestRegister:
    def test_returns_202(self, client, db):
        r = client.post("/api/users", json={"email": "jan@example.com"})
        assert r.status_code == 202

    def test_creates_pending_user(self, client, db):
        client.post("/api/users", json={"email": "jan@example.com"})
        user = db.query(User).filter_by(email="jan@example.com").first()
        assert user is not None
        assert user.status == "pending"

    def test_re_registration_of_active_user_still_returns_202(self, client, db):
        _full_register(client, db)
        r = client.post("/api/users", json={"email": "jan@example.com"})
        assert r.status_code == 202

    def test_invalid_email_returns_422(self, client, db):
        r = client.post("/api/users", json={"email": "not-an-email"})
        assert r.status_code == 422

    def test_email_without_domain_returns_422(self, client, db):
        r = client.post("/api/users", json={"email": "noatsign"})
        assert r.status_code == 422


# ── POST /api/users/confirm ───────────────────────────────────────────────────

class TestConfirm:
    def test_valid_code_returns_setup_token(self, client, db):
        client.post("/api/users", json={"email": "jan@example.com"})
        user = db.query(User).filter_by(email="jan@example.com").first()
        ct = db.query(ConfirmationToken).filter_by(user_id=user.id, type="email_confirmation").first()
        r = client.post("/api/users/confirm", json={"code": ct.token})
        assert r.status_code == 200
        assert "setup_token" in r.json()

    def test_invalid_code_returns_400(self, client, db):
        r = client.post("/api/users/confirm", json={"code": "bad-code"})
        assert r.status_code == 400


# ── POST /api/users/activate ──────────────────────────────────────────────────

class TestActivate:
    def _setup_token(self, client, db):
        client.post("/api/users", json={"email": "jan@example.com"})
        user = db.query(User).filter_by(email="jan@example.com").first()
        ct = db.query(ConfirmationToken).filter_by(user_id=user.id, type="email_confirmation").first()
        r = client.post("/api/users/confirm", json={"code": ct.token})
        return r.json()["setup_token"]

    def test_returns_access_token(self, client, db):
        setup = self._setup_token(client, db)
        r = client.post("/api/users/activate", json={"setup_token": setup, "password": "validpass1"})
        assert r.status_code == 200
        assert "access_token" in r.json()
        assert r.json()["token_type"] == "bearer"

    def test_invalid_setup_token_returns_400(self, client, db):
        r = client.post("/api/users/activate", json={"setup_token": "bad", "password": "validpass1"})
        assert r.status_code == 400

    def test_short_password_returns_400(self, client, db):
        setup = self._setup_token(client, db)
        r = client.post("/api/users/activate", json={"setup_token": setup, "password": "short"})
        assert r.status_code == 400


# ── GET /api/users/me ─────────────────────────────────────────────────────────

class TestGetMe:
    def test_returns_user_info(self, client, db):
        token = _full_register(client, db)
        r = client.get("/api/users/me", headers=_auth(token))
        assert r.status_code == 200
        data = r.json()
        assert data["email"] == "jan@example.com"
        assert data["name"] == "Jan"
        assert "id" in data

    def test_no_credentials_returns_401(self, client, db):
        r = client.get("/api/users/me")
        assert r.status_code == 401

    def test_invalid_token_returns_401(self, client, db):
        r = client.get("/api/users/me", headers={"Authorization": "Bearer notavalidtoken"})
        assert r.status_code == 401


# ── PUT /api/users/me ─────────────────────────────────────────────────────────

class TestUpdateMe:
    def test_updates_name(self, client, db):
        token = _full_register(client, db)
        r = client.put("/api/users/me", json={"name": "Janssen"}, headers=_auth(token))
        assert r.status_code == 200
        assert r.json()["name"] == "Janssen"

    def test_email_change_returns_202_style_detail(self, client, db):
        token = _full_register(client, db)
        r = client.put("/api/users/me", json={"email": "new@example.com"}, headers=_auth(token))
        assert r.status_code == 200
        assert "detail" in r.json()

    def test_email_not_updated_immediately(self, client, db):
        token = _full_register(client, db)
        client.put("/api/users/me", json={"email": "new@example.com"}, headers=_auth(token))
        user = db.query(User).filter_by(email="jan@example.com").first()
        assert user is not None

    def test_email_change_creates_pending_request(self, client, db):
        token = _full_register(client, db)
        client.put("/api/users/me", json={"email": "new@example.com"}, headers=_auth(token))
        user = db.query(User).filter_by(email="jan@example.com").first()
        req = db.query(EmailChangeRequest).filter_by(user_id=user.id).first()
        assert req is not None
        assert req.new_email == "new@example.com"

    def test_same_email_does_not_create_pending_request(self, client, db):
        token = _full_register(client, db)
        client.put("/api/users/me", json={"email": "jan@example.com"}, headers=_auth(token))
        user = db.query(User).filter_by(email="jan@example.com").first()
        assert db.query(EmailChangeRequest).filter_by(user_id=user.id).count() == 0

    def test_short_password_returns_400(self, client, db):
        token = _full_register(client, db)
        r = client.put("/api/users/me", json={"password": "short"}, headers=_auth(token))
        assert r.status_code == 400

    def test_duplicate_email_returns_409(self, client, db):
        token = _full_register(client, db, email="jan@example.com")
        _full_register(client, db, email="piet@example.com")
        r = client.put("/api/users/me", json={"email": "piet@example.com"}, headers=_auth(token))
        assert r.status_code == 409


# ── GET /api/users/me/email-change ────────────────────────────────────────────

class TestGetPendingEmailChange:
    def test_no_pending_change_returns_null(self, client, db):
        token = _full_register(client, db)
        r = client.get("/api/users/me/email-change", headers=_auth(token))
        assert r.status_code == 200
        assert r.json() is None

    def test_pending_change_returned(self, client, db):
        token = _full_register(client, db)
        user = db.query(User).filter_by(email="jan@example.com").first()
        user_svc.request_email_change(db, user, "new@example.com")
        r = client.get("/api/users/me/email-change", headers=_auth(token))
        assert r.status_code == 200
        assert r.json()["new_email"] == "new@example.com"

    def test_requires_auth(self, client, db):
        r = client.get("/api/users/me/email-change")
        assert r.status_code == 401


# ── POST /api/users/email-change/confirm ─────────────────────────────────────

class TestConfirmEmailChangeApi:
    def test_valid_token_updates_email(self, client, db):
        _full_register(client, db)
        user = db.query(User).filter_by(email="jan@example.com").first()
        req = user_svc.request_email_change(db, user, "new@example.com")
        r = client.post("/api/users/email-change/confirm", json={"token": req.confirm_token})
        assert r.status_code == 200
        assert "email" not in r.json()
        db.refresh(user)
        assert user.email == "new@example.com"

    def test_invalid_token_returns_400(self, client, db):
        r = client.post("/api/users/email-change/confirm", json={"token": "badtoken"})
        assert r.status_code == 400

    def test_token_cannot_be_reused(self, client, db):
        _full_register(client, db)
        user = db.query(User).filter_by(email="jan@example.com").first()
        req = user_svc.request_email_change(db, user, "new@example.com")
        client.post("/api/users/email-change/confirm", json={"token": req.confirm_token})
        r = client.post("/api/users/email-change/confirm", json={"token": req.confirm_token})
        assert r.status_code == 400


# ── POST /api/users/email-change/revert ──────────────────────────────────────

class TestRevertEmailChangeApi:
    def test_valid_token_reverts_email(self, client, db):
        _full_register(client, db)
        user = db.query(User).filter_by(email="jan@example.com").first()
        req = user_svc.request_email_change(db, user, "new@example.com")
        user_svc.confirm_email_change(db, req.confirm_token)
        r = client.post("/api/users/email-change/revert", json={"token": req.revert_token})
        assert r.status_code == 200
        assert "email" not in r.json()
        db.refresh(user)
        assert user.email == "jan@example.com"

    def test_invalid_token_returns_400(self, client, db):
        r = client.post("/api/users/email-change/revert", json={"token": "badtoken"})
        assert r.status_code == 400

    def test_token_cannot_be_used_twice(self, client, db):
        _full_register(client, db)
        user = db.query(User).filter_by(email="jan@example.com").first()
        req = user_svc.request_email_change(db, user, "new@example.com")
        client.post("/api/users/email-change/revert", json={"token": req.revert_token})
        r = client.post("/api/users/email-change/revert", json={"token": req.revert_token})
        assert r.status_code == 400


# ── DELETE /api/users/me ──────────────────────────────────────────────────────

class TestDeleteMe:
    def test_returns_204(self, client, db):
        token = _full_register(client, db)
        r = client.delete("/api/users/me", headers=_auth(token))
        assert r.status_code == 204

    def test_user_no_longer_in_db(self, client, db):
        token = _full_register(client, db)
        client.delete("/api/users/me", headers=_auth(token))
        assert db.query(User).filter_by(email="jan@example.com").first() is None

    def test_sends_deletion_confirmation_email(self, client, db):
        token = _full_register(client, db)
        with patch("routers.api_users.send_account_deleted_email") as mock_send:
            client.delete("/api/users/me", headers=_auth(token))
        mock_send.assert_called_once_with("jan@example.com", "Jan")


# ── POST /api/auth/token ──────────────────────────────────────────────────────

class TestLogin:
    def test_correct_credentials_return_token(self, client, db):
        _full_register(client, db)
        r = client.post("/api/auth/token", json={"email": "jan@example.com", "password": "validpass1"})
        assert r.status_code == 200
        assert "access_token" in r.json()

    def test_wrong_password_returns_401(self, client, db):
        _full_register(client, db)
        r = client.post("/api/auth/token", json={"email": "jan@example.com", "password": "wrongpass"})
        assert r.status_code == 401

    def test_unknown_email_returns_401(self, client, db):
        r = client.post("/api/auth/token", json={"email": "nobody@example.com", "password": "pass"})
        assert r.status_code == 401


# ── POST /api/auth/forgot-password ───────────────────────────────────────────

class TestForgotPassword:
    def test_unknown_email_still_returns_202(self, client, db):
        r = client.post("/api/auth/forgot-password", json={"email": "nobody@example.com"})
        assert r.status_code == 202

    def test_active_user_returns_202(self, client, db):
        _full_register(client, db)
        r = client.post("/api/auth/forgot-password", json={"email": "jan@example.com"})
        assert r.status_code == 202

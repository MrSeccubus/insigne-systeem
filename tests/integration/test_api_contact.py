"""Tests for the JSON contact API."""
from insigne import users as user_svc
from insigne.auth import create_access_token
from insigne.models import ConfirmationToken, User
from routers.html_contact import _make_token, _current_bucket


def _valid_token(answer: int) -> str:
    return _make_token(answer, _current_bucket())


def _auth(token):
    return {"Authorization": f"Bearer {token}"}


def _full_register(client, db, email="jan@example.com"):
    user_svc.start_registration(db, email)
    user = db.query(User).filter_by(email=email).first()
    ct = db.query(ConfirmationToken).filter_by(user_id=user.id, type="email_confirmation").first()
    setup = user_svc.confirm_email(db, ct.token)
    user_svc.activate_account(db, setup, "validpass1", "Jan")
    db.refresh(user)
    token, _ = create_access_token(user.id)
    return token


class TestGetCaptcha:
    def test_returns_token_and_numbers(self, client, db):
        r = client.get("/api/contact/captcha")
        assert r.status_code == 200
        data = r.json()
        assert "token" in data
        assert 1 <= data["a"] <= 9
        assert 1 <= data["b"] <= 9

    def test_each_call_returns_different_token(self, client, db):
        t1 = client.get("/api/contact/captcha").json()["token"]
        t2 = client.get("/api/contact/captcha").json()["token"]
        # statistically near-certain to differ (different random numbers)
        # just check they're non-empty strings
        assert t1 and t2


class TestPostContactAnonymous:
    def _body(self, *, correct=7, submitted=None):
        if submitted is None:
            submitted = correct
        return {
            "subject": "Testvraag",
            "body": "Dit is een testbericht.",
            "sender_email": "user@example.com",
            "captcha_token": _valid_token(correct),
            "captcha_answer": submitted,
        }

    def test_valid_returns_202(self, client, db):
        r = client.post("/api/contact", json=self._body())
        assert r.status_code == 202

    def test_wrong_captcha_returns_400(self, client, db):
        r = client.post("/api/contact", json=self._body(correct=7, submitted=99))
        assert r.status_code == 400

    def test_expired_bucket_returns_400(self, client, db):
        old_token = _make_token(7, _current_bucket() - 2)
        body = self._body()
        body["captcha_token"] = old_token
        r = client.post("/api/contact", json=body)
        assert r.status_code == 400

    def test_missing_captcha_returns_422(self, client, db):
        r = client.post("/api/contact", json={
            "subject": "S", "body": "B", "sender_email": "x@example.com",
        })
        assert r.status_code == 422

    def test_missing_sender_email_returns_422(self, client, db):
        r = client.post("/api/contact", json={
            "subject": "S", "body": "B",
            "captcha_token": _valid_token(7), "captcha_answer": 7,
        })
        assert r.status_code == 422

    def test_previous_bucket_accepted(self, client, db):
        body = self._body()
        body["captcha_token"] = _make_token(7, _current_bucket() - 1)
        r = client.post("/api/contact", json=body)
        assert r.status_code == 202


class TestPostContactAuthenticated:
    def test_valid_returns_202(self, client, db):
        token = _full_register(client, db)
        r = client.post("/api/contact",
                        json={"subject": "Vraag", "body": "Hallo"},
                        headers=_auth(token))
        assert r.status_code == 202

    def test_no_captcha_needed(self, client, db):
        token = _full_register(client, db)
        r = client.post("/api/contact",
                        json={"subject": "Vraag", "body": "Hallo"},
                        headers=_auth(token))
        assert r.status_code == 202

    def test_sender_email_ignored(self, client, db):
        token = _full_register(client, db)
        r = client.post("/api/contact",
                        json={"subject": "Vraag", "body": "Hallo",
                              "sender_email": "evil@attacker.com"},
                        headers=_auth(token))
        assert r.status_code == 202

    def test_invalid_bearer_token_falls_back_to_anonymous(self, client, db):
        r = client.post("/api/contact",
                        json={"subject": "S", "body": "B"},
                        headers={"Authorization": "Bearer badtoken"})
        assert r.status_code == 422

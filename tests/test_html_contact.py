"""Tests for the contact form routes."""
import hashlib
import hmac

from insigne import users as user_svc
from insigne.auth import create_access_token
from insigne.config import config
from insigne.models import ConfirmationToken, User


def _captcha_token(answer: int) -> str:
    return hmac.new(
        config.jwt_secret_key.encode(),
        str(answer).encode(),
        hashlib.sha256,
    ).hexdigest()


def _register_and_activate(db, email="jan@example.com"):
    user_svc.start_registration(db, email)
    user = db.query(User).filter_by(email=email).first()
    ct = db.query(ConfirmationToken).filter_by(user_id=user.id, type="email_confirmation").first()
    setup = user_svc.confirm_email(db, ct.token)
    user_svc.activate_account(db, setup, "validpass1", "Jan")
    db.refresh(user)
    return user


class TestContactPage:
    def test_get_returns_200(self, client, db):
        r = client.get("/contact")
        assert r.status_code == 200

    def test_anonymous_sees_email_field_and_captcha(self, client, db):
        r = client.get("/contact")
        assert "sender_email" in r.text
        assert "captcha" in r.text.lower()

    def test_authenticated_has_no_email_field_or_captcha(self, client, db):
        user = _register_and_activate(db)
        client.cookies.set("access_token", create_access_token(user.id)[0])
        r = client.get("/contact")
        assert "sender_email" not in r.text
        assert "captcha" not in r.text.lower()

    def test_footer_contact_link_present_on_homepage(self, client, db):
        r = client.get("/")
        assert "/contact" in r.text


class TestContactSubmitAnonymous:
    def _post(self, client, *, answer_override=None, **kwargs):
        a, b = 3, 4
        correct = a + b
        answer = answer_override if answer_override is not None else correct
        token = _captcha_token(correct)
        data = {
            "sender_email": "user@example.com",
            "subject": "Testvraag",
            "body": "Dit is een testbericht.",
            "captcha_token": token,
            "captcha_answer": str(answer),
            **kwargs,
        }
        return client.post("/contact", data=data)

    def test_valid_submission_shows_success(self, client, db):
        r = self._post(client)
        assert r.status_code == 200
        assert "verzonden" in r.text.lower()

    def test_wrong_captcha_shows_error(self, client, db):
        r = self._post(client, answer_override=99)
        assert r.status_code == 200
        assert "onjuist" in r.text.lower()

    def test_wrong_captcha_preserves_subject(self, client, db):
        r = self._post(client, answer_override=99, subject="Bewaar dit")
        assert "Bewaar dit" in r.text

    def test_wrong_captcha_preserves_body(self, client, db):
        r = self._post(client, answer_override=99, body="Bewaar ook dit")
        assert "Bewaar ook dit" in r.text

    def test_non_numeric_captcha_shows_error(self, client, db):
        r = self._post(client, answer_override="abc")
        assert r.status_code == 200
        assert "onjuist" in r.text.lower()

    def test_valid_submission_does_not_show_form_again(self, client, db):
        r = self._post(client)
        assert "captcha_token" not in r.text


class TestContactSubmitAuthenticated:
    def test_valid_submission_shows_success(self, client, db):
        user = _register_and_activate(db)
        client.cookies.set("access_token", create_access_token(user.id)[0])
        r = client.post("/contact", data={"subject": "Vraag", "body": "Hallo"})
        assert r.status_code == 200
        assert "verzonden" in r.text.lower()

    def test_no_captcha_required_for_authenticated_user(self, client, db):
        user = _register_and_activate(db)
        client.cookies.set("access_token", create_access_token(user.id)[0])
        r = client.post("/contact", data={"subject": "Vraag", "body": "Hallo"})
        assert r.status_code == 200
        assert "onjuist" not in r.text.lower()

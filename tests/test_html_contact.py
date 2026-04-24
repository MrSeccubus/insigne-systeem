"""Tests for the contact form routes."""
from unittest.mock import patch

from insigne import users as user_svc
from insigne.auth import create_access_token
from insigne.models import ConfirmationToken, User
from routers.html_contact import _make_token, _current_bucket


def _valid_token(answer: int) -> str:
    return _make_token(answer, _current_bucket())


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
    def _post(self, client, *, correct=7, submitted=None, token=None, **kwargs):
        """Post the form. correct= is what the token is signed for; submitted= is what the user types."""
        if submitted is None:
            submitted = correct
        data = {
            "sender_email": "user@example.com",
            "subject": "Testvraag",
            "body": "Dit is een testbericht.",
            "captcha_token": token if token is not None else _valid_token(correct),
            "captcha_answer": str(submitted),
            **kwargs,
        }
        return client.post("/contact", data=data)

    def test_valid_submission_shows_success(self, client, db):
        r = self._post(client)
        assert r.status_code == 200
        assert "verzonden" in r.text.lower()

    def test_wrong_answer_shows_error(self, client, db):
        r = self._post(client, correct=7, submitted=99)
        assert r.status_code == 200
        assert "onjuist" in r.text.lower()

    def test_wrong_answer_preserves_subject(self, client, db):
        r = self._post(client, correct=7, submitted=99, subject="Bewaar dit")
        assert "Bewaar dit" in r.text

    def test_wrong_answer_preserves_body(self, client, db):
        r = self._post(client, correct=7, submitted=99, body="Bewaar ook dit")
        assert "Bewaar ook dit" in r.text

    def test_non_numeric_answer_shows_error(self, client, db):
        r = self._post(client, correct=7, submitted="abc")
        assert r.status_code == 200
        assert "onjuist" in r.text.lower()

    def test_valid_submission_does_not_show_form_again(self, client, db):
        r = self._post(client)
        assert "captcha_token" not in r.text

    def test_previous_bucket_still_accepted(self, client, db):
        prev_bucket = _current_bucket() - 1
        r = self._post(client, correct=7, token=_make_token(7, prev_bucket))
        assert "verzonden" in r.text.lower()

    def test_old_bucket_rejected(self, client, db):
        old_bucket = _current_bucket() - 2
        r = self._post(client, correct=7, token=_make_token(7, old_bucket))
        assert "onjuist" in r.text.lower()

    def test_future_bucket_rejected(self, client, db):
        future_bucket = _current_bucket() + 1
        r = self._post(client, correct=7, token=_make_token(7, future_bucket))
        assert "onjuist" in r.text.lower()

    def test_token_from_jwt_secret_directly_rejected(self, client, db):
        """Verify the captcha uses a derived key, not the raw JWT secret."""
        import hashlib
        import hmac
        from insigne.config import config
        fake_token = f"{_current_bucket()}:" + hmac.new(
            config.jwt_secret_key.encode(),
            f"7:{_current_bucket()}".encode(),
            hashlib.sha256,
        ).hexdigest()
        r = self._post(client, correct=7, token=fake_token)
        assert "onjuist" in r.text.lower()


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

    def test_submitted_email_ignored_for_authenticated_user(self, client, db):
        user = _register_and_activate(db)
        client.cookies.set("access_token", create_access_token(user.id)[0])
        # Even if someone crafts a POST with a sender_email, it should succeed
        # (the email used will be current_user.email, not the submitted one)
        r = client.post("/contact", data={
            "subject": "Vraag", "body": "Hallo",
            "sender_email": "evil@attacker.com",
        })
        assert r.status_code == 200
        assert "verzonden" in r.text.lower()

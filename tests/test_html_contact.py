"""Tests for the contact form routes."""
import hashlib
import hmac

from insigne.config import config


def _captcha_token(answer: int) -> str:
    return hmac.new(
        config.jwt_secret_key.encode(),
        str(answer).encode(),
        hashlib.sha256,
    ).hexdigest()


class TestContactPage:
    def test_get_returns_200(self, client, db):
        r = client.get("/contact")
        assert r.status_code == 200

    def test_page_contains_form_fields(self, client, db):
        r = client.get("/contact")
        assert "sender_email" in r.text
        assert "subject" in r.text
        assert "captcha" in r.text.lower()

    def test_footer_contact_link_present_on_homepage(self, client, db):
        r = client.get("/")
        assert "/contact" in r.text


class TestContactSubmit:
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

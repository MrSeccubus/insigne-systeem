"""Tests for the contact form routes (ALTCHA proof-of-work captcha)."""
import base64
import json

from altcha import solve_challenge_v1

from insigne import users as user_svc
from insigne.auth import create_access_token
from insigne.config import config
from insigne.models import ConfirmationToken, User


def _solve_captcha(client) -> str:
    """Fetch a challenge from the server and produce a valid ALTCHA payload, the
    way the browser widget would. Returns the base64 payload for the `altcha`
    form field."""
    d = client.get("/altcha/challenge").json()
    max_number = d.get("maxnumber") or d.get("maxNumber")
    sol = solve_challenge_v1(d["challenge"], d["salt"], d["algorithm"], max_number, 0)
    payload = {"algorithm": d["algorithm"], "challenge": d["challenge"],
               "number": sol.number, "salt": d["salt"], "signature": d["signature"]}
    return base64.b64encode(json.dumps(payload).encode()).decode()


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
        assert client.get("/contact").status_code == 200

    def test_anonymous_sees_email_field(self, client, db):
        assert "sender_email" in client.get("/contact").text

    def test_anonymous_sees_captcha_widget_when_enabled(self, client, db):
        config.captcha.enabled = True
        r = client.get("/contact")
        assert "altcha-widget" in r.text
        assert "altcha.min.js" in r.text

    def test_authenticated_has_no_email_field_or_captcha(self, client, db):
        user = _register_and_activate(db)
        client.cookies.set("access_token", create_access_token(user.id)[0])
        config.captcha.enabled = True
        r = client.get("/contact")
        assert "sender_email" not in r.text
        assert "altcha-widget" not in r.text

    def test_footer_contact_link_present_on_homepage(self, client, db):
        assert "/contact" in client.get("/").text


class TestContactSubmitAnonymousCaptchaEnabled:
    def _data(self, **kw):
        d = {"sender_email": "user@example.com", "subject": "Testvraag",
             "body": "Dit is een testbericht."}
        d.update(kw)
        return d

    def test_valid_solution_shows_success(self, client, db):
        config.captcha.enabled = True
        r = client.post("/contact", data=self._data(altcha=_solve_captcha(client)))
        assert r.status_code == 200
        assert "verstuurd" in r.text.lower()

    def test_missing_solution_shows_error(self, client, db):
        config.captcha.enabled = True
        r = client.post("/contact", data=self._data())
        assert r.status_code == 200
        assert "verificatie is mislukt" in r.text.lower()

    def test_garbage_solution_shows_error(self, client, db):
        config.captcha.enabled = True
        r = client.post("/contact", data=self._data(altcha="not-a-valid-payload"))
        assert "verificatie is mislukt" in r.text.lower()

    def test_error_preserves_subject_and_body(self, client, db):
        config.captcha.enabled = True
        r = client.post("/contact", data=self._data(subject="Bewaar dit", body="En dit"))
        assert "Bewaar dit" in r.text and "En dit" in r.text

    def test_solution_cannot_be_replayed(self, client, db):
        config.captcha.enabled = True
        payload = _solve_captcha(client)
        first = client.post("/contact", data=self._data(altcha=payload))
        second = client.post("/contact", data=self._data(altcha=payload))
        assert "verstuurd" in first.text.lower()
        assert "verificatie is mislukt" in second.text.lower()  # replay rejected


class TestContactSubmitCaptchaDisabled:
    def test_disabled_allows_submit_without_solution(self, client, db):
        config.captcha.enabled = False
        r = client.post("/contact", data={
            "sender_email": "user@example.com", "subject": "S", "body": "B"})
        assert r.status_code == 200
        assert "verstuurd" in r.text.lower()


class TestContactSubmitAuthenticated:
    def test_valid_submission_shows_success(self, client, db):
        user = _register_and_activate(db)
        client.cookies.set("access_token", create_access_token(user.id)[0])
        config.captcha.enabled = True  # captcha is skipped for logged-in users
        r = client.post("/contact", data={"subject": "Vraag", "body": "Hallo"})
        assert r.status_code == 200
        assert "verstuurd" in r.text.lower()

    def test_submitted_email_ignored_for_authenticated_user(self, client, db):
        user = _register_and_activate(db)
        client.cookies.set("access_token", create_access_token(user.id)[0])
        r = client.post("/contact", data={
            "subject": "Vraag", "body": "Hallo", "sender_email": "evil@attacker.com"})
        assert r.status_code == 200
        assert "verstuurd" in r.text.lower()

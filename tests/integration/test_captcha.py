"""ALTCHA captcha: challenge endpoint, server verification, and its use on the
/register and /contact endpoints. The captcha is disabled in the test config;
these tests flip config.captcha.enabled on and solve a real challenge the way
the browser widget would."""
import base64
import json

from altcha import solve_challenge_v1

import captcha
from insigne.config import config
from insigne.models import User


def _solve(client) -> str:
    d = client.get("/altcha/challenge").json()
    max_number = d.get("maxnumber") or d.get("maxNumber")
    sol = solve_challenge_v1(d["challenge"], d["salt"], d["algorithm"], max_number, 0)
    payload = {"algorithm": d["algorithm"], "challenge": d["challenge"],
               "number": sol.number, "salt": d["salt"], "signature": d["signature"]}
    return base64.b64encode(json.dumps(payload).encode()).decode()


class TestChallengeEndpoint:
    def test_returns_signed_challenge(self, client, db):
        d = client.get("/altcha/challenge").json()
        for key in ("algorithm", "challenge", "salt", "signature"):
            assert key in d
        # Both maxnumber spellings present for widget compatibility.
        assert (d.get("maxnumber") or d.get("maxNumber")) is not None


class TestVerify:
    def test_valid_payload_verifies(self, client, db):
        config.captcha.enabled = True
        assert captcha.verify(_solve(client)) is True

    def test_empty_and_garbage_rejected(self, client, db):
        assert captcha.verify("") is False
        assert captcha.verify("not-base64!!") is False

    def test_replay_rejected(self, client, db):
        config.captcha.enabled = True
        payload = _solve(client)
        assert captcha.verify(payload) is True
        assert captcha.verify(payload) is False  # single-use

    def test_wrong_signing_key_rejected(self, client, db):
        """A payload signed with a different key (e.g. forged) must fail."""
        config.captcha.enabled = True
        d = client.get("/altcha/challenge").json()
        max_number = d.get("maxnumber") or d.get("maxNumber")
        sol = solve_challenge_v1(d["challenge"], d["salt"], d["algorithm"], max_number, 0)
        forged = {"algorithm": d["algorithm"], "challenge": d["challenge"],
                  "number": sol.number, "salt": d["salt"], "signature": "0" * 64}
        assert captcha.verify(base64.b64encode(json.dumps(forged).encode()).decode()) is False


class TestRegisterCaptcha:
    def test_valid_solution_advances_to_step2(self, client, db):
        config.captcha.enabled = True
        r = client.post("/register", data={"email": "new@example.com", "altcha": _solve(client)})
        assert r.status_code == 200
        # A pending user is created only when the captcha passed.
        assert db.query(User).filter_by(email="new@example.com").first() is not None

    def test_missing_solution_blocks_registration(self, client, db):
        config.captcha.enabled = True
        r = client.post("/register", data={"email": "blocked@example.com"})
        assert r.status_code == 200
        assert "verificatie is mislukt" in r.text.lower()
        # No user row created when the captcha failed.
        assert db.query(User).filter_by(email="blocked@example.com").first() is None

    def test_widget_shown_on_register_page_when_enabled(self, client, db):
        config.captcha.enabled = True
        r = client.get("/register")
        assert "altcha-widget" in r.text
        assert "altcha.min.js" in r.text

    def test_disabled_allows_registration_without_solution(self, client, db):
        config.captcha.enabled = False
        r = client.post("/register", data={"email": "nocaptcha@example.com"})
        assert r.status_code == 200
        assert db.query(User).filter_by(email="nocaptcha@example.com").first() is not None

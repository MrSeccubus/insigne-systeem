"""Per-IP rate limiting on the unauthenticated e-mail-sending endpoints.

The limiter is disabled in the test config (tests/fixtures/config.yml); these
tests flip it on with a small limit and confirm the Nth request is refused with
429. The autouse reset_config fixture restores config and clears the limiter
counters after each test.
"""
from insigne.config import config


def _enable(register="2/hour", forgot="2/hour", contact="2/hour"):
    config.rate_limit.enabled = True
    config.rate_limit.register = register
    config.rate_limit.forgot_password = forgot
    config.rate_limit.contact = contact


class TestRegisterRateLimit:
    def test_blocks_after_limit(self, client, db):
        _enable(register="2/hour")
        r1 = client.post("/register", data={"email": "a@example.com"})
        r2 = client.post("/register", data={"email": "b@example.com"})
        r3 = client.post("/register", data={"email": "c@example.com"})
        assert r1.status_code == 200
        assert r2.status_code == 200
        assert r3.status_code == 429

    def test_disabled_never_blocks(self, client, db):
        config.rate_limit.enabled = False
        for i in range(6):
            r = client.post("/register", data={"email": f"u{i}@example.com"})
            assert r.status_code == 200


class TestForgotPasswordRateLimit:
    def test_blocks_after_limit(self, client, db):
        _enable(forgot="2/hour")
        assert client.post("/forgot-password", data={"email": "a@example.com"}).status_code == 200
        assert client.post("/forgot-password", data={"email": "a@example.com"}).status_code == 200
        assert client.post("/forgot-password", data={"email": "a@example.com"}).status_code == 429


class TestContactRateLimit:
    def test_blocks_after_limit_regardless_of_captcha(self, client, db):
        """The limit is enforced before the handler, so even requests that would
        fail the captcha count — bounding spam attempts directly."""
        _enable(contact="2/hour")
        data = {"name": "X", "email": "x@example.com", "subject": "s",
                "body": "b", "captcha_answer": "0", "captcha_token": "bogus"}
        codes = [client.post("/contact", data=data).status_code for _ in range(3)]
        assert codes[2] == 429
        assert codes[0] != 429 and codes[1] != 429


class TestRateLimitIsolationBetweenTests:
    """Guards that the reset_config fixture actually clears counters — if it
    didn't, this test would start already throttled by the tests above."""

    def test_counter_is_reset(self, client, db):
        _enable(register="2/hour")
        assert client.post("/register", data={"email": "fresh@example.com"}).status_code == 200

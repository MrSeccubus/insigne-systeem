"""Rate limiting on the e-mail-sending endpoints.

The limiter is disabled in the test config (tests/fixtures/config.yml); these
tests flip it on with a small limit and confirm the Nth request is refused with
429. The autouse reset_config fixture restores config and clears the limiter
counters after each test.

The unauthenticated endpoints (/register, /forgot-password, /contact) key on
the client IP; the by-email sign-off endpoints key on the authenticated user.
"""
from insigne.auth import create_access_token
from insigne.config import config
from insigne.models import User


def _enable(register="2/hour", forgot="2/hour", contact="2/hour", signoff="2/hour"):
    config.rate_limit.enabled = True
    config.rate_limit.register = register
    config.rate_limit.forgot_password = forgot
    config.rate_limit.contact = contact
    config.rate_limit.signoff = signoff


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


class TestSignoffRateLimit:
    """The by-email sign-off endpoints mail an arbitrary address on behalf of
    the logged-in scout; the limit keys on the user id from the JWT cookie
    (not the IP), so it can't be reset by hopping connections and is never
    shared by users behind one NAT.

    The limiter runs before the handler, so a nonexistent entry id (handler →
    303 to "/") still exercises it without sending real mail.
    """

    _URL = "/progress/00000000-0000-0000-0000-000000000000/request-signoff"
    _DATA = {"mentor_email": "mentor@example.com"}

    def _login(self, client, db, email):
        user = User(email=email, name="Scout", status="active", password_hash="x")
        db.add(user)
        db.commit()
        token, _ = create_access_token(user.id)
        client.cookies.set("access_token", token)
        return user

    def test_blocks_after_limit(self, client, db):
        _enable(signoff="2/hour")
        self._login(client, db, "scout@example.com")
        codes = [
            client.post(self._URL, data=self._DATA, follow_redirects=False).status_code
            for _ in range(3)
        ]
        assert codes == [303, 303, 429]

    def test_keyed_per_user_not_per_ip(self, client, db):
        """A second user on the same client/IP gets a fresh bucket."""
        _enable(signoff="2/hour")
        self._login(client, db, "first@example.com")
        for _ in range(2):
            client.post(self._URL, data=self._DATA, follow_redirects=False)
        assert client.post(self._URL, data=self._DATA, follow_redirects=False).status_code == 429

        self._login(client, db, "second@example.com")
        assert client.post(self._URL, data=self._DATA, follow_redirects=False).status_code == 303

    def test_jaarinsigne_direct_endpoint_is_limited(self, client, db):
        _enable(signoff="2/hour")
        self._login(client, db, "scout@example.com")
        url = "/badges/jaarinsigne_2026/request-signoff"
        codes = [
            client.post(url, data=self._DATA, follow_redirects=False).status_code
            for _ in range(3)
        ]
        assert codes[0] != 429 and codes[1] != 429
        assert codes[2] == 429

    def test_disabled_never_blocks(self, client, db):
        config.rate_limit.enabled = False
        config.rate_limit.signoff = "2/hour"
        self._login(client, db, "scout@example.com")
        for _ in range(5):
            r = client.post(self._URL, data=self._DATA, follow_redirects=False)
            assert r.status_code == 303


class TestRateLimitIsolationBetweenTests:
    """Guards that the reset_config fixture actually clears counters — if it
    didn't, this test would start already throttled by the tests above."""

    def test_counter_is_reset(self, client, db):
        _enable(register="2/hour")
        assert client.post("/register", data={"email": "fresh@example.com"}).status_code == 200

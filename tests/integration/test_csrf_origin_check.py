"""Origin / Referer CSRF middleware (#99).

State-changing requests whose Origin header doesn't match ``config.base_url``
are rejected with 403; Referer is consulted as fallback when Origin is absent.
Requests missing both headers are rejected (OWASP CSRF Cheat Sheet behaviour).
The old ``/api/`` exemption was removed with the JSON API (v1.2.0), so every
state-changing request is now checked.

The default ``client`` fixture sets ``Origin`` so the rest of the suite isn't
forced to send it on every POST; these tests pop it where the test needs to
exercise the absent-Origin / Referer-only code paths."""


def _no_default_origin(client):
    """Strip the conftest's default Origin so this test controls headers."""
    client.headers.pop("Origin", None)
    return client


class TestOriginCsrfCheck:
    # /groups/new is auth-gated; without a session cookie it returns 303 to
    # /login. Perfect for exercising the middleware without dragging in
    # bcrypt / cookie setup — we just check whether the middleware lets
    # the request through to the auth layer (303) or blocks it (403).

    def test_post_with_matching_origin_passes(self, client, db):
        r = client.post(
            "/groups/new",
            data={"name": "Test"},
            headers={"Origin": "http://localhost:8000"},
            follow_redirects=False,
        )
        assert r.status_code != 403, f"Got 403, expected middleware to pass: {r.text!r}"

    def test_post_with_mismatched_origin_is_rejected(self, client, db):
        r = client.post(
            "/groups/new",
            data={"name": "Test"},
            headers={"Origin": "http://evil.example.com"},
            follow_redirects=False,
        )
        assert r.status_code == 403
        assert "Origin" in r.text  # error message references Origin

    def test_post_with_matching_referer_passes(self, client, db):
        """Origin absent, Referer matches base_url — pass."""
        _no_default_origin(client)
        r = client.post(
            "/groups/new",
            data={"name": "Test"},
            headers={"Referer": "http://localhost:8000/groups"},
            follow_redirects=False,
        )
        assert r.status_code != 403, f"Got 403, expected middleware to pass: {r.text!r}"

    def test_post_with_mismatched_referer_is_rejected(self, client, db):
        """Origin absent, Referer set but cross-site — reject."""
        _no_default_origin(client)
        r = client.post(
            "/groups/new",
            data={"name": "Test"},
            headers={"Referer": "http://evil.example.com/page"},
            follow_redirects=False,
        )
        assert r.status_code == 403
        assert "Referer" in r.text

    def test_post_without_origin_or_referer_is_rejected(self, client, db):
        """Browsers always send at least one of Origin/Referer on state-changing
        requests. Missing both → 403."""
        _no_default_origin(client)
        r = client.post(
            "/groups/new",
            data={"name": "Test"},
            follow_redirects=False,
        )
        assert r.status_code == 403
        assert "Origin" in r.text and "Referer" in r.text

    def test_get_with_mismatched_origin_passes(self, client, db):
        """GET is not state-changing — Origin not checked."""
        r = client.get("/login", headers={"Origin": "http://evil.example.com"})
        assert r.status_code == 200

    def test_delete_with_mismatched_origin_is_rejected(self, client, db):
        """DELETE is state-changing — same rule applies."""
        r = client.delete(
            "/groups/new",  # path doesn't have to support DELETE — middleware runs first
            headers={"Origin": "http://evil.example.com"},
        )
        assert r.status_code == 403

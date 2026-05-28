"""Origin-header CSRF middleware (#99).

State-changing browser POSTs whose Origin header doesn't match
``config.base_url`` are rejected with 403. Origin-less requests
(non-browser clients) pass — the middleware is defense-in-depth on top
of the SameSite=Lax cookie, not a hard CSRF wall. JSON-API paths
under ``/api/`` are exempt: they use bearer-token auth, not cookies."""


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

    def test_post_without_origin_passes(self, client, db):
        """Non-browser clients (curl, server-to-server, TestClient by default)
        don't send Origin — the middleware allows them through. They're
        protected by the SameSite=Lax cookie + bearer-token API alternative."""
        r = client.post(
            "/groups/new",
            data={"name": "Test"},
            follow_redirects=False,
        )
        assert r.status_code != 403

    def test_get_with_mismatched_origin_passes(self, client, db):
        """GET is not state-changing — Origin not checked."""
        r = client.get("/login", headers={"Origin": "http://evil.example.com"})
        assert r.status_code == 200

    def test_api_post_with_mismatched_origin_passes(self, client, db):
        """/api/* uses bearer-token auth; not vulnerable to cookie CSRF.
        Middleware skips it."""
        r = client.post(
            "/api/auth/login",
            json={"email": "x@example.com", "password": "wrong"},
            headers={"Origin": "http://evil.example.com"},
        )
        # API returns 401 for bad creds — but NOT 403 from the middleware.
        assert r.status_code != 403

    def test_delete_with_mismatched_origin_is_rejected(self, client, db):
        """DELETE is state-changing — same rule applies."""
        r = client.delete(
            "/groups/new",  # path doesn't have to support DELETE — middleware runs first
            headers={"Origin": "http://evil.example.com"},
        )
        assert r.status_code == 403

"""Security headers applied to every response (clickjacking, MIME-sniffing, CSP)."""
import pytest


class TestSecurityHeaders:
    def test_html_page_has_all_headers(self, client, db):
        r = client.get("/login")
        assert r.headers["X-Frame-Options"] == "DENY"
        assert r.headers["X-Content-Type-Options"] == "nosniff"
        assert r.headers["Referrer-Policy"] == "same-origin"
        assert "Content-Security-Policy" in r.headers

    def test_csp_directives(self, client, db):
        csp = client.get("/login").headers["Content-Security-Policy"]
        # Clickjacking + XSS blast-radius reducers.
        assert "frame-ancestors 'none'" in csp
        assert "object-src 'none'" in csp
        assert "base-uri 'self'" in csp
        assert "form-action 'self'" in csp
        assert "default-src 'self'" in csp

    def test_csp_allows_altcha_worker_blob(self, client, db):
        """The ALTCHA captcha spawns its PoW worker from a Blob URL — worker-src
        must allow blob: or the captcha silently breaks."""
        csp = client.get("/login").headers["Content-Security-Policy"]
        assert "worker-src 'self' blob:" in csp

    def test_csp_allows_inline_and_eval_for_alpine(self, client, db):
        """Pragmatic CSP: inline scripts + Alpine's Function-based expression
        eval require unsafe-inline / unsafe-eval in script-src."""
        csp = client.get("/login").headers["Content-Security-Policy"]
        assert "'unsafe-inline'" in csp
        assert "'unsafe-eval'" in csp

    def test_no_hsts_header_from_app(self, client, db):
        """HSTS is the reverse proxy's job (must not be sent over plain HTTP)."""
        assert "Strict-Transport-Security" not in client.get("/login").headers

    def test_headers_on_static_assets(self, client, db):
        r = client.get("/static/style.css")
        assert r.status_code == 200
        assert r.headers["X-Frame-Options"] == "DENY"
        assert r.headers["X-Content-Type-Options"] == "nosniff"

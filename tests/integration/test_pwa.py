"""PWA wrapper (#101): manifest, service worker, icons, install page,
offline fallback, and the PWA meta tags in base.html."""
import json


class TestManifest:
    def test_manifest_served(self, client, db):
        r = client.get("/static/manifest.webmanifest")
        assert r.status_code == 200

    def test_manifest_has_required_fields(self, client, db):
        r = client.get("/static/manifest.webmanifest")
        m = json.loads(r.text)
        # PWA installability requires at least name, start_url, display,
        # and an icon set containing 192x192 + 512x512.
        for key in ("name", "short_name", "start_url", "scope", "display",
                    "theme_color", "background_color", "icons"):
            assert key in m, f"manifest missing {key!r}"
        assert m["display"] == "standalone"
        assert m["theme_color"] == "#00A651"
        sizes = {icon["sizes"] for icon in m["icons"]}
        assert "192x192" in sizes and "512x512" in sizes

    def test_manifest_has_maskable_icon(self, client, db):
        r = client.get("/static/manifest.webmanifest")
        m = json.loads(r.text)
        purposes = {icon.get("purpose", "") for icon in m["icons"]}
        assert "maskable" in purposes, \
            "PWA needs a maskable icon for proper Android home-screen masking"


class TestServiceWorker:
    def test_sw_served_at_root_path(self, client, db):
        """The service worker must be reachable from its registration URL
        so its scope can be the whole app."""
        r = client.get("/static/sw.js")
        assert r.status_code == 200
        assert "javascript" in r.headers.get("content-type", "").lower()

    def test_sw_pre_caches_static_shell(self, client, db):
        r = client.get("/static/sw.js")
        assert "/static/style.css" in r.text
        assert "/static/manifest.webmanifest" in r.text

    def test_sw_ignores_state_changing_requests(self, client, db):
        """GET-only caching — POST/PUT/DELETE must never be served from cache."""
        r = client.get("/static/sw.js")
        assert 'req.method !== "GET"' in r.text


class TestIcons:
    def test_icon_192_is_a_png(self, client, db):
        r = client.get("/static/icons/icon-192.png")
        assert r.status_code == 200
        # PNG signature: 89 50 4E 47 0D 0A 1A 0A
        assert r.content[:8] == b"\x89PNG\r\n\x1a\n"

    def test_icon_512_is_a_png(self, client, db):
        r = client.get("/static/icons/icon-512.png")
        assert r.status_code == 200
        assert r.content[:8] == b"\x89PNG\r\n\x1a\n"

    def test_apple_touch_icon_served(self, client, db):
        r = client.get("/static/icons/apple-touch-icon.png")
        assert r.status_code == 200
        assert r.content[:8] == b"\x89PNG\r\n\x1a\n"

    def test_maskable_icon_served(self, client, db):
        r = client.get("/static/icons/icon-512-maskable.png")
        assert r.status_code == 200
        assert r.content[:8] == b"\x89PNG\r\n\x1a\n"


class TestBaseHtmlPwaTags:
    def test_manifest_link_in_head(self, client, db):
        r = client.get("/login")
        assert '<link rel="manifest" href="/static/manifest.webmanifest">' in r.text

    def test_theme_color_meta_in_head(self, client, db):
        r = client.get("/login")
        assert '<meta name="theme-color" content="#00A651">' in r.text

    def test_apple_meta_tags_in_head(self, client, db):
        r = client.get("/login")
        assert '<link rel="apple-touch-icon" href="/static/icons/apple-touch-icon.png">' in r.text
        assert '<meta name="apple-mobile-web-app-capable" content="yes">' in r.text

    def test_service_worker_registered(self, client, db):
        r = client.get("/login")
        # The SW is registered on the ``load`` event so it doesn't compete
        # with the page rendering. Just check the registration call is
        # present in the page source.
        assert 'navigator.serviceWorker.register("/static/sw.js"' in r.text


class TestInstallPage:
    def test_install_page_renders(self, client, db):
        r = client.get("/install")
        assert r.status_code == 200
        assert "App installeren" in r.text or "Insigne Systeem op je telefoon" in r.text

    def test_install_page_covers_both_platforms(self, client, db):
        r = client.get("/install")
        assert "Android" in r.text
        assert "iPhone" in r.text or "iOS" in r.text or "Safari" in r.text

    def test_install_page_does_not_require_auth(self, client, db):
        """Anonymous users must be able to read install instructions
        before signing in."""
        r = client.get("/install", follow_redirects=False)
        assert r.status_code == 200

    def test_footer_links_to_install(self, client, db):
        """The install link must be reachable from every page."""
        r = client.get("/login")
        assert 'href="/install"' in r.text


class TestOfflinePage:
    def test_offline_page_renders(self, client, db):
        r = client.get("/offline")
        assert r.status_code == 200
        assert "Geen verbinding" in r.text

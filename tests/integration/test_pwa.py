"""PWA wrapper (#101): manifest, service worker, icons, install page,
offline fallback, and the PWA meta tags in base.html."""
import json


def _auth(client, db, *, email="u@example.com", admin=False):
    from insigne.config import config
    from insigne.models import User
    from insigne.auth import create_access_token
    if admin:
        config.admins = [email]
    u = User(email=email, name="U", status="active", password_hash="x")
    db.add(u); db.commit()
    token, _ = create_access_token(u.id)
    client.cookies.set("access_token", token)
    return u


class TestClientSideFilters:
    """Favorites / in-progress filters are client-side (badge_filters.js) so they
    work offline and instantly — no ?only_favorites server round-trip."""

    def test_script_served_and_pre_cached(self, client, db):
        r = client.get("/static/badge_filters.js")
        assert r.status_code == 200
        assert "javascript" in r.headers.get("content-type", "").lower()
        sw = client.get("/sw.js").text
        assert "/static/badge_filters.js" in sw  # in the offline shell

    def test_home_has_filter_root_and_data_attrs(self, client, db):
        _auth(client, db)
        r = client.get("/")
        assert "data-badge-filter" in r.text
        assert "badge-filter-fav" in r.text and "badge-filter-prog" in r.text
        assert "badge-item" in r.text and "data-fav=" in r.text and "data-prog=" in r.text

    def test_home_renders_all_badges_regardless_of_query(self, client, db):
        """Server no longer filters — ?only_favorites=1 still renders every
        badge (the client filters); the old param is harmless."""
        _auth(client, db)
        all_items = client.get("/").text.count('class="badge-item"')
        filtered = client.get("/?only_favorites=1&only_in_progress=1").text.count('class="badge-item"')
        assert all_items > 0
        assert filtered == all_items

    def test_speltak_progress_filter_root_with_init(self, client, db):
        from insigne import groups as groups_svc
        from insigne.models import SpeltakMembership
        leider = _auth(client, db, email="l@example.com")
        g = groups_svc.create_group(db, name="G", slug="g-flt", created_by_id=leider.id)
        s = groups_svc.create_speltak(db, group_id=g.id, name="S", slug="s-flt")
        db.add(SpeltakMembership(user_id=leider.id, speltak_id=s.id,
                                 role="speltakleider", approved=True))
        db.commit()
        r = client.get("/groups/g-flt/speltakken/s-flt/progress")
        assert r.status_code == 200
        assert "data-badge-filter" in r.text
        assert "badge-filter-fav" in r.text
        assert 'data-init-fav="0"' in r.text  # no favourites set → default off


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
        """The service worker must be served from the ROOT (/sw.js), not
        /static/, so it can register with ``scope: /``. A worker under /static/
        may only control /static/ unless the response sends
        Service-Worker-Allowed — serving it at the root avoids that footgun."""
        r = client.get("/sw.js")
        assert r.status_code == 200
        assert "javascript" in r.headers.get("content-type", "").lower()

    def test_sw_allows_root_scope(self, client, db):
        """Belt-and-suspenders header so the root-scope registration can never
        be rejected with a SecurityError (the bug that left the SW unregistered
        and offline navigation showing the browser error page)."""
        r = client.get("/sw.js")
        assert r.headers.get("service-worker-allowed") == "/"

    def test_sw_pre_caches_static_shell(self, client, db):
        r = client.get("/sw.js")
        assert "/static/style.css" in r.text
        assert "/static/manifest.webmanifest" in r.text

    def test_sw_ignores_state_changing_requests(self, client, db):
        """GET-only caching — POST/PUT/DELETE must never be served from cache."""
        r = client.get("/sw.js")
        assert 'req.method !== "GET"' in r.text

    def test_sw_pre_caches_vendored_js(self, client, db):
        """HTMX and Alpine are vendored locally and pre-cached so the app
        stays interactive offline — the SW skips cross-origin requests, so
        these must be same-origin and in the shell list."""
        r = client.get("/sw.js")
        assert "/static/vendor/htmx.min.js" in r.text
        assert "/static/vendor/alpine.min.js" in r.text


class TestVendoredJs:
    """HTMX and Alpine must be served same-origin (not from a CDN) so the
    service worker can cache them — see TestServiceWorker."""

    def test_htmx_served_locally(self, client, db):
        r = client.get("/static/vendor/htmx.min.js")
        assert r.status_code == 200
        assert "javascript" in r.headers.get("content-type", "").lower()

    def test_alpine_served_locally(self, client, db):
        r = client.get("/static/vendor/alpine.min.js")
        assert r.status_code == 200
        assert "javascript" in r.headers.get("content-type", "").lower()

    def test_base_html_references_local_not_cdn(self, client, db):
        """No CDN <script src> for the core libraries — they must point at
        /static/vendor/ so they work offline and behind CDN-blocking networks."""
        r = client.get("/login")
        assert '<script src="/static/vendor/htmx.min.js?v=' in r.text
        assert '<script src="/static/vendor/alpine.min.js?v=' in r.text
        assert "unpkg.com" not in r.text
        assert "alpinejs@" not in r.text


class TestStaticCaching:
    def test_static_assets_immutable(self, client, db):
        """/static is immutably cached (Lighthouse efficient-cache-policy)."""
        for path in ("/static/style.css", "/static/vendor/htmx.min.js",
                     "/static/manifest.webmanifest"):
            cc = client.get(path).headers.get("cache-control", "")
            assert "max-age=31536000" in cc and "immutable" in cc, path

    def test_changing_assets_are_version_busted(self, client, db):
        """style.css / badge_filters.js carry ?v={app_version} so the immutable
        cache busts on each release."""
        r = client.get("/login")
        assert "/static/style.css?v=" in r.text
        assert "/static/badge_filters.js?v=" in r.text
        # Vendored libs are version-busted too, so a security patch reaches
        # clients despite the immutable cache.
        assert "/static/vendor/htmx.min.js?v=" in r.text
        assert "/static/vendor/alpine.min.js?v=" in r.text

    def test_service_worker_not_immutably_cached(self, client, db):
        """The worker itself must stay bustable, or deploys never reach clients."""
        cc = client.get("/sw.js").headers.get("cache-control", "")
        assert "immutable" not in cc

    def test_sw_ignores_search_for_static(self, client, db):
        """The SW matches /static cache-first ignoring the ?v= query."""
        assert "ignoreSearch" in client.get("/sw.js").text


class TestImageCaching:
    def test_badge_images_have_immutable_cache(self, client, db):
        """Badge artwork never changes under the same URL, so /images carries a
        1-year immutable Cache-Control (Lighthouse efficient-cache-policy)."""
        from insigne.badges import BadgeCatalogue
        from pathlib import Path
        cat = BadgeCatalogue(Path(__file__).parent.parent.parent / "api" / "data")
        img = next(
            (b["images"][0] for badges in cat.list().values()
             for b in badges if b.get("images")),
            None,
        )
        assert img, "no catalogue image to test"
        r = client.get(img)
        assert r.status_code == 200
        cc = r.headers.get("cache-control", "")
        assert "max-age=31536000" in cc and "immutable" in cc


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

    def test_open_graph_tags_in_head(self, client, db):
        """#140: social scrapers (WhatsApp/Slack/Facebook) render a card from
        Open Graph tags; og:image must be an absolute-URL raster (not the SVG
        favicon) so WhatsApp shows a thumbnail."""
        from insigne.config import config
        r = client.get("/login")
        assert '<meta property="og:title"' in r.text
        assert '<meta property="og:description"' in r.text
        # og:image is absolute and a PNG (WhatsApp can't render the SVG favicon).
        assert f'<meta property="og:image" content="{config.base_url}/static/icons/icon-512.png">' in r.text
        assert '<meta name="twitter:card" content="summary">' in r.text

    def test_service_worker_registered(self, client, db):
        r = client.get("/login")
        # The SW is registered on the ``load`` event so it doesn't compete
        # with the page rendering. Just check the registration call is
        # present in the page source.
        assert 'navigator.serviceWorker.register("/sw.js"' in r.text


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

    def test_user_menu_links_to_install(self, client, db):
        """The install link sits in the authenticated user dropdown
        (below Importeren/exporteren) — anonymous users hit /install
        directly via the URL or via instructions we hand them."""
        from insigne.models import User
        from insigne.auth import create_access_token
        u = User(email="u@example.com", name="U", status="active", password_hash="x")
        db.add(u); db.commit()
        token, _ = create_access_token(u.id)
        client.cookies.set("access_token", token)
        r = client.get("/")
        assert r.status_code == 200
        assert 'class="nav-user-item">App installeren' in r.text or \
               '"nav-user-item">App installeren' in r.text

    def test_anonymous_user_does_not_see_install_link(self, client, db):
        """Logged-out users have no dropdown menu, so no install link
        is rendered in the chrome. The /install page itself is still
        reachable directly."""
        r = client.get("/login")
        assert "App installeren" not in r.text


class TestOfflinePage:
    def test_offline_page_renders(self, client, db):
        r = client.get("/offline")
        assert r.status_code == 200
        assert "Geen verbinding" in r.text


class TestOfflineDisabledPage:
    """Aftekeningen / Groepsbeheer / Admin fall back to this page offline."""

    def test_disabled_page_renders(self, client, db):
        r = client.get("/offline/disabled")
        assert r.status_code == 200
        assert "Werkt niet offline" in r.text

    def test_sw_pre_caches_disabled_page(self, client, db):
        r = client.get("/sw.js")
        assert "/offline/disabled" in r.text

    def test_sw_routes_disabled_paths_offline(self, client, db):
        """The SW must recognise the screens that can't work offline, and must
        keep the leader progress overview (.../progress) available."""
        r = client.get("/sw.js")
        for marker in ('"/admin"', '"/signoff-requests"', '"/requests"', '"/contact"', '"/groups"'):
            assert marker in r.text
        assert 'endsWith("/progress")' in r.text

    def test_contact_link_disabled_offline(self, client, db):
        """The contact form needs the network, so its footer link greys out."""
        r = client.get("/login")
        assert '<a href="/contact" class="offline-disabled"' in r.text


class TestOfflineManifest:
    """The 'Maak offline beschikbaar' button warms these URLs into the cache."""

    def test_manifest_served(self, client, db):
        r = client.get("/offline/manifest.json")
        assert r.status_code == 200
        assert r.json()["urls"]

    def test_manifest_covers_every_badge(self, client, db):
        from insigne.badges import BadgeCatalogue
        from pathlib import Path
        cat = BadgeCatalogue(Path(__file__).parent.parent.parent / "api" / "data")
        urls = set(client.get("/offline/manifest.json").json()["urls"])
        for badges in cat.list().values():
            for badge in badges:
                assert f"/badges/{badge['slug']}" in urls, badge["slug"]
                for img in badge.get("images", []):
                    assert img in urls

    def test_manifest_is_one_url_per_badge_no_niveau_variants(self, client, db):
        """Niveau switching is client-side, so the manifest needs only the bare
        /badges/{slug} URL — no ?niveau= / ?speltak= query variants."""
        urls = client.get("/offline/manifest.json").json()["urls"]
        assert not any("?" in u for u in urls)

    def test_manifest_anonymous_has_no_user_pages(self, client, db):
        urls = client.get("/offline/manifest.json").json()["urls"]
        assert "/my-speltakken" not in urls

    def test_manifest_includes_leader_speltak_progress(self, client, db):
        """A logged-in leader's home + speltak progress overviews are warmed too,
        so they're available offline (the original leader-offline goal)."""
        from insigne import groups as groups_svc
        from insigne.models import User, SpeltakMembership
        from insigne.auth import create_access_token
        leider = User(email="l@example.com", name="L", status="active", password_hash="x")
        db.add(leider); db.commit()
        g = groups_svc.create_group(db, name="G", slug="g-pwa", created_by_id=leider.id)
        s = groups_svc.create_speltak(db, group_id=g.id, name="S", slug="s-pwa")
        db.add(SpeltakMembership(user_id=leider.id, speltak_id=s.id,
                                 role="speltakleider", approved=True))
        db.commit()
        token, _ = create_access_token(leider.id)
        client.cookies.set("access_token", token)
        urls = client.get("/offline/manifest.json").json()["urls"]
        assert "/" in urls
        assert "/my-speltakken" in urls
        assert "/groups/g-pwa/speltakken/s-pwa/progress" in urls


class TestOfflineReadOnlyMode:
    """Offline = read-only: a banner appears and edit controls are greyed out
    (body.offline), driven by online/offline events."""

    def test_base_html_has_offline_banner(self, client, db):
        r = client.get("/login")
        assert 'class="offline-banner"' in r.text

    def test_base_html_toggles_offline_class(self, client, db):
        r = client.get("/login")
        assert 'addEventListener("offline"' in r.text
        assert 'classList.toggle("offline"' in r.text

    def test_base_html_blocks_offline_mutations(self, client, db):
        """State-changing HTMX requests are cancelled while offline."""
        r = client.get("/login")
        assert "htmx:beforeRequest" in r.text

    def test_offline_detection_probes_ping(self, client, db):
        """navigator.onLine is unreliable (stays true on reload under
        throttling / no-internet), so offline detection also probes /ping."""
        r = client.get("/login")
        assert '/ping' in r.text

    def test_offline_banner_has_retry_link(self, client, db):
        """Reconnecting is user-driven: the banner offers a reload link rather
        than auto-clearing (a single ping may pass on a spotty link)."""
        r = client.get("/login")
        assert "offline-banner-retry" in r.text
        assert "Opnieuw proberen" in r.text

    def test_ping_endpoint_is_204(self, client, db):
        r = client.get("/ping")
        assert r.status_code == 204

    def test_sw_does_not_intercept_ping(self, client, db):
        """The probe must hit the real network, so the SW bypasses /ping."""
        r = client.get("/sw.js")
        assert '/ping' in r.text  # referenced in the bypass guard


class TestSyncScreen:
    def test_sync_page_has_download_button(self, client, db):
        r = client.get("/sync")
        assert r.status_code == 200
        assert "Nu synchroniseren" in r.text
        assert "offlineDownload" in r.text

    def test_install_page_no_longer_has_download_button(self, client, db):
        """The sync button moved to its own /sync screen."""
        r = client.get("/install")
        assert "offlineDownload" not in r.text

    def test_sync_menu_item_always_shown_to_users(self, client, db):
        """The 'Data synchroniseren' menu item is shown to any logged-in user
        (not gated on PWA support) so an unsupported browser can still reach
        /sync and see why offline isn't available."""
        from insigne.models import User
        from insigne.auth import create_access_token
        u = User(email="s@example.com", name="S", status="active", password_hash="x")
        db.add(u); db.commit()
        token, _ = create_access_token(u.id)
        client.cookies.set("access_token", token)
        r = client.get("/")
        assert 'href="/sync"' in r.text
        assert "pwa-only" not in r.text  # no longer gated

    def test_sync_page_explains_when_unsupported(self, client, db):
        """/sync detects a browser without the PWA cache on load and shows an
        explanation of the feature + how to enable it (not only after a click)."""
        r = client.get("/sync")
        assert "serviceWorker" in r.text and "caches" in r.text  # x-init capability check
        assert "ondersteunt offline gebruik" in r.text  # the unsupported notice
        assert "Waarvoor is dit?" in r.text and "Hoe krijg je het werkend?" in r.text
        assert 'href="/install"' in r.text  # link to install instructions


class TestBadgeNiveausClientSide:
    """All three niveaus render at /badges/{slug} (one cacheable URL) and niveau
    selection is client-side — no server redirect to ?niveau=N."""

    def _a_regular_slug(self):
        from insigne.badges import BadgeCatalogue
        from pathlib import Path
        cat = BadgeCatalogue(Path(__file__).parent.parent.parent / "api" / "data")
        return next(
            b["slug"] for badges in cat.list().values()
            for b in badges if b.get("type") != "jaarinsigne"
        )

    def test_all_niveaus_rendered(self, client, db):
        r = client.get(f"/badges/{self._a_regular_slug()}")
        assert r.status_code == 200
        assert "niveau-cell--1" in r.text
        assert "niveau-cell--2" in r.text
        assert "niveau-cell--3" in r.text

    def test_no_mobile_redirect_script(self, client, db):
        r = client.get(f"/badges/{self._a_regular_slug()}")
        assert "location.replace" not in r.text

    def test_bare_url_shows_all_niveaus(self, client, db):
        """No ?niveau= → the compare view (all three columns)."""
        r = client.get(f"/badges/{self._a_regular_slug()}")
        assert 'data-niveau="all"' in r.text

    def test_niveau_param_focuses_single_niveau(self, client, db):
        """?niveau=N (e.g. from the home page) → that niveau is focused, not all."""
        slug = self._a_regular_slug()
        r = client.get(f"/badges/{slug}?niveau=2")
        assert 'data-niveau="2"' in r.text
        assert 'data-niveau="all"' not in r.text

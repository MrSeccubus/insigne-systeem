// Insigne Systeem service worker (#101).
//
// Strategy:
//   - HTML responses (any same-origin navigation): network-first with a
//     cache fallback. Online users always get fresh data; offline users
//     fall back to the last cached version of whatever they last loaded,
//     then to the offline fallback page if nothing matches.
//   - /static/* (CSS, icons, manifest, this worker's own fetches):
//     cache-first. The static shell is pre-cached on install.
//   - /images/* (badge artwork): cache-first too — these files never
//     change under the same URL.
//   - /api/* is unused since v1.2.0 (#117) but kept on the network-only
//     allowlist as a safety net in case it ever comes back.
//   - HTMX swap responses (carry the ``HX-Request: true`` request header,
//     which we can't read here, so we conservatively never cache anything
//     that isn't GET).
//
// Updates: ``skipWaiting`` + ``clients.claim`` so a new deploy applies on
// the next reload without forcing the user to close all tabs.

const VERSION = "v3";
const SHELL_CACHE = `shell-${VERSION}`;
const RUNTIME_CACHE = `runtime-${VERSION}`;

const SHELL_ASSETS = [
    "/static/style.css",
    "/static/favicon.svg",
    "/static/icons/icon-192.png",
    "/static/icons/icon-512.png",
    "/static/icons/icon-512-maskable.png",
    "/static/icons/apple-touch-icon.png",
    "/static/manifest.webmanifest",
    "/static/vendor/htmx.min.js",
    "/static/vendor/alpine.min.js",
    "/offline",
    "/offline/disabled",
];

// Paths whose screens can't work offline (aftekeningen, groepsbeheer, admin):
// when the network is gone we serve the "werkt niet offline" page instead of a
// stale cached copy. ``/groups/**/progress`` is the read-only leader overview
// and stays available, so it's excluded. ``/my-speltakken`` is not under
// ``/groups`` and stays cacheable too.
function isOfflineDisabledPath(pathname) {
    if (pathname.startsWith("/admin")) return true;
    if (pathname.startsWith("/signoff-requests")) return true;
    if (pathname.startsWith("/requests")) return true;
    if (pathname.startsWith("/groups") && !pathname.endsWith("/progress")) return true;
    return false;
}

self.addEventListener("install", (event) => {
    event.waitUntil(
        caches.open(SHELL_CACHE)
            .then((cache) => cache.addAll(SHELL_ASSETS))
            .then(() => self.skipWaiting())
    );
});

self.addEventListener("activate", (event) => {
    event.waitUntil(
        caches.keys()
            .then((keys) => Promise.all(
                keys
                    .filter((k) => k !== SHELL_CACHE && k !== RUNTIME_CACHE)
                    .map((k) => caches.delete(k))
            ))
            .then(() => self.clients.claim())
    );
});

self.addEventListener("fetch", (event) => {
    const req = event.request;
    if (req.method !== "GET") return;  // never cache state-changing requests
    const url = new URL(req.url);
    if (url.origin !== self.location.origin) return;
    if (url.pathname.startsWith("/api/")) return;  // future-proof: don't cache API
    if (url.pathname === "/ping") return;  // connectivity probe must hit the real network

    // Cache-first for static + images (URLs that never change content).
    if (url.pathname.startsWith("/static/") || url.pathname.startsWith("/images/")) {
        event.respondWith(
            caches.match(req).then((cached) => cached || fetch(req).then((resp) => {
                if (resp.ok) {
                    const copy = resp.clone();
                    caches.open(RUNTIME_CACHE).then((c) => c.put(req, copy));
                }
                return resp;
            }))
        );
        return;
    }

    // Network-first for HTML / everything else, with a cache fallback.
    event.respondWith(
        fetch(req).then((resp) => {
            if (resp.ok && resp.headers.get("content-type")?.includes("text/html")) {
                const copy = resp.clone();
                caches.open(RUNTIME_CACHE).then((c) => c.put(req, copy));
            }
            return resp;
        }).catch(() => {
            // Offline. The HTML fallback pages are only appropriate for full
            // page navigations — never for sub-resource / HTMX-partial GETs
            // (e.g. the sign-off counter), or we'd inject a whole page into a
            // tiny element. ``req.mode === "navigate"`` distinguishes the two.
            const isNavigation = req.mode === "navigate";
            // Screens that can't work offline get the disabled page — checked
            // BEFORE the cache, since they may also be runtime-cached.
            if (isNavigation && isOfflineDisabledPath(url.pathname)) {
                return caches.match("/offline/disabled").then((d) => d || caches.match("/offline"));
            }
            return caches.match(req).then((cached) => {
                if (cached) return cached;
                if (isNavigation) {
                    return caches.match("/offline").then((off) => off || new Response(
                        "Geen verbinding.",
                        { status: 503, headers: { "Content-Type": "text/plain; charset=utf-8" } }
                    ));
                }
                // Sub-resource / partial with no cache entry: fail quietly so
                // it can't inject an HTML page into the DOM.
                return new Response("", { status: 503 });
            });
        })
    );
});

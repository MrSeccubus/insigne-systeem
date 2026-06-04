// Client-side badge filtering (favorites / in-progress) for the home page and
// the speltak progress page. Pure DOM — works offline, instant online, no
// navigation. Replaces the old server-side ?only_favorites/?only_in_progress.
//
// Each page has one filter root: an element with [data-badge-filter] carrying
// data-init-fav / data-init-prog (server default state) and data-has-fav
// (whether the user has any favorites — picks the right empty-state message).
// Inside it: .badge-item elements with data-fav / data-prog ("1"/"0"), category
// sections .badge-cat, and hidden empty-state variants .badge-empty[data-empty].
// Toggle buttons are .badge-filter-fav / .badge-filter-prog. The two filters are
// independent and combine with AND.
(function () {
    function emptyKey(fav, prog, hasFav) {
        if (fav && prog) return "favprog";
        if (fav) return hasFav ? "fav" : "fav-none";
        if (prog) return "prog";
        return null;
    }

    function setActive(btn, on) {
        if (!btn) return;
        btn.classList.toggle("btn-star-active", on);
        btn.classList.toggle("btn-neutral", !on);
    }

    function init(root) {
        var url = new URLSearchParams(location.search);
        function initVal(param, dataKey) {
            // Explicit URL value wins (bookmark / after a toggle); otherwise the
            // server-provided default (e.g. speltak defaults to favourites).
            if (url.has(param)) return url.get(param) === "1";
            return root.dataset[dataKey] === "1";
        }
        var state = {
            fav: initVal("only_favorites", "initFav"),
            prog: initVal("only_in_progress", "initProg"),
        };
        var favBtn = root.querySelector(".badge-filter-fav");
        var progBtn = root.querySelector(".badge-filter-prog");

        function apply() {
            var anyVisible = false;
            root.querySelectorAll(".badge-item").forEach(function (item) {
                var ok = (!state.fav || item.dataset.fav === "1")
                      && (!state.prog || item.dataset.prog === "1");
                item.hidden = !ok;
                if (ok) anyVisible = true;
            });
            root.querySelectorAll(".badge-cat").forEach(function (cat) {
                cat.hidden = !cat.querySelector(".badge-item:not([hidden])");
            });
            var key = anyVisible ? null : emptyKey(state.fav, state.prog, root.dataset.hasFav === "1");
            root.querySelectorAll(".badge-empty").forEach(function (e) {
                e.hidden = e.dataset.empty !== key;
            });
            setActive(favBtn, state.fav);
            setActive(progBtn, state.prog);
        }

        function syncUrl() {
            var u = new URL(location.href);
            u.searchParams.set("only_favorites", state.fav ? "1" : "0");
            u.searchParams.set("only_in_progress", state.prog ? "1" : "0");
            history.replaceState(null, "", u);
        }

        function toggle(which) {
            state[which] = !state[which];
            syncUrl();
            apply();
        }

        if (favBtn) favBtn.addEventListener("click", function () { toggle("fav"); });
        if (progBtn) progBtn.addEventListener("click", function () { toggle("prog"); });

        // After a favorite-star HTMX swap, re-derive each item's data-fav from
        // its star button (the swap only replaces the button, not the wrapper)
        // so a live "favorites" filter updates.
        document.addEventListener("htmx:afterSwap", function () {
            root.querySelectorAll(".badge-item").forEach(function (item) {
                var star = item.querySelector('[hx-post$="toggle-badge"], [hx-post*="favorite-badge"]');
                if (star) item.dataset.fav = star.classList.contains("btn-star-active") ? "1" : "0";
            });
            apply();
        });

        apply();
    }

    function start() {
        document.querySelectorAll("[data-badge-filter]").forEach(init);
    }
    if (document.readyState === "loading") {
        document.addEventListener("DOMContentLoaded", start);
    } else {
        start();
    }
})();

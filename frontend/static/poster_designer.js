/* Poster designer (#132, Phase 1).
 *
 * Alpine component driving the param panel + live preview iframe. The preview
 * loads /posters/render?preview=1&… (same render as print, so preview == print);
 * paged.js inside the iframe paginates into exact A-series pages. Param changes
 * debounce-reload the iframe (full server render keeps pagination correct).
 * "Print" opens the same render URL (without preview) in its own window, where
 * paged.js auto-prints after layout.
 *
 * Config comes from a <script type="application/json" id="poster-designer-config">
 * block (NOT an x-data attribute): |tojson doesn't escape double quotes, so
 * interpolating it into an attribute is both an XSS risk and breaks the markup.
 */
(function () {
    function register() {
        Alpine.data('posterDesigner', () => {
            let cfg = {};
            try {
                const el = document.getElementById('poster-designer-config');
                if (el) cfg = JSON.parse(el.textContent);
            } catch (e) { /* fall back to empty defaults */ }
            return {
                posterType: cfg.posterType || 'badges',
                paperSize: cfg.paperSize || 'A4',
                orientation: cfg.orientation || 'portrait',
                name: cfg.name || '',
                params: cfg.params || {},
                posterId: cfg.posterId || '',
                editable: !!cfg.editable,
                filterSets: cfg.filterSets || {},
                scopeSel: 'user',

                // Min designer width — below this we don't build the preview
                // (the CSS shows the "te klein scherm" warning instead).
                get tooSmall() { return window.innerWidth < 1024; },

                init() {
                    if (!this.tooSmall) this.updatePreview();
                    window.addEventListener('resize', () => {
                        if (!this.tooSmall && this.$refs.preview && !this.$refs.preview.src) {
                            this.updatePreview();
                        }
                    });
                },

                renderUrl(preview) {
                    const p = new URLSearchParams();
                    p.set('type', this.posterType);
                    p.set('paper_size', this.paperSize);
                    p.set('orientation', this.orientation);
                    for (const [k, v] of Object.entries(this.params)) {
                        p.set(k, v === null || v === undefined ? '' : v);
                    }
                    if (preview) p.set('preview', '1');
                    return '/posters/render?' + p.toString();
                },

                updatePreview() {
                    if (this.tooSmall) return;
                    if (this.$refs.preview) this.$refs.preview.src = this.renderUrl(true);
                },

                printPoster() {
                    window.open(this.renderUrl(false), '_blank');
                },

                // Badge-grid quick selects (poster type 1).
                selectSet(name) {
                    this.params.badge_slugs = [...(this.filterSets[name] || [])];
                    this.updatePreview();
                },
                selectNone() {
                    this.params.badge_slugs = [];
                    this.updatePreview();
                },
            };
        });
    }

    // Register on alpine:init, or immediately if Alpine is already running
    // (guards against script load-order races).
    if (window.Alpine) register();
    else document.addEventListener('alpine:init', register);
})();

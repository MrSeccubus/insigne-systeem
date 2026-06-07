/* Poster designer (#132).
 *
 * Alpine component driving the wizard + live preview. The poster definition is
 * one nested object (`def`, the YAML shape as JSON); inputs bind into it. The
 * preview iframe loads /posters/render?def=<json>&preview=1 (same render as
 * print, so preview == print); paged.js inside it paginates into exact A-series
 * pages. Param changes debounce-reload the iframe. "Print" opens the same render
 * URL (without preview) in its own window, where paged.js auto-prints.
 *
 * Config comes from a <script type="application/json"> block (NOT an x-data
 * attribute): |tojson doesn't escape double quotes, which would be an XSS risk
 * and break the markup.
 */
(function () {
    function register() {
        Alpine.data('posterDesigner', () => {
            let cfg = {};
            try {
                const el = document.getElementById('poster-designer-config');
                if (el) cfg = JSON.parse(el.textContent);
            } catch (e) { /* empty defaults */ }
            return {
                def: cfg.definition || {},
                posterId: cfg.posterId || '',
                editable: !!cfg.editable,
                filterSets: cfg.filterSets || {},
                scopeSel: 'user',
                selected: '',   // which poster element is being edited
                saveOpen: false,
                proofMode: false,   // preview iframe shows the faithful (proof) render

                get tooSmall() { return window.innerWidth < 1024; },

                init() {
                    if (!this.tooSmall) this.updatePreview();
                    // The preview iframe posts which element was clicked.
                    window.addEventListener('message', (e) => {
                        if (e.origin !== window.location.origin) return;
                        if (e.data && e.data.source === 'poster-preview') {
                            this.selected = e.data.el || '';
                            this.updatePreview();   // reload to show the selection highlight
                        }
                    });
                    window.addEventListener('resize', () => {
                        if (!this.tooSmall && this.$refs.preview && !this.$refs.preview.src) {
                            this.updatePreview();
                        }
                    });
                },

                renderUrl(preview) {
                    const p = new URLSearchParams();
                    p.set('def', JSON.stringify(this.def));
                    if (preview) {
                        p.set('preview', '1');
                        if (this.selected) p.set('sel', this.selected);
                    }
                    return '/posters/render?' + p.toString();
                },

                updatePreview() {
                    if (this.tooSmall) return;
                    if (!this.$refs.preview) return;
                    if (this.proofMode) {
                        // Proof: the faithful render (no placeholders, not clickable),
                        // scaled to fit — shown in the same iframe, not a new window.
                        const p = new URLSearchParams();
                        p.set('def', JSON.stringify(this.def));
                        p.set('proof', '1');
                        this.$refs.preview.src = '/posters/render?' + p.toString();
                    } else {
                        this.$refs.preview.src = this.renderUrl(true);
                    }
                },

                printPoster() {
                    window.open(this.renderUrl(false), '_blank');
                },

                // Toggle the preview iframe between the editable view and the
                // faithful proof view (press again to return and edit).
                togglePreview() {
                    this.proofMode = !this.proofMode;
                    this.updatePreview();
                },

                // Badge-grid quick selects (poster type 0).
                badges() {
                    return (this.def.elements && this.def.elements.badge_block
                            && this.def.elements.badge_block.badges) || [];
                },
                selectSet(name) {
                    this.def.elements.badge_block.badges = [...(this.filterSets[name] || [])];
                    this.updatePreview();
                },
            };
        });
    }

    if (window.Alpine) register();
    else document.addEventListener('alpine:init', register);
})();

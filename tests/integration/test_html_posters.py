"""Poster designer (#132) — YAML-definition storage, sandboxed templating,
CRUD, scope/IDOR, export/import."""
import json
from datetime import datetime

import yaml

from insigne import groups as groups_svc
from insigne import poster_templates as pt
from insigne import posters as posters_svc
from insigne.auth import create_access_token
from insigne.config import config
from insigne.models import PosterTemplate, SpeltakMembership, User


def _user(db, *, email="u@example.com", name="U", admin=False):
    if admin:
        config.admins = [email]
    u = User(email=email, name=name, status="active", password_hash="x")
    db.add(u)
    db.commit()
    return u


def _login(client, user):
    token, _ = create_access_token(user.id)
    client.cookies.set("access_token", token)


def _defn(**over):
    d = pt.base_definition(over.pop("type", 0))
    badges = over.pop("badges", None)
    if badges is not None:
        d["elements"]["badge_block"]["badges"] = badges
    if "niveau" in over:
        d["elements"]["badge_block"]["niveaus"] = [over.pop("niveau")]
    d.update(over)
    return d


def _create(db, user, **over):
    return posters_svc.create(db, created_by_id=user.id, definition=_defn(**over),
                              scope="user", scope_id=None)


def _speltakleider(db, *, email):
    leider = _user(db, email=email)
    g = groups_svc.create_group(db, name="Groep", slug=f"g-{email[:4]}", created_by_id=leider.id)
    s = groups_svc.create_speltak(db, group_id=g.id, name="Stam", slug=f"s-{email[:4]}")
    db.add(SpeltakMembership(user_id=leider.id, speltak_id=s.id, role="speltakleider", approved=True))
    db.commit()
    return leider, g, s


# ── List / wizard chooser ─────────────────────────────────────────────────────

class TestPostersList:
    def test_anonymous_redirects_to_login(self, client, db):
        r = client.get("/posters", follow_redirects=False)
        assert r.status_code == 303 and r.headers["location"] == "/login"

    def test_shows_wizard_chooser(self, client, db):
        _login(client, _user(db))
        r = client.get("/posters")
        assert r.status_code == 200
        assert "Wat wil je doen?" in r.text
        for t in ("badges", "speltak", "signoff"):
            assert f"/posters/new?type={t}" in r.text
        assert "/posters/import" in r.text  # import form

    def test_existing_posters_listed(self, client, db):
        u = _user(db)
        _login(client, u)
        _create(db, u, name="Bestaande")
        assert "Bestaande" in client.get("/posters").text


# ── Designer ──────────────────────────────────────────────────────────────────

class TestPosterDesigner:
    def test_new_seeds_base_definition(self, client, db):
        _login(client, _user(db))
        r = client.get("/posters/new?type=badges")
        assert r.status_code == 200
        assert "Insigneposter" in r.text          # base title, seeded into config
        assert "poster_designer.js" in r.text

    def test_new_unknown_type_falls_back(self, client, db):
        _login(client, _user(db))
        assert client.get("/posters/new?type=bogus").status_code == 200

    def test_is_click_to_edit(self, client, db):
        _login(client, _user(db))
        r = client.get("/posters/new?type=badges")
        assert "Klik op een element" in r.text     # empty-pane hint
        assert "poster-editor" in r.text
        assert "poster-bar" in r.text              # persistent name/save/print bar
        assert "Insigne-blok" in r.text            # an element editor heading

    def test_save_and_print_icons(self, client, db):
        _login(client, _user(db))
        r = client.get("/posters/new?type=badges")
        assert 'aria-label="Printen"' in r.text   # print button is icon-only
        assert 'aria-label="Opslaan"' in r.text   # save button is icon-only
        assert "Font Awesome" in r.text           # inline SVG icons included

    def test_text_fields_have_template_help(self, client, db):
        _login(client, _user(db))
        r = client.get("/posters/new?type=badges")
        # title/subtitle/header/footer each carry the disclosure
        assert r.text.count("Sjabloonvelden gebruiken") >= 4
        assert "{{ user.name }}" in r.text and "{{ datum }}" in r.text

    def test_huisstijl_color_swatches(self, client, db):
        _login(client, _user(db))
        r = client.get("/posters/new?type=badges")
        assert "Scouting blauw" in r.text and "Scouting groen" in r.text
        assert 'id="poster-huisstijl"' in r.text   # datalist for the native picker

    def test_toolbar_and_save_dialog(self, client, db):
        _login(client, _user(db))
        r = client.get("/posters/new?type=badges")
        assert "Pagina-eigenschappen" in r.text   # page-properties button in the toolbar
        assert "poster-modal" in r.text           # save name/scope dialog
        assert "poster-divider" in r.text

    def test_small_screen_guard(self, client, db):
        _login(client, _user(db))
        r = client.get("/posters/new?type=badges")
        assert "poster-toosmall" in r.text and "Te klein scherm" in r.text

    def test_badge_picker_present(self, client, db):
        _login(client, _user(db))
        r = client.get("/posters/new?type=badges")
        assert "poster-badge-list" in r.text
        assert 'value="vredeslicht"' in r.text
        assert "filterSets" in r.text

    def test_config_is_xss_safe(self, client, db):
        u = _user(db)
        _login(client, u)
        p = _create(db, u, name='"></script><img src=x onerror=alert(1)>',
                    title='"><img src=y onerror=alert(2)>')
        r = client.get(f"/posters/{p.id}")
        assert r.status_code == 200
        assert 'x-data="posterDesigner()"' in r.text
        assert "<img src=x onerror" not in r.text
        assert "<img src=y onerror" not in r.text
        assert "</script><img" not in r.text


# ── Render (standalone) + templating ──────────────────────────────────────────

class TestPosterRender:
    def _get(self, client, defn, **extra):
        params = {"def": json.dumps(defn)}
        params.update(extra)
        return client.get("/posters/render", params=params)

    def test_page_size_a4(self, client, db):
        _login(client, _user(db))
        r = self._get(client, _defn(paper="A4", orientation="portrait"))
        assert r.status_code == 200
        assert "size: 210mm 297mm" in r.text

    def test_single_page_is_default(self, client, db):
        """Default multi_page=False → fit on one page, no paged.js."""
        _login(client, _user(db))
        r = self._get(client, _defn(badges=["vredeslicht"]))
        assert "paged.polyfill.js" not in r.text
        assert "poster-page" in r.text   # single fixed-page wrapper

    def test_multi_page_uses_pagedjs(self, client, db):
        _login(client, _user(db))
        d = _defn(badges=["vredeslicht"])
        d["multi_page"] = True
        r = self._get(client, d)
        assert "/static/vendor/paged.polyfill.js" in r.text
        assert "poster-page" not in r.text

    def test_single_page_preserves_paper_size(self, client, db):
        """Fitting to one page keeps the chosen paper — it doesn't collapse to A4."""
        _login(client, _user(db))
        r = self._get(client, _defn(paper="A2", orientation="portrait", badges=["vredeslicht"]))
        assert "size: 420mm 594mm" in r.text                 # @page = chosen paper
        assert "width:420mm;height:594mm" in r.text          # full-page sheet (background fills it)

    def test_background_fills_page_via_var(self, client, db):
        """Background is set on the page surface (--poster-bg), not the scaled .poster."""
        _login(client, _user(db))
        d = _defn(badges=["vredeslicht"])
        d["elements"]["background"] = {"style": "horizontal_gradient",
                                       "start_color": "red", "end_color": "green"}
        r = self._get(client, d)
        assert "--poster-bg: linear-gradient(to right,red,green)" in r.text

    def test_badge_title_drops_insigne_word(self, client, db):
        _login(client, _user(db))
        r = self._get(client, _defn(badges=["vredeslicht"]))   # title "Insigne Vredeslicht"
        assert ">Vredeslicht<" in r.text
        assert "Insigne Vredeslicht" not in r.text

    def test_a2_landscape_swaps(self, client, db):
        _login(client, _user(db))
        r = self._get(client, _defn(paper="A2", orientation="landscape"))
        assert "size: 594mm 420mm" in r.text

    def test_print_only_when_not_preview(self, client, db):
        _login(client, _user(db))
        assert "window.print()" in self._get(client, _defn()).text
        assert "window.print()" not in self._get(client, _defn(), preview="1").text

    def test_selected_badge_images(self, client, db):
        _login(client, _user(db))
        r = self._get(client, _defn(badges=["vredeslicht"], niveau=1))
        assert 'src="/images/vredeslicht.1.png"' in r.text

    def test_niveau_selects_image(self, client, db):
        _login(client, _user(db))
        r = self._get(client, _defn(badges=["vredeslicht"], niveau=2))
        assert 'src="/images/vredeslicht.2.png"' in r.text

    def test_unknown_slug_dropped(self, client, db):
        _login(client, _user(db))
        r = self._get(client, _defn(badges=["vredeslicht", "not-a-real-badge"]))
        assert "/images/vredeslicht" in r.text
        assert "not-a-real-badge" not in r.text

    def test_templating_user_and_date(self, client, db):
        _login(client, _user(db, name="Jan Jansen"))
        r = self._get(client, _defn(title="Hallo {{ user.name }}", header="{{ date }}"))
        assert "Hallo Jan Jansen" in r.text
        assert str(datetime.now().year) in r.text
        assert "{{ date }}" not in r.text

    def test_templating_is_sandboxed(self, client, db):
        """SSTI probes must render inert (caught → empty), never leak internals or 500."""
        _login(client, _user(db))
        for payload in ("{{ self.__init__.__globals__ }}",
                        "{{ ''.__class__.__mro__ }}",
                        "{{ cycler.__init__.__globals__ }}"):
            r = self._get(client, _defn(title=payload))
            assert r.status_code == 200
            for marker in ("__globals__", "__class__", "__mro__", "builtins", "<class"):
                assert marker not in r.text

    def test_html_in_field_escaped(self, client, db):
        _login(client, _user(db))
        r = self._get(client, _defn(title="<b>x</b>"))
        assert "<b>x</b>" not in r.text
        assert "&lt;b&gt;x&lt;/b&gt;" in r.text

    def test_empty_badges_renders_all_default_categories(self, client, db):
        """badges: [] = all gewoon + buitengewoon (not explorers/jaarinsignes)."""
        _login(client, _user(db))
        r = self._get(client, _defn(badges=[]))
        assert "/images/internationaal.1.png" in r.text   # a gewoon badge
        assert "/images/jaarinsigne_2026" not in r.text    # jaarinsignes excluded
        assert "/images/explorer_jaarbadge" not in r.text  # explorers excluded

    def test_niveaus_emit_one_image_each(self, client, db):
        _login(client, _user(db))
        d = _defn(badges=["vredeslicht"])
        d["elements"]["badge_block"]["niveaus"] = [1, 2, 3]
        r = self._get(client, d)
        for n in (1, 2, 3):
            assert f"/images/vredeslicht.{n}.png" in r.text

    def test_handpicked_badges_render_in_catalogue_order(self, client, db):
        """A few hand-picked badges appear in catalogue order, not click order."""
        _login(client, _user(db))
        # 'internationaal' precedes 'kamperen' in the catalogue; pick them reversed.
        r = self._get(client, _defn(badges=["kamperen", "internationaal"]))
        assert r.text.index("/images/internationaal") < r.text.index("/images/kamperen")

    def test_jaarinsigne_image_sized_like_others(self, client, db):
        """A jaarinsigne's single image is sized per-niveau (not full column)."""
        _login(client, _user(db))
        r = self._get(client, _defn(badges=["jaarinsigne_2026"]))
        assert "--poster-levels:3" in r.text
        assert "/images/jaarinsigne_2026.png" in r.text

    def test_activiteitengebied_callout(self, client, db):
        _login(client, _user(db))
        r = self._get(client, _defn(badges=[]))   # all gewoon + buitengewoon
        assert "poster-badge-callout" in r.text
        assert "Uitdagende Scoutingtechnieken" in r.text   # a gebied callout

    def test_activiteitengebied_callout_can_be_hidden(self, client, db):
        _login(client, _user(db))
        d = _defn(badges=[])
        d["elements"]["badge_block"]["show_activiteitengebied"] = False
        r = self._get(client, d)
        assert "poster-badge-callout" not in r.text

    def test_proof_view_is_faithful_not_clickable_no_print(self, client, db):
        """proof=1 renders like print (no placeholders, not clickable) but does
        not open the print dialog; it scales to fit the window instead."""
        _login(client, _user(db))
        p = {"def": json.dumps(_defn(badges=["vredeslicht"])), "proof": "1"}
        r = client.get("/posters/render", params=p)
        assert r.status_code == 200
        assert "poster-preview" not in r.text          # not the clickable editor view
        assert 'data-placeholder="Subtitel"' not in r.text  # empty blocks dropped
        assert "window.print" not in r.text            # no auto-print
        assert "page.style.transform" in r.text        # scaled to fit the window

    def test_print_view_auto_prints(self, client, db):
        _login(client, _user(db))
        p = {"def": json.dumps(_defn(badges=["vredeslicht"]))}   # neither preview nor proof
        r = client.get("/posters/render", params=p)
        assert "window.print" in r.text

    def test_activiteitengebied_font_size_default(self, client, db):
        _login(client, _user(db))
        r = self._get(client, _defn(badges=[]))
        assert "--callout-pt:14pt" in r.text          # default

    def test_activiteitengebied_font_size_adjustable(self, client, db):
        _login(client, _user(db))
        d = _defn(badges=[])
        d["elements"]["badge_block"]["activiteitengebied_font_size_pt"] = 22
        r = self._get(client, d)
        assert "--callout-pt:22pt" in r.text

    def test_activiteitengebied_font_size_clamped(self, client, db):
        """Out-of-range / bad values fall back to the default (6–72)."""
        _login(client, _user(db))
        d = _defn(badges=[])
        d["elements"]["badge_block"]["activiteitengebied_font_size_pt"] = 999
        r = self._get(client, d)
        assert "--callout-pt:72pt" in r.text

    def test_section_headers_shown_by_default(self, client, db):
        _login(client, _user(db))
        r = self._get(client, _defn(badges=[]))   # empty = all gewoon + buitengewoon
        assert "poster-section-header" in r.text
        assert "Gewone insignes" in r.text and "Buitengewone insignes" in r.text

    def test_section_headers_can_be_hidden(self, client, db):
        _login(client, _user(db))
        d = _defn(badges=[])
        d["elements"]["badge_block"]["show_section_headers"] = False
        r = self._get(client, d)
        assert "poster-section-header" not in r.text

    def test_levels_grouped_per_badge(self, client, db):
        """Each badge is one cell with its niveaus as a row of levels."""
        _login(client, _user(db))
        d = _defn(badges=["vredeslicht", "lucht"])
        d["elements"]["badge_block"]["niveaus"] = [1, 2, 3]
        r = self._get(client, d)
        assert r.text.count('class="poster-badge-main"') == 2     # one cell per badge
        assert r.text.count('class="poster-badge-levels"') == 2   # a levels row each

    def test_datum_and_url_templating(self, client, db):
        from insigne.config import config
        _login(client, _user(db))
        r = self._get(client, _defn(badges=["vredeslicht"], footer="{{ datum }} via {{ url }}"))
        assert config.base_url in r.text
        assert str(datetime.now().year) in r.text

    def test_background_gradient_rendered(self, client, db):
        _login(client, _user(db))
        d = _defn(badges=["vredeslicht"])
        d["elements"]["background"] = {"style": "horizontal_gradient",
                                       "start_color": "red", "end_color": "green"}
        r = self._get(client, d)
        assert "linear-gradient(to right,red,green)" in r.text

    def test_background_color_is_sanitized(self, client, db):
        """A colour that isn't a #hex or plain name is dropped (CSS-injection guard)."""
        _login(client, _user(db))
        d = _defn(badges=["vredeslicht"])
        d["elements"]["background"] = {"style": "solid",
                                       "start_color": "red;}body{display:none", "end_color": "green"}
        r = self._get(client, d)
        assert "display:none" not in r.text

    def test_text_font_family_and_color(self, client, db):
        _login(client, _user(db))
        d = _defn(title="Hoi", badges=["vredeslicht"])
        d["elements"]["title"]["font_family"] = "Georgia, serif"
        d["elements"]["title"]["color"] = "#ff0000"
        r = self._get(client, d)
        assert "font-family:Georgia, serif" in r.text
        assert "color:#ff0000" in r.text

    def test_font_family_sanitized(self, client, db):
        _login(client, _user(db))
        d = _defn(title="Hoi", badges=["vredeslicht"])
        d["elements"]["title"]["font_family"] = "x;}body{display:none"
        r = self._get(client, d)
        assert "display:none" not in r.text

    def test_preview_elements_are_clickable(self, client, db):
        _login(client, _user(db))
        r = self._get(client, _defn(badges=["vredeslicht"]), preview="1")
        assert 'data-el="title"' in r.text and 'data-el="badge_block"' in r.text
        assert "postMessage" in r.text and "poster-preview" in r.text

    def test_print_has_no_click_script(self, client, db):
        _login(client, _user(db))
        r = self._get(client, _defn(badges=["vredeslicht"]))   # no preview flag
        assert "postMessage" not in r.text

    def test_selection_highlight_applied(self, client, db):
        _login(client, _user(db))
        r = self._get(client, _defn(badges=["vredeslicht"]), preview="1", sel="title")
        assert "poster-selected" in r.text

    def test_bad_sel_ignored(self, client, db):
        _login(client, _user(db))
        r = self._get(client, _defn(badges=["vredeslicht"]), preview="1", sel="../../etc")
        assert r.status_code == 200  # sanitised to '' server-side, no error


# ── CRUD ────────────────────────────────────────────────────────────────────

class TestPosterCrud:
    def test_create_stores_yaml_and_mirrors_meta(self, client, db):
        _login(client, _user(db))
        defn = _defn(name="Mijn poster", title="Hoi", badges=["vredeslicht"])
        r = client.post("/posters", data={"definition": json.dumps(defn), "scope": "user"},
                        follow_redirects=False)
        assert r.status_code == 303 and r.headers["location"].startswith("/posters/")
        row = db.query(PosterTemplate).filter_by(name="Mijn poster").first()
        assert row is not None and row.poster_type == 0
        stored = yaml.safe_load(row.definition)
        assert stored["title"] == "Hoi"
        assert stored["elements"]["badge_block"]["badges"] == ["vredeslicht"]

    def test_update(self, client, db):
        u = _user(db)
        _login(client, u)
        p = _create(db, u, name="A")
        defn = _defn(name="B", paper="A3", orientation="landscape")
        r = client.post(f"/posters/{p.id}", data={"definition": json.dumps(defn)},
                        follow_redirects=False)
        assert r.status_code == 303
        db.refresh(p)
        assert p.name == "B"
        assert yaml.safe_load(p.definition)["paper"] == "A3"

    def test_delete(self, client, db):
        u = _user(db)
        _login(client, u)
        p = _create(db, u, name="A")
        r = client.post(f"/posters/{p.id}/delete", follow_redirects=False)
        assert r.status_code == 303 and r.headers["location"] == "/posters"
        assert db.get(PosterTemplate, p.id) is None

    def test_bad_uuid_redirects(self, client, db):
        _login(client, _user(db))
        r = client.get("/posters/not-a-uuid", follow_redirects=False)
        assert r.status_code == 303 and r.headers["location"] == "/posters"

    def test_malformed_definition_falls_back(self, client, db):
        _login(client, _user(db))
        r = client.post("/posters", data={"definition": "{not json", "scope": "user"},
                        follow_redirects=False)
        assert r.status_code == 303  # creates a fresh fallback poster, no crash


# ── Scope + IDOR ────────────────────────────────────────────────────────────

class TestPosterScope:
    def test_leader_creates_speltak_scoped(self, client, db):
        leider, g, s = _speltakleider(db, email="leider@example.com")
        _login(client, leider)
        r = client.post("/posters", data={
            "definition": json.dumps(_defn(name="Stam-poster", type=1)),
            "scope": "speltak", "scope_id": s.id,
        }, follow_redirects=False)
        assert r.status_code == 303
        row = db.query(PosterTemplate).filter_by(name="Stam-poster").first()
        assert row is not None and row.speltak_id == s.id and row.scope == "speltak"

    def test_non_leader_cannot_create_speltak_scoped(self, client, db):
        leider, g, s = _speltakleider(db, email="leider2@example.com")
        scout = _user(db, email="scout@example.com")
        db.add(SpeltakMembership(user_id=scout.id, speltak_id=s.id, role="scout", approved=True))
        db.commit()
        _login(client, scout)
        r = client.post("/posters", data={
            "definition": json.dumps(_defn(name="Hack")), "scope": "speltak", "scope_id": s.id,
        }, follow_redirects=False)
        assert r.status_code == 303 and r.headers["location"] == "/posters"
        assert db.query(PosterTemplate).filter_by(name="Hack").first() is None

    def test_personal_is_idor_protected(self, client, db):
        owner = _user(db, email="owner@example.com")
        p = _create(db, owner, name="Privé")
        other = _user(db, email="other@example.com")
        _login(client, other)
        r = client.get(f"/posters/{p.id}", follow_redirects=False)
        assert r.status_code == 303 and r.headers["location"] == "/posters"

    def test_member_duplicates_shared(self, client, db):
        leider, g, s = _speltakleider(db, email="leider3@example.com")
        shared = posters_svc.create(db, created_by_id=leider.id,
                                    definition=_defn(name="Gedeeld", type=1),
                                    scope="speltak", scope_id=s.id)
        scout = _user(db, email="scout3@example.com")
        db.add(SpeltakMembership(user_id=scout.id, speltak_id=s.id, role="scout", approved=True))
        db.commit()
        _login(client, scout)
        assert "Gedeeld" in client.get("/posters").text
        assert client.get(f"/posters/{shared.id}").status_code == 200
        r = client.post(f"/posters/{shared.id}",
                        data={"definition": json.dumps(_defn(name="Mijn kopie"))},
                        follow_redirects=False)
        assert r.status_code == 303
        copy = db.query(PosterTemplate).filter_by(name="Mijn kopie").first()
        assert copy is not None and copy.scope == "user" and copy.user_id == scout.id


# ── Export / import ────────────────────────────────────────────────────────────

class TestExportImport:
    def test_export_returns_yaml(self, client, db):
        u = _user(db)
        _login(client, u)
        p = _create(db, u, name="Exporteerbaar", title="Hoi")
        r = client.get(f"/posters/{p.id}/export")
        assert r.status_code == 200
        assert "yaml" in r.headers.get("content-type", "")
        loaded = yaml.safe_load(r.text)
        assert loaded["name"] == "Exporteerbaar" and loaded["title"] == "Hoi"

    def test_export_idor_protected(self, client, db):
        owner = _user(db, email="o2@example.com")
        p = _create(db, owner, name="X")
        _login(client, _user(db, email="x2@example.com"))
        r = client.get(f"/posters/{p.id}/export", follow_redirects=False)
        assert r.status_code == 303 and r.headers["location"] == "/posters"

    def test_import_creates_personal_poster(self, client, db):
        u = _user(db)
        _login(client, u)
        yaml_text = pt.to_yaml(_defn(name="Geïmporteerd", title="Ingeladen"))
        r = client.post("/posters/import",
                        files={"file": ("poster.yml", yaml_text, "application/x-yaml")},
                        follow_redirects=False)
        assert r.status_code == 303 and r.headers["location"].startswith("/posters/")
        row = db.query(PosterTemplate).filter_by(name="Geïmporteerd").first()
        assert row is not None and row.scope == "user" and row.user_id == u.id

    def test_import_malformed_redirects(self, client, db):
        _login(client, _user(db))
        r = client.post("/posters/import",
                        files={"file": ("bad.yml", "- just\n- a\n- list", "application/x-yaml")},
                        follow_redirects=False)
        assert r.status_code == 303 and r.headers["location"] == "/posters"

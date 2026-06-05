"""Poster designer routes (#132, Phase 1) — list, designer, render, CRUD,
scope/visibility and IDOR guards."""
from insigne import groups as groups_svc
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


def _speltakleider(db, *, email):
    """A user who is speltakleider of a fresh group/speltak. Returns (user, group, speltak)."""
    leider = _user(db, email=email)
    g = groups_svc.create_group(db, name="Groep", slug=f"g-{email[:4]}", created_by_id=leider.id)
    s = groups_svc.create_speltak(db, group_id=g.id, name="Stam", slug=f"s-{email[:4]}")
    db.add(SpeltakMembership(user_id=leider.id, speltak_id=s.id,
                             role="speltakleider", approved=True))
    db.commit()
    return leider, g, s


# ── List ──────────────────────────────────────────────────────────────────────

class TestPostersList:
    def test_anonymous_redirects_to_login(self, client, db):
        r = client.get("/posters", follow_redirects=False)
        assert r.status_code == 303
        assert r.headers["location"] == "/login"

    def test_authenticated_shows_wizard_chooser(self, client, db):
        _login(client, _user(db))
        r = client.get("/posters")
        assert r.status_code == 200
        assert "Wat wil je doen?" in r.text
        # The three "new" options + the "open existing" step.
        assert "/posters/new?type=badges" in r.text
        assert "/posters/new?type=speltak" in r.text
        assert "/posters/new?type=signoff" in r.text
        assert "poster-wizard-card" in r.text

    def test_existing_posters_listed_in_open_step(self, client, db):
        from insigne import posters as posters_svc
        from insigne import poster_templates as pt
        u = _user(db)
        _login(client, u)
        posters_svc.create(db, created_by_id=u.id, name="Bestaande", poster_type="badges",
                           paper_size="A4", orientation="portrait",
                           params=pt.parse_params({}), scope="user", scope_id=None)
        r = client.get("/posters")
        assert "Bestaande" in r.text and "/posters/" in r.text


# ── New / designer ──────────────────────────────────────────────────────────

class TestPosterNew:
    def test_new_seeds_base_template(self, client, db):
        _login(client, _user(db))
        r = client.get("/posters/new?type=badges")
        assert r.status_code == 200
        # Base template title for the badge poster is seeded into the Alpine model.
        assert "Insignes" in r.text
        assert "poster_designer.js" in r.text

    def test_new_unknown_type_falls_back(self, client, db):
        _login(client, _user(db))
        r = client.get("/posters/new?type=bogus")
        assert r.status_code == 200

    def test_designer_has_small_screen_guard(self, client, db):
        _login(client, _user(db))
        r = client.get("/posters/new?type=badges")
        assert "poster-toosmall" in r.text and "Te klein scherm" in r.text

    def test_designer_is_stepped_wizard(self, client, db):
        _login(client, _user(db))
        r = client.get("/posters/new?type=badges")
        assert "poster-steps" in r.text
        assert "1. Inhoud" in r.text and "2. Opmaak" in r.text and "3. Opslaan" in r.text

    def test_designer_config_is_xss_safe(self, client, db):
        """The designer config goes in a JSON <script> block (|tojson escapes
        < > &), not an x-data attribute — so a malicious saved title can't break
        out into live markup (regression for the PR #158 review finding)."""
        from insigne import posters as posters_svc
        from insigne import poster_templates as pt
        u = _user(db)
        _login(client, u)
        payload = '"></script><img src=x onerror=alert(1)>'
        p = posters_svc.create(
            db, created_by_id=u.id, name=payload, poster_type="badges",
            paper_size="A4", orientation="portrait",
            params=pt.parse_params({"title": payload}), scope="user", scope_id=None,
        )
        r = client.get(f"/posters/{p.id}")
        assert r.status_code == 200
        assert 'x-data="posterDesigner()"' in r.text
        # The payload must not appear as live markup anywhere.
        assert "<img src=x onerror" not in r.text
        assert "</script><img" not in r.text


# ── Render (standalone) ───────────────────────────────────────────────────────

class TestPosterRender:
    def test_render_emits_correct_page_size_a4(self, client, db):
        _login(client, _user(db))
        r = client.get("/posters/render?type=badges&paper_size=A4&orientation=portrait")
        assert r.status_code == 200
        assert "size: 210mm 297mm" in r.text
        assert "/static/vendor/paged.polyfill.js" in r.text

    def test_render_a2_landscape_swaps_dimensions(self, client, db):
        _login(client, _user(db))
        r = client.get("/posters/render?type=badges&paper_size=A2&orientation=landscape")
        assert "size: 594mm 420mm" in r.text

    def test_render_preview_flag_autoprints_only_when_not_preview(self, client, db):
        _login(client, _user(db))
        printv = client.get("/posters/render?type=badges&paper_size=A4&orientation=portrait")
        assert "window.print()" in printv.text
        prev = client.get("/posters/render?type=badges&paper_size=A4&orientation=portrait&preview=1")
        assert "window.print()" not in prev.text

    def test_render_escapes_title(self, client, db):
        _login(client, _user(db))
        r = client.get("/posters/render", params={
            "type": "badges", "paper_size": "A4", "orientation": "portrait",
            "title": "<script>alert(1)</script>",
        })
        assert "<script>alert(1)</script>" not in r.text
        assert "&lt;script&gt;" in r.text


# ── Create / update / delete ──────────────────────────────────────────────────

class TestPosterCrud:
    def test_create_personal_and_redirect(self, client, db):
        _login(client, _user(db))
        r = client.post("/posters", data={
            "poster_type": "badges", "scope": "user", "paper_size": "A4",
            "orientation": "portrait", "name": "Mijn poster", "title": "Hoi",
        }, follow_redirects=False)
        assert r.status_code == 303
        assert r.headers["location"].startswith("/posters/")
        row = db.query(PosterTemplate).filter_by(name="Mijn poster").first()
        assert row is not None and row.scope == "user"
        assert row.params["title"] == "Hoi"

    def test_update_changes_fields(self, client, db):
        u = _user(db)
        _login(client, u)
        from insigne import posters as posters_svc
        from insigne import poster_templates as pt
        p = posters_svc.create(db, created_by_id=u.id, name="A", poster_type="badges",
                               paper_size="A4", orientation="portrait",
                               params=pt.parse_params({}), scope="user", scope_id=None)
        r = client.post(f"/posters/{p.id}", data={
            "poster_type": "badges", "paper_size": "A3", "orientation": "landscape",
            "name": "B", "title": "Nieuw",
        }, follow_redirects=False)
        assert r.status_code == 303
        db.refresh(p)
        assert p.name == "B" and p.paper_size == "A3" and p.orientation == "landscape"

    def test_delete_removes_row(self, client, db):
        u = _user(db)
        _login(client, u)
        from insigne import posters as posters_svc
        from insigne import poster_templates as pt
        p = posters_svc.create(db, created_by_id=u.id, name="A", poster_type="badges",
                               paper_size="A4", orientation="portrait",
                               params=pt.parse_params({}), scope="user", scope_id=None)
        r = client.post(f"/posters/{p.id}/delete", follow_redirects=False)
        assert r.status_code == 303 and r.headers["location"] == "/posters"
        assert db.get(PosterTemplate, p.id) is None

    def test_bad_uuid_redirects(self, client, db):
        _login(client, _user(db))
        r = client.get("/posters/not-a-uuid", follow_redirects=False)
        assert r.status_code == 303 and r.headers["location"] == "/posters"


# ── Scope + IDOR ────────────────────────────────────────────────────────────

class TestBadgePoster:
    """Type 1 — Insigneposter algemeen (badge grid)."""

    def test_render_shows_selected_badge_images(self, client, db):
        _login(client, _user(db))
        r = client.get("/posters/render", params={
            "type": "badges", "paper_size": "A3", "orientation": "portrait",
            "badge_slugs": "vredeslicht", "niveau": "1", "columns": "4",
            "image_mm": "35", "show_titles": "1",
        })
        assert r.status_code == 200
        assert 'src="/images/vredeslicht.1.png"' in r.text
        assert "poster-badge-grid" in r.text

    def test_render_niveau_selects_image(self, client, db):
        _login(client, _user(db))
        r = client.get("/posters/render", params={
            "type": "badges", "paper_size": "A3", "orientation": "portrait",
            "badge_slugs": "vredeslicht", "niveau": "2",
        })
        assert 'src="/images/vredeslicht.2.png"' in r.text

    def test_render_ignores_unknown_slug(self, client, db):
        _login(client, _user(db))
        r = client.get("/posters/render", params={
            "type": "badges", "paper_size": "A3", "orientation": "portrait",
            "badge_slugs": "vredeslicht,not-a-real-badge",
        })
        assert "/images/vredeslicht" in r.text
        assert "not-a-real-badge" not in r.text

    def test_create_persists_cleaned_type_params(self, client, db):
        u = _user(db)
        _login(client, u)
        r = client.post("/posters", data={
            "poster_type": "badges", "scope": "user", "paper_size": "A3",
            "orientation": "portrait", "name": "Grid",
            "badge_slugs": "vredeslicht,bogus", "columns": "5", "image_mm": "40",
            "niveau": "2", "show_titles": "0",
        }, follow_redirects=False)
        assert r.status_code == 303
        row = db.query(PosterTemplate).filter_by(name="Grid").first()
        assert row.params["badge_slugs"] == ["vredeslicht"]   # bogus dropped
        assert row.params["columns"] == 5 and row.params["niveau"] == 2
        assert row.params["show_titles"] is False

    def test_designer_has_badge_picker(self, client, db):
        _login(client, _user(db))
        r = client.get("/posters/new?type=badges")
        assert "poster-badge-list" in r.text
        assert 'value="vredeslicht"' in r.text          # a real badge checkbox
        assert "filterSets" in r.text                    # quick-select sets in config

    def test_designer_config_includes_favorites_set(self, client, db):
        from insigne import users as users_svc
        u = _user(db)
        _login(client, u)
        users_svc.toggle_user_favorite_badge(db, u.id, "vredeslicht")
        r = client.get("/posters/new?type=badges")
        assert "favorites" in r.text and "vredeslicht" in r.text


class TestPosterScope:
    def test_leader_can_create_speltak_scoped(self, client, db):
        leider, g, s = _speltakleider(db, email="leider@example.com")
        _login(client, leider)
        r = client.post("/posters", data={
            "poster_type": "speltak", "scope": "speltak", "scope_id": s.id,
            "paper_size": "A3", "orientation": "landscape", "name": "Stam-poster",
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
            "poster_type": "speltak", "scope": "speltak", "scope_id": s.id, "name": "Hack",
        }, follow_redirects=False)
        assert r.status_code == 303 and r.headers["location"] == "/posters"
        assert db.query(PosterTemplate).filter_by(name="Hack").first() is None

    def test_personal_poster_is_idor_protected(self, client, db):
        owner = _user(db, email="owner@example.com")
        from insigne import posters as posters_svc
        from insigne import poster_templates as pt
        p = posters_svc.create(db, created_by_id=owner.id, name="Privé", poster_type="badges",
                               paper_size="A4", orientation="portrait",
                               params=pt.parse_params({}), scope="user", scope_id=None)
        other = _user(db, email="other@example.com")
        _login(client, other)
        r = client.get(f"/posters/{p.id}", follow_redirects=False)
        assert r.status_code == 303 and r.headers["location"] == "/posters"

    def test_member_sees_and_duplicates_shared_speltak_poster(self, client, db):
        leider, g, s = _speltakleider(db, email="leider3@example.com")
        from insigne import posters as posters_svc
        from insigne import poster_templates as pt
        shared = posters_svc.create(db, created_by_id=leider.id, name="Gedeeld",
                                    poster_type="speltak", paper_size="A3",
                                    orientation="landscape", params=pt.parse_params({}),
                                    scope="speltak", scope_id=s.id)
        scout = _user(db, email="scout3@example.com")
        db.add(SpeltakMembership(user_id=scout.id, speltak_id=s.id, role="scout", approved=True))
        db.commit()
        _login(client, scout)
        # Visible + viewable, but not editable.
        assert client.get("/posters").text.count("Gedeeld") >= 1
        view = client.get(f"/posters/{shared.id}")
        assert view.status_code == 200
        # Saving as a non-editor creates a personal copy (new row), original untouched.
        r = client.post(f"/posters/{shared.id}", data={
            "poster_type": "speltak", "paper_size": "A3", "orientation": "landscape",
            "name": "Mijn kopie",
        }, follow_redirects=False)
        assert r.status_code == 303
        copy = db.query(PosterTemplate).filter_by(name="Mijn kopie").first()
        assert copy is not None and copy.scope == "user" and copy.user_id == scout.id

"""HTML integration tests for the batch-signoff-per-niveau UX (#102).

Per the design decision on #102, no new server-side endpoints exist. The
scout-side panel and the mentor-inbox grouped card both *loop client-side*
over the existing per-eis ``/progress/{id}/request-signoff-*`` and
``/progress/{id}/{confirm,reject}-signoff`` endpoints. These tests
therefore only verify the rendered HTML — that the panel shows up when a
niveau is ready, that the mentor inbox renders the grouped card, and that
the per-entry endpoint URLs and entry IDs the JS loops over are present in
the page source."""
import re

import insigne.auth as auth_svc
from insigne.badges import BadgeCatalogue
from insigne import groups as groups_svc
from insigne import progress as progress_svc
from insigne.models import (
    GroupMembership,
    ProgressEntry,
    SpeltakMembership,
    User,
)


def _user(db, email, name="X"):
    u = User(email=email, name=name, status="active", password_hash="x")
    db.add(u); db.commit()
    return u


def _entry(db, user_id, badge_slug, level_index, step_index, status="work_done"):
    e = ProgressEntry(
        user_id=user_id, badge_slug=badge_slug,
        level_index=level_index, step_index=step_index, status=status,
    )
    db.add(e); db.commit()
    return e


def _speltak_with_leider(db, leider, scout):
    g = groups_svc.create_group(db, name="G", slug="g", created_by_id=leider.id)
    s = groups_svc.create_speltak(db, group_id=g.id, name="Welpen", slug="welpen",
                                  speltak_type="welpen")
    db.add(GroupMembership(user_id=leider.id, group_id=g.id,
                           role="groepsleider", approved=True))
    db.add(SpeltakMembership(user_id=leider.id, speltak_id=s.id,
                             role="speltakleider", approved=True))
    db.add(GroupMembership(user_id=scout.id, group_id=g.id,
                           role="member", approved=True))
    db.add(SpeltakMembership(user_id=scout.id, speltak_id=s.id,
                             role="scout", approved=True))
    db.commit()
    return g, s


def _login(client, user):
    token, _ = auth_svc.create_access_token(user.id)
    return {"access_token": token}


def _mark_all_eisen_work_done(db, user_id, badge_slug, niveau_idx):
    """Set every non-empty eis at this niveau to work_done."""
    from pathlib import Path
    cat = BadgeCatalogue(Path(__file__).parent.parent.parent / "api" / "data")
    badge = cat.get(badge_slug)
    entries = []
    for ei, level in enumerate(badge["levels"]):
        if level["steps"][niveau_idx]["text"].strip():
            entries.append(_entry(db, user_id, badge_slug, ei, niveau_idx, "work_done"))
    return entries


class TestBatchPanelOnBadgePage:
    def test_panel_appears_when_niveau_ready(self, client, db):
        scout = _user(db, "s@x.com")
        _mark_all_eisen_work_done(db, scout.id, "kamperen", 0)
        client.cookies.update(_login(client, scout))
        r = client.get("/badges/kamperen?niveau=1")
        assert r.status_code == 200
        # The panel headline mentions niveau 1.
        assert "Niveau 1" in r.text
        # The JS loops over the per-entry endpoint — its path-fragment string
        # must be present in the page source for at least one of the three
        # buttons (speltak / members / direct).
        assert "/request-signoff-speltak" in r.text or \
               "/request-signoff-members" in r.text or \
               "/request-signoff" in r.text

    def test_panel_absent_when_no_eisen_done(self, client, db):
        scout = _user(db, "s@x.com")
        client.cookies.update(_login(client, scout))
        r = client.get("/badges/kamperen?niveau=1")
        assert r.status_code == 200
        # No "Vraag aftekening voor het hele niveau" headline.
        assert "voor het hele niveau" not in r.text

    def test_panel_renders_pending_state_with_cancel_button(self, client, db):
        scout = _user(db, "s@x.com")
        leider = _user(db, "l@x.com", "Leider")
        _, speltak = _speltak_with_leider(db, leider, scout)
        entries = _mark_all_eisen_work_done(db, scout.id, "kamperen", 0)
        # Put two of them into pending via per-eis service calls.
        for e in entries[:2]:
            progress_svc.request_signoff_for_speltak(db, scout.id, e.id, speltak.id)

        client.cookies.update(_login(client, scout))
        r = client.get("/badges/kamperen?niveau=1")
        assert r.status_code == 200
        assert "Verzoek intrekken" in r.text
        assert "/cancel-signoff" in r.text

    def test_panel_entry_ids_match_work_done_eisen(self, client, db):
        """The Alpine entryIds array must list exactly the work_done entry
        IDs for that niveau — the JS loop will hit each one."""
        scout = _user(db, "s@x.com")
        entries = _mark_all_eisen_work_done(db, scout.id, "kamperen", 0)
        client.cookies.update(_login(client, scout))
        r = client.get("/badges/kamperen?niveau=1")
        for e in entries:
            assert e.id in r.text

    def test_x_data_attribute_is_well_formed(self, client, db):
        """The ``entryIds`` JSON inside x-data must not break the attribute.
        The original implementation used ``x-data="{...entryIds: {{ ... | tojson }}...}"``
        — but tojson outputs ``["uuid","uuid"]`` and the inner ``"`` terminates
        the surrounding double-quoted attribute, dumping the rest of the JS
        as text content. The fix uses single-quoted ``x-data='funcName(...)'``
        and a page-scope ``<script>`` defining the component."""
        scout = _user(db, "s@x.com")
        _mark_all_eisen_work_done(db, scout.id, "kamperen", 0)
        client.cookies.update(_login(client, scout))
        r = client.get("/badges/kamperen?niveau=1")
        assert r.status_code == 200
        # The Alpine attribute must call the helper, not embed a JS object.
        assert "x-data='batchSignoffPanelData(" in r.text
        # Sanity: the body of postEachEntry must NOT appear as DOM text.
        # Strip every <script>...</script> block first, then look for a
        # distinctive token from the function body. If we still see it,
        # the x-data attribute is terminating on an inner double quote
        # and the JS body is leaking into the DOM as text.
        without_scripts = re.sub(
            r"<script\b[^>]*>.*?</script>", "", r.text, flags=re.DOTALL,
        )
        leaked_token = "if (Array.isArray(v)) v.forEach"
        assert leaked_token not in without_scripts, (
            "JS function body leaks into DOM text — x-data attribute "
            "is being terminated by an inner double quote."
        )

    def test_panel_wrapper_subscribes_to_niveau_updated(self, client, db):
        """The panel wrapper must auto-refresh on the HX-Trigger event that
        the per-eis log endpoint fires, so the panel appears in real time
        when the scout marks the last eis work_done (no manual reload)."""
        scout = _user(db, "s@x.com")
        _mark_all_eisen_work_done(db, scout.id, "kamperen", 0)
        client.cookies.update(_login(client, scout))
        r = client.get("/badges/kamperen?niveau=1")
        assert r.status_code == 200
        assert 'id="batch-signoff-section"' in r.text
        assert 'hx-trigger="niveau-updated from:body"' in r.text
        assert 'hx-select="#batch-signoff-section"' in r.text


class TestSignoffRequestsPageGroup:
    def test_inbox_renders_badge_niveau_group_card(self, client, db):
        scout = _user(db, "scout@x.com", "Scout")
        leider = _user(db, "leider@x.com", "Leider")
        _, speltak = _speltak_with_leider(db, leider, scout)
        e1 = _entry(db, scout.id, "kamperen", 0, 0, "work_done")
        e2 = _entry(db, scout.id, "kamperen", 1, 0, "work_done")
        progress_svc.request_signoff_for_speltak(db, scout.id, e1.id, speltak.id)
        progress_svc.request_signoff_for_speltak(db, scout.id, e2.id, speltak.id)

        client.cookies.update(_login(client, leider))
        r = client.get("/signoff-requests")
        assert r.status_code == 200
        # Group card has a stable id.
        assert re.search(
            rf'id="request-badge-niveau-{scout.id}-kamperen-0"',
            r.text,
        )
        # The card's Alpine entryIds must list both entry UUIDs so the
        # confirm/reject loop hits each.
        assert e1.id in r.text
        assert e2.id in r.text

    def test_scout_notes_survive_batch_signoff_and_render_on_card(self, client, db):
        """The batch-signoff JS loop POSTs the per-eis request-signoff-speltak
        endpoint without a ``notes`` field. The endpoint used to overwrite
        ``entry.notes`` to NULL unconditionally, wiping the scout's pre-typed
        remarks. Notes the scout typed on the per-eis card MUST survive the
        batch flow and show up on the mentor's grouped inbox card."""
        scout = _user(db, "scout@x.com", "Scout")
        leider = _user(db, "leider@x.com", "Leider")
        _, speltak = _speltak_with_leider(db, leider, scout)

        # Scout has typed notes on each eis (e.g. via the per-eis card),
        # status is work_done, ready for batch sign-off.
        e1 = _entry(db, scout.id, "kamperen", 0, 0, "work_done")
        e2 = _entry(db, scout.id, "kamperen", 1, 0, "work_done")
        e1.notes = "Heb dit met de groep gedaan op kamp"
        e2.notes = "Hier had ik moeite mee"
        db.commit()

        # Mimic the batch panel: fire the per-eis request-signoff-speltak
        # endpoint for each entry WITHOUT a ``notes`` field.
        client.cookies.update(_login(client, scout))
        for entry_id in (e1.id, e2.id):
            r = client.post(
                f"/progress/{entry_id}/request-signoff-speltak",
                data={"speltak_id": speltak.id},
                headers={"HX-Request": "true"},
            )
            assert r.status_code in (200, 303)

        # Notes must still be on the entries.
        db.expire_all()
        from insigne.models import ProgressEntry
        assert db.get(ProgressEntry, e1.id).notes == "Heb dit met de groep gedaan op kamp"
        assert db.get(ProgressEntry, e2.id).notes == "Hier had ik moeite mee"

        # And the mentor inbox card surfaces them.
        client.cookies.update(_login(client, leider))
        r = client.get("/signoff-requests")
        assert r.status_code == 200
        assert "Heb dit met de groep gedaan op kamp" in r.text
        assert "Hier had ik moeite mee" in r.text

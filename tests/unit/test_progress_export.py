"""Tests for progress export/import service and API endpoints."""

from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

import yaml
import pytest

from insigne.badges import BadgeCatalogue
from insigne.models import Jaarinsigne2026Inclusion, ProgressEntry, User

_DATA_DIR = Path(__file__).parent.parent.parent / "api" / "data"
_CATALOGUE = BadgeCatalogue(_DATA_DIR)

from insigne.progress_export import (
    embed_yaml_in_pdf,
    export_data,
    extract_yaml_from_pdf,
    find_or_create_nameholder,
    import_progress,
    to_pdf,
    to_yaml,
)


# ── helpers ───────────────────────────────────────────────────────────────────

def _make_user(db, email="scout@example.com", name="Scout") -> User:
    user = User(email=email, name=name, status="active")
    db.add(user)
    db.commit()
    return user


def _make_entry(db, user_id, *, badge_slug="sport_spel", level_index=0, step_index=0,
                status="in_progress", signed_off_by_id=None, signed_off_at=None, notes=None):
    entry = ProgressEntry(
        user_id=user_id, badge_slug=badge_slug,
        level_index=level_index, step_index=step_index,
        status=status, signed_off_by_id=signed_off_by_id,
        signed_off_at=signed_off_at, notes=notes,
    )
    db.add(entry)
    db.commit()
    return entry


# ── find_or_create_nameholder ─────────────────────────────────────────────────

class TestFindOrCreateNameholder:
    def test_creates_emailless_user(self, db):
        holder = find_or_create_nameholder(db, "Leider Jan")
        db.commit()
        assert holder.email is None
        assert holder.name == "Leider Jan"
        assert holder.status == "active"

    def test_reuses_existing_emailless_user(self, db):
        h1 = find_or_create_nameholder(db, "Leider Jan")
        db.commit()
        h2 = find_or_create_nameholder(db, "Leider Jan")
        assert h1.id == h2.id

    def test_does_not_match_users_with_email(self, db):
        real = User(email="jan@example.com", name="Leider Jan", status="active")
        db.add(real)
        db.commit()
        holder = find_or_create_nameholder(db, "Leider Jan")
        db.commit()
        assert holder.id != real.id
        assert holder.email is None

    def test_holder_has_no_group_memberships(self, db):
        holder = find_or_create_nameholder(db, "Leider Jan")
        db.commit()
        assert holder.group_memberships == []
        assert holder.speltak_memberships == []


# ── export_data ───────────────────────────────────────────────────────────────

class TestExportData:
    def test_includes_non_pending_entries(self, db):
        user = _make_user(db)
        _make_entry(db, user.id, status="in_progress")
        _make_entry(db, user.id, step_index=1, status="work_done")
        _make_entry(db, user.id, step_index=2, status="signed_off",
                    signed_off_at=datetime(2026, 3, 1, tzinfo=timezone.utc))
        data = export_data(db, user.id)
        assert len(data["progress"]) == 3

    def test_excludes_pending_signoff(self, db):
        user = _make_user(db)
        _make_entry(db, user.id, status="pending_signoff")
        data = export_data(db, user.id)
        assert len(data["progress"]) == 0

    def test_signed_off_by_name_not_email(self, db):
        mentor = User(email="mentor@example.com", name="Leider Piet", status="active")
        db.add(mentor)
        db.commit()
        user = _make_user(db)
        _make_entry(db, user.id, status="signed_off", signed_off_by_id=mentor.id,
                    signed_off_at=datetime(2026, 3, 1, tzinfo=timezone.utc))
        data = export_data(db, user.id)
        entry = data["progress"][0]
        assert entry["signed_off_by"] == "Leider Piet"
        assert "mentor@example.com" not in str(entry)

    def test_version_and_structure(self, db):
        user = _make_user(db)
        data = export_data(db, user.id)
        assert data["version"] == 3
        assert "exported_at" in data
        assert data["user"]["name"] == "Scout"

    def test_notes_included(self, db):
        user = _make_user(db)
        _make_entry(db, user.id, notes="Mijn aantekening")
        data = export_data(db, user.id)
        assert data["progress"][0]["notes"] == "Mijn aantekening"


# ── to_yaml / to_pdf ──────────────────────────────────────────────────────────

class TestToYaml:
    def test_roundtrip(self, db):
        user = _make_user(db)
        _make_entry(db, user.id, status="work_done")
        data = export_data(db, user.id)
        parsed = yaml.safe_load(to_yaml(data))
        assert parsed["version"] == 3
        assert parsed["progress"][0]["status"] == "work_done"


def _pdf_text(pdf_bytes: bytes) -> str:
    import fitz
    doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    return "".join(page.get_text() for page in doc)


class TestToPdf:
    def test_returns_pdf_bytes(self, db):
        user = _make_user(db)
        data = export_data(db, user.id)
        pdf = to_pdf(data)
        assert pdf[:4] == b"%PDF"

    def test_pdf_with_entries(self, db):
        user = _make_user(db)
        _make_entry(db, user.id, status="signed_off",
                    signed_off_at=datetime(2026, 3, 1, tzinfo=timezone.utc))
        data = export_data(db, user.id)
        pdf = to_pdf(data)
        assert len(pdf) > 1000

    def test_pdf_contains_explorers_category_heading(self, db):
        user = _make_user(db)
        data = export_data(db, user.id)
        pdf = to_pdf(data, catalogue=_CATALOGUE)
        text = _pdf_text(pdf)
        assert "Explorers" in text

    def test_pdf_explorer_jaarbadge_uses_jaarbadge_label(self, db):
        user = _make_user(db)
        data = export_data(db, user.id)
        pdf = to_pdf(data, catalogue=_CATALOGUE)
        text = _pdf_text(pdf)
        assert "Jaarbadge 1" in text
        assert "Jaarbadge 2" in text
        assert "Jaarbadge 3" in text

    def test_pdf_regular_badge_uses_niveau_label(self, db):
        user = _make_user(db)
        data = export_data(db, user.id)
        pdf = to_pdf(data, catalogue=_CATALOGUE)
        text = _pdf_text(pdf)
        assert "Niveau 1" in text
        assert "Niveau 2" in text
        assert "Niveau 3" in text


# ── embed / extract ───────────────────────────────────────────────────────────

class TestPdfYamlEmbedding:
    def _simple_pdf(self):
        from reportlab.lib.pagesizes import A4
        from reportlab.pdfgen import canvas
        import io
        buf = io.BytesIO()
        c = canvas.Canvas(buf, pagesize=A4)
        c.drawString(100, 750, "Test")
        c.save()
        return buf.getvalue()

    def test_embed_and_extract_roundtrip(self):
        yaml_str = "version: 1\nuser:\n  name: Test\nprogress: []\n"
        pdf = embed_yaml_in_pdf(self._simple_pdf(), yaml_str)
        extracted = extract_yaml_from_pdf(pdf)
        assert extracted == yaml_str

    def test_extract_returns_none_when_no_attachment(self):
        result = extract_yaml_from_pdf(self._simple_pdf())
        assert result is None

    def test_full_export_pdf_roundtrip(self, db):
        user = _make_user(db)
        _make_entry(db, user.id, status="work_done")
        data = export_data(db, user.id)
        yaml_str = to_yaml(data)
        pdf = embed_yaml_in_pdf(to_pdf(data), yaml_str)
        extracted = yaml.safe_load(extract_yaml_from_pdf(pdf))
        assert extracted["version"] == 3
        assert extracted["progress"][0]["status"] == "work_done"


# ── import_progress ───────────────────────────────────────────────────────────

class TestImportProgress:
    def _data(self, entries, version=2):
        return {"version": version, "user": {"name": "Scout"}, "progress": entries}

    def test_rejects_future_version(self, db):
        user = _make_user(db)
        data = self._data([], version=99)
        with pytest.raises(ValueError, match="99"):
            import_progress(db, user.id, data)

    def test_accepts_version_1_for_backwards_compat(self, db):
        user = _make_user(db)
        data = self._data([{
            "badge_slug": "sport_spel", "level_index": 0, "step_index": 0,
            "status": "in_progress", "notes": None,
            "signed_off_by": None, "signed_off_at": None,
        }], version=1)
        count = import_progress(db, user.id, data)
        assert count == 1

    def test_creates_new_entries(self, db):
        user = _make_user(db)
        data = self._data([{
            "badge_slug": "sport_spel", "level_index": 0, "step_index": 0,
            "status": "in_progress", "notes": None,
            "signed_off_by": None, "signed_off_at": None,
        }])
        count = import_progress(db, user.id, data)
        assert count == 1
        assert db.query(ProgressEntry).filter_by(user_id=user.id).count() == 1

    def test_creates_nameholder_for_signed_off(self, db):
        user = _make_user(db)
        data = self._data([{
            "badge_slug": "sport_spel", "level_index": 0, "step_index": 0,
            "status": "signed_off", "notes": None,
            "signed_off_by": "Leider Piet",
            "signed_off_at": "2026-03-01T10:00:00+00:00",
        }])
        import_progress(db, user.id, data)
        entry = db.query(ProgressEntry).filter_by(user_id=user.id).first()
        assert entry.signed_off_by is not None
        assert entry.signed_off_by.name == "Leider Piet"
        assert entry.signed_off_by.email is None

    def test_does_not_downgrade_status(self, db):
        user = _make_user(db)
        _make_entry(db, user.id, status="signed_off",
                    signed_off_at=datetime(2026, 3, 1, tzinfo=timezone.utc))
        data = self._data([{
            "badge_slug": "sport_spel", "level_index": 0, "step_index": 0,
            "status": "in_progress", "notes": None,
            "signed_off_by": None, "signed_off_at": None,
        }])
        count = import_progress(db, user.id, data)
        assert count == 0
        entry = db.query(ProgressEntry).filter_by(user_id=user.id).first()
        assert entry.status == "signed_off"

    def test_upgrades_status(self, db):
        user = _make_user(db)
        _make_entry(db, user.id, status="in_progress")
        data = self._data([{
            "badge_slug": "sport_spel", "level_index": 0, "step_index": 0,
            "status": "work_done", "notes": None,
            "signed_off_by": None, "signed_off_at": None,
        }])
        count = import_progress(db, user.id, data)
        assert count == 1
        entry = db.query(ProgressEntry).filter_by(user_id=user.id).first()
        assert entry.status == "work_done"

    def test_idempotent_same_status(self, db):
        user = _make_user(db)
        _make_entry(db, user.id, status="work_done")
        data = self._data([{
            "badge_slug": "sport_spel", "level_index": 0, "step_index": 0,
            "status": "work_done", "notes": None,
            "signed_off_by": None, "signed_off_at": None,
        }])
        count = import_progress(db, user.id, data)
        assert count == 0

    def test_skips_invalid_entries(self, db):
        user = _make_user(db)
        data = self._data([{"badge_slug": "sport_spel"}])
        count = import_progress(db, user.id, data)
        assert count == 0

    def test_reuses_existing_nameholder(self, db):
        user = _make_user(db)
        data = self._data([
            {"badge_slug": "sport_spel", "level_index": 0, "step_index": 0,
             "status": "signed_off", "notes": None,
             "signed_off_by": "Leider Jan", "signed_off_at": "2026-03-01T10:00:00+00:00"},
            {"badge_slug": "sport_spel", "level_index": 0, "step_index": 1,
             "status": "signed_off", "notes": None,
             "signed_off_by": "Leider Jan", "signed_off_at": "2026-03-02T10:00:00+00:00"},
        ])
        import_progress(db, user.id, data)
        holders = db.query(User).filter(User.email.is_(None), User.name == "Leider Jan").all()
        assert len(holders) == 1


# ── full export → import roundtrip ───────────────────────────────────────────

class TestFullRoundtrip:
    """Export from user A; import YAML on user B and PDF on user C; verify parity."""

    def _setup_source(self, db):
        mentor = User(email="mentor@example.com", name="Leider Piet", status="active")
        db.add(mentor)
        db.commit()
        scout = _make_user(db, email="scout_a@example.com", name="Scout A")
        _make_entry(db, scout.id, level_index=0, step_index=0,
                    status="in_progress", notes="Bezig met voorbereiding")
        _make_entry(db, scout.id, level_index=0, step_index=1,
                    status="work_done")
        _make_entry(db, scout.id, level_index=1, step_index=0,
                    status="signed_off", signed_off_by_id=mentor.id,
                    signed_off_at=datetime(2026, 3, 1, tzinfo=timezone.utc),
                    notes="Goed gedaan")
        _make_entry(db, scout.id, level_index=2, step_index=0,
                    status="pending_signoff")  # must be absent from export
        return scout

    def _sorted_entries(self, db, user_id):
        return (
            db.query(ProgressEntry)
            .filter_by(user_id=user_id)
            .order_by(ProgressEntry.badge_slug,
                      ProgressEntry.level_index,
                      ProgressEntry.step_index)
            .all()
        )

    def test_yaml_import_matches_export(self, db):
        scout = self._setup_source(db)
        data = export_data(db, scout.id)
        yaml_str = to_yaml(data)

        user_b = _make_user(db, email="scout_b@example.com", name="Scout B")
        import_progress(db, user_b.id, yaml.safe_load(yaml_str))

        entries = self._sorted_entries(db, user_b.id)
        exported = sorted(data["progress"],
                          key=lambda x: (x["badge_slug"], x["level_index"], x["step_index"]))

        assert len(entries) == len(exported) == 3  # pending_signoff not exported
        for item, entry in zip(exported, entries):
            assert entry.badge_slug  == item["badge_slug"]
            assert entry.level_index == item["level_index"]
            assert entry.step_index  == item["step_index"]
            assert entry.status      == item["status"]
            assert entry.notes       == item["notes"]
            signer = entry.signed_off_by.name if entry.signed_off_by else None
            assert signer == item["signed_off_by"]

    def test_pdf_import_matches_export(self, db):
        scout = self._setup_source(db)
        data = export_data(db, scout.id)
        yaml_str = to_yaml(data)
        pdf = embed_yaml_in_pdf(to_pdf(data), yaml_str)

        user_c = _make_user(db, email="scout_c@example.com", name="Scout C")
        extracted = extract_yaml_from_pdf(pdf)
        assert extracted is not None
        import_progress(db, user_c.id, yaml.safe_load(extracted))

        entries = self._sorted_entries(db, user_c.id)
        exported = sorted(data["progress"],
                          key=lambda x: (x["badge_slug"], x["level_index"], x["step_index"]))

        assert len(entries) == len(exported) == 3
        for item, entry in zip(exported, entries):
            assert entry.badge_slug  == item["badge_slug"]
            assert entry.level_index == item["level_index"]
            assert entry.step_index  == item["step_index"]
            assert entry.status      == item["status"]
            assert entry.notes       == item["notes"]
            signer = entry.signed_off_by.name if entry.signed_off_by else None
            assert signer == item["signed_off_by"]

    def test_yaml_and_pdf_imports_are_equivalent(self, db):
        """YAML and PDF imports of the same source produce identical progress."""
        scout = self._setup_source(db)
        data = export_data(db, scout.id)
        yaml_str = to_yaml(data)
        pdf = embed_yaml_in_pdf(to_pdf(data), yaml_str)

        user_b = _make_user(db, email="scout_b@example.com", name="Scout B")
        user_c = _make_user(db, email="scout_c@example.com", name="Scout C")

        import_progress(db, user_b.id, yaml.safe_load(yaml_str))
        import_progress(db, user_c.id, yaml.safe_load(extract_yaml_from_pdf(pdf)))

        entries_b = self._sorted_entries(db, user_b.id)
        entries_c = self._sorted_entries(db, user_c.id)

        assert len(entries_b) == len(entries_c)
        for b, c in zip(entries_b, entries_c):
            assert b.badge_slug  == c.badge_slug
            assert b.level_index == c.level_index
            assert b.step_index  == c.step_index
            assert b.status      == c.status
            assert b.notes       == c.notes
            b_signer = b.signed_off_by.name if b.signed_off_by else None
            c_signer = c.signed_off_by.name if c.signed_off_by else None
            assert b_signer == c_signer

    def test_one_nameholder_per_signer_name(self, db):
        """Importing the same signer via both YAML and PDF creates exactly one emailless user."""
        scout = self._setup_source(db)
        data = export_data(db, scout.id)
        yaml_str = to_yaml(data)
        pdf = embed_yaml_in_pdf(to_pdf(data), yaml_str)

        user_b = _make_user(db, email="scout_b@example.com", name="Scout B")
        user_c = _make_user(db, email="scout_c@example.com", name="Scout C")

        import_progress(db, user_b.id, yaml.safe_load(yaml_str))
        import_progress(db, user_c.id, yaml.safe_load(extract_yaml_from_pdf(pdf)))

        # Collect all signer names referenced in the export
        signer_names = {
            item["signed_off_by"]
            for item in data["progress"]
            if item.get("signed_off_by")
        }
        for name in signer_names:
            holders = db.query(User).filter(User.email.is_(None), User.name == name).all()
            assert len(holders) == 1, (
                f"Expected exactly 1 emailless user for '{name}', found {len(holders)}"
            )


class TestJaarinsigne2026Inclusions:
    """Issue #111 — the include/exclude selections for jaarinsigne_2026 must
    survive an export/import round-trip."""

    def _setup_user_with_inclusions(self, db):
        scout = _make_user(db, email="ji@example.com", name="JI Scout")
        # Three picks across two badges and two niveaus.
        for bs, li, si in [("sport_spel", 0, 1), ("sport_spel", 1, 0), ("kamperen", 0, 0)]:
            db.add(Jaarinsigne2026Inclusion(
                user_id=scout.id, badge_slug=bs, level_index=li, step_index=si,
            ))
        db.commit()
        return scout

    def test_export_includes_inclusions(self, db):
        scout = self._setup_user_with_inclusions(db)
        data = export_data(db, scout.id)
        assert data["version"] == 3
        incs = data["jaarinsigne_2026_inclusions"]
        assert len(incs) == 3
        # Verify deterministic ordering (badge_slug, level_index, step_index)
        keys = [(i["badge_slug"], i["level_index"], i["step_index"]) for i in incs]
        assert keys == sorted(keys)

    def test_yaml_roundtrip_restores_inclusions_on_new_user(self, db):
        source = self._setup_user_with_inclusions(db)
        yaml_str = to_yaml(export_data(db, source.id))

        target = _make_user(db, email="target@example.com", name="Target")
        import_progress(db, target.id, yaml.safe_load(yaml_str))

        rows = (
            db.query(Jaarinsigne2026Inclusion)
            .filter_by(user_id=target.id)
            .order_by(Jaarinsigne2026Inclusion.badge_slug,
                      Jaarinsigne2026Inclusion.level_index,
                      Jaarinsigne2026Inclusion.step_index)
            .all()
        )
        assert [(r.badge_slug, r.level_index, r.step_index) for r in rows] == [
            ("kamperen", 0, 0),
            ("sport_spel", 0, 1),
            ("sport_spel", 1, 0),
        ]

    def test_import_is_idempotent(self, db):
        source = self._setup_user_with_inclusions(db)
        yaml_str = to_yaml(export_data(db, source.id))
        target = _make_user(db, email="target@example.com", name="Target")

        import_progress(db, target.id, yaml.safe_load(yaml_str))
        import_progress(db, target.id, yaml.safe_load(yaml_str))  # again

        n = db.query(Jaarinsigne2026Inclusion).filter_by(user_id=target.id).count()
        assert n == 3  # not 6 — unique constraint + existence check

    def test_v2_import_does_not_crash_or_create_inclusions(self, db):
        """Older v2 exports lack the jaarinsigne_2026_inclusions key; import must
        still work and simply create no inclusion rows."""
        target = _make_user(db, email="target@example.com", name="Target")
        v2_data = {
            "version": 2,
            "user": {"name": "Old Scout"},
            "progress": [{
                "badge_slug": "sport_spel", "level_index": 0, "step_index": 0,
                "status": "work_done", "notes": None,
                "signed_off_by": None, "signed_off_at": None,
            }],
        }
        import_progress(db, target.id, v2_data)
        assert db.query(Jaarinsigne2026Inclusion).filter_by(user_id=target.id).count() == 0

    def _hand_edited(self, inclusion_row: dict) -> dict:
        """v3 export payload with a single hand-edited inclusion row, no progress."""
        return {
            "version": 3,
            "user": {"name": "Hand-edited", "primary_speltak_type": "scouts"},
            "progress": [],
            "jaarinsigne_2026_inclusions": [inclusion_row],
        }

    def test_import_skips_non_int_indices(self, db):
        """Issue #124 — non-int level_index / step_index would 500 downstream
        pages (compute_score TypeError). The import must skip them silently."""
        target = _make_user(db, email="ne@example.com", name="NonInt")
        import_progress(db, target.id, self._hand_edited(
            {"badge_slug": "sport_spel", "level_index": "one", "step_index": 0}
        ))
        assert db.query(Jaarinsigne2026Inclusion).filter_by(user_id=target.id).count() == 0

    def test_import_skips_ineligible_badge_slug(self, db):
        """Issue #124 — only `gewoon` / `buitengewoon` badges may appear in an
        inclusion. A hand-edited slug pointing at an explorers badge or a
        completely made-up slug must be rejected at the import boundary."""
        target = _make_user(db, email="ie@example.com", name="Ineligible")
        # Made-up slug.
        import_progress(db, target.id, self._hand_edited(
            {"badge_slug": "definitely_not_a_real_badge", "level_index": 0, "step_index": 0}
        ))
        assert db.query(Jaarinsigne2026Inclusion).filter_by(user_id=target.id).count() == 0

    def test_import_skips_non_string_badge_slug(self, db):
        target = _make_user(db, email="ns@example.com", name="NonStr")
        import_progress(db, target.id, self._hand_edited(
            {"badge_slug": 12345, "level_index": 0, "step_index": 0}
        ))
        assert db.query(Jaarinsigne2026Inclusion).filter_by(user_id=target.id).count() == 0

    def test_import_still_accepts_valid_inclusions(self, db):
        """Sanity: the harden-up didn't reject legitimate rows."""
        target = _make_user(db, email="ok@example.com", name="OK")
        import_progress(db, target.id, self._hand_edited(
            {"badge_slug": "sport_spel", "level_index": 0, "step_index": 1}
        ))
        rows = db.query(Jaarinsigne2026Inclusion).filter_by(user_id=target.id).all()
        assert len(rows) == 1
        assert rows[0].level_index == 0
        assert rows[0].step_index == 1


# ── API endpoints ─────────────────────────────────────────────────────────────

def _full_register(client, db, email="scout@example.com", password="validpass1", name="Scout"):
    from insigne.models import ConfirmationToken
    client.post("/api/users", json={"email": email})
    user = db.query(User).filter_by(email=email).first()
    ct = db.query(ConfirmationToken).filter_by(user_id=user.id, type="email_confirmation").first()
    r = client.post("/api/users/confirm", json={"code": ct.token})
    setup = r.json()["setup_token"]
    r = client.post("/api/users/activate", json={"setup_token": setup, "password": password, "name": name})
    return r.json()["access_token"]


def _auth(token):
    return {"Authorization": f"Bearer {token}"}


class TestExportApi:
    def test_yaml_export_returns_yaml(self, client, db):
        token = _full_register(client, db)
        r = client.get("/api/users/me/export?format=yaml", headers=_auth(token))
        assert r.status_code == 200
        assert "yaml" in r.headers["content-type"]
        data = yaml.safe_load(r.content)
        assert data["version"] == 3

    def test_pdf_export_returns_pdf(self, client, db):
        token = _full_register(client, db)
        r = client.get("/api/users/me/export?format=pdf", headers=_auth(token))
        assert r.status_code == 200
        assert r.content[:4] == b"%PDF"

    def test_pdf_contains_embedded_yaml(self, client, db):
        token = _full_register(client, db)
        r = client.get("/api/users/me/export?format=pdf", headers=_auth(token))
        extracted = extract_yaml_from_pdf(r.content)
        assert extracted is not None
        assert yaml.safe_load(extracted)["version"] == 3

    def test_export_requires_auth(self, client, db):
        r = client.get("/api/users/me/export?format=yaml")
        assert r.status_code == 401


class TestImportApi:
    def test_import_yaml_file(self, client, db):
        token = _full_register(client, db)
        user = db.query(User).filter_by(email="scout@example.com").first()
        yaml_str = to_yaml({
            "version": 2, "user": {"name": "Scout"}, "progress": [{
                "badge_slug": "sport_spel", "level_index": 0, "step_index": 0,
                "status": "work_done", "notes": None,
                "signed_off_by": None, "signed_off_at": None,
            }],
        })
        r = client.post(
            "/api/users/me/import",
            headers=_auth(token),
            files={"file": ("export.yml", yaml_str.encode(), "application/x-yaml")},
        )
        assert r.status_code == 200
        assert r.json()["imported"] == 1

    def test_import_pdf_file(self, client, db):
        token = _full_register(client, db)
        yaml_str = to_yaml({
            "version": 2, "user": {"name": "Scout"}, "progress": [{
                "badge_slug": "sport_spel", "level_index": 0, "step_index": 0,
                "status": "in_progress", "notes": None,
                "signed_off_by": None, "signed_off_at": None,
            }],
        })
        user = db.query(User).filter_by(email="scout@example.com").first()
        data = yaml.safe_load(yaml_str)
        pdf = embed_yaml_in_pdf(to_pdf(data), yaml_str)
        r = client.post(
            "/api/users/me/import",
            headers=_auth(token),
            files={"file": ("export.pdf", pdf, "application/pdf")},
        )
        assert r.status_code == 200
        assert r.json()["imported"] == 1

    def test_import_wrong_extension_rejected(self, client, db):
        token = _full_register(client, db)
        r = client.post(
            "/api/users/me/import",
            headers=_auth(token),
            files={"file": ("export.txt", b"hello", "text/plain")},
        )
        assert r.status_code == 400

    def test_import_requires_auth(self, client, db):
        r = client.post("/api/users/me/import",
                        files={"file": ("e.yml", b"version: 1", "application/x-yaml")})
        assert r.status_code == 401


class TestJaarinsigne2026InclusionsViaApi:
    """End-to-end API round-trip for #111: a scout's jaarinsigne_2026
    inclusion picks must survive an export-via-API + import-via-API cycle
    on a different account. Mirrors the unit-level
    TestJaarinsigne2026Inclusions but goes through the HTTP layer."""

    def _setup_source(self, client, db):
        token = _full_register(client, db, email="src@example.com", name="Src")
        user = db.query(User).filter_by(email="src@example.com").first()
        for bs, li, si in [("sport_spel", 0, 1), ("sport_spel", 1, 0), ("kamperen", 0, 0)]:
            db.add(Jaarinsigne2026Inclusion(
                user_id=user.id, badge_slug=bs, level_index=li, step_index=si,
            ))
        db.commit()
        return token, user

    def test_yaml_roundtrip_via_api_restores_inclusions(self, client, db):
        src_token, _ = self._setup_source(client, db)
        # Export via API
        r = client.get("/api/users/me/export?format=yaml", headers=_auth(src_token))
        assert r.status_code == 200
        exported = yaml.safe_load(r.content)
        assert exported["version"] == 3
        assert len(exported["jaarinsigne_2026_inclusions"]) == 3

        # Fresh account, import via API
        tgt_token = _full_register(client, db, email="tgt@example.com", name="Tgt")
        tgt_user = db.query(User).filter_by(email="tgt@example.com").first()
        r = client.post(
            "/api/users/me/import",
            headers=_auth(tgt_token),
            files={"file": ("export.yml", r.content, "application/x-yaml")},
        )
        assert r.status_code == 200

        rows = (
            db.query(Jaarinsigne2026Inclusion)
            .filter_by(user_id=tgt_user.id)
            .order_by(Jaarinsigne2026Inclusion.badge_slug,
                      Jaarinsigne2026Inclusion.level_index,
                      Jaarinsigne2026Inclusion.step_index)
            .all()
        )
        assert [(r.badge_slug, r.level_index, r.step_index) for r in rows] == [
            ("kamperen", 0, 0),
            ("sport_spel", 0, 1),
            ("sport_spel", 1, 0),
        ]

    def test_pdf_roundtrip_via_api_restores_inclusions(self, client, db):
        """PDF embeds the YAML — import-via-API on a PDF must restore
        inclusions just like the YAML path."""
        src_token, _ = self._setup_source(client, db)
        r = client.get("/api/users/me/export?format=pdf", headers=_auth(src_token))
        assert r.status_code == 200
        pdf_bytes = r.content

        tgt_token = _full_register(client, db, email="tgt2@example.com", name="Tgt2")
        tgt_user = db.query(User).filter_by(email="tgt2@example.com").first()
        r = client.post(
            "/api/users/me/import",
            headers=_auth(tgt_token),
            files={"file": ("export.pdf", pdf_bytes, "application/pdf")},
        )
        assert r.status_code == 200

        n = db.query(Jaarinsigne2026Inclusion).filter_by(user_id=tgt_user.id).count()
        assert n == 3

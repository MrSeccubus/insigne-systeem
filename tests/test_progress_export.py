"""Tests for progress export/import service and API endpoints."""

from datetime import datetime, timezone
from unittest.mock import patch

import yaml
import pytest

from insigne.models import ProgressEntry, User
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
        assert data["version"] == 1
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
        assert parsed["version"] == 1
        assert parsed["progress"][0]["status"] == "work_done"


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
        assert extracted["version"] == 1
        assert extracted["progress"][0]["status"] == "work_done"


# ── import_progress ───────────────────────────────────────────────────────────

class TestImportProgress:
    def _data(self, entries):
        return {"version": 1, "user": {"name": "Scout"}, "progress": entries}

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
        assert data["version"] == 1

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
        assert yaml.safe_load(extracted)["version"] == 1

    def test_export_requires_auth(self, client, db):
        r = client.get("/api/users/me/export?format=yaml")
        assert r.status_code == 401


class TestImportApi:
    def test_import_yaml_file(self, client, db):
        token = _full_register(client, db)
        user = db.query(User).filter_by(email="scout@example.com").first()
        yaml_str = to_yaml({
            "version": 1, "user": {"name": "Scout"}, "progress": [{
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
            "version": 1, "user": {"name": "Scout"}, "progress": [{
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

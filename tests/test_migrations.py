"""Verify Alembic migrations upgrade and downgrade cleanly."""
import sqlite3
import sys
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config

sys.path.insert(0, str(Path(__file__).parent.parent / "api"))
from migrate import main as run_migrate  # noqa: E402

_ALEMBIC_INI = str(Path(__file__).parent.parent / "api" / "alembic.ini")

EXPECTED_TABLES = {
    "users",
    "confirmation_tokens",
    "progress_entries",
    "signoff_requests",
    "signoff_rejections",
    "groups",
    "speltakken",
    "group_memberships",
    "speltak_memberships",
    "membership_requests",
    "speltak_favorite_badges",
    "group_favorite_badges",
}


@pytest.fixture()
def alembic_cfg(tmp_path):
    db_path = tmp_path / "test.db"
    import insigne.config as cfg
    cfg.config.database_url = f"sqlite:///{db_path}"
    yield Config(_ALEMBIC_INI), db_path


def _tables(db_path):
    return {r[0] for r in sqlite3.connect(db_path).execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name != 'alembic_version'"
    )}


def test_upgrade_creates_all_tables(alembic_cfg):
    ac, db_path = alembic_cfg
    command.upgrade(ac, "head")
    assert _tables(db_path) == EXPECTED_TABLES


def test_downgrade_removes_all_tables(alembic_cfg):
    ac, db_path = alembic_cfg
    command.upgrade(ac, "head")
    command.downgrade(ac, "base")
    assert _tables(db_path) == set()


def test_migrate_stamps_existing_unversioned_db(tmp_path):
    """migrate.py should auto-stamp a DB that has tables but no alembic_version."""
    db_path = tmp_path / "legacy.db"
    import insigne.config as cfg
    cfg.config.database_url = f"sqlite:///{db_path}"

    # Simulate a pre-Alembic database: create tables directly, no version table
    conn = sqlite3.connect(db_path)
    conn.execute("CREATE TABLE users (id TEXT PRIMARY KEY, email TEXT)")
    conn.execute("CREATE TABLE confirmation_tokens (id TEXT PRIMARY KEY)")
    conn.execute("CREATE TABLE progress_entries (id TEXT PRIMARY KEY)")
    conn.execute("CREATE TABLE signoff_requests (id TEXT PRIMARY KEY)")
    conn.execute("CREATE TABLE signoff_rejections (id TEXT PRIMARY KEY)")
    conn.commit()
    conn.close()

    # Should not raise — should stamp then upgrade (no-op)
    run_migrate()

    version = list(sqlite3.connect(db_path).execute("SELECT * FROM alembic_version"))
    assert len(version) == 1

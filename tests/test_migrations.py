"""Verify Alembic migrations upgrade and downgrade cleanly."""
import sqlite3
import tempfile
from pathlib import Path

import pytest
from alembic.config import Config
from alembic import command

_ALEMBIC_INI = str(Path(__file__).parent.parent / "api" / "alembic.ini")

EXPECTED_TABLES = {
    "users",
    "confirmation_tokens",
    "progress_entries",
    "signoff_requests",
    "signoff_rejections",
}


@pytest.fixture()
def alembic_cfg(tmp_path):
    db_path = tmp_path / "test.db"
    import insigne.config as cfg
    cfg.config.database_url = f"sqlite:///{db_path}"
    ac = Config(_ALEMBIC_INI)
    yield ac, db_path


def test_upgrade_creates_all_tables(alembic_cfg):
    ac, db_path = alembic_cfg
    command.upgrade(ac, "head")
    tables = {r[0] for r in sqlite3.connect(db_path).execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name != 'alembic_version'"
    )}
    assert tables == EXPECTED_TABLES


def test_downgrade_removes_all_tables(alembic_cfg):
    ac, db_path = alembic_cfg
    command.upgrade(ac, "head")
    command.downgrade(ac, "base")
    tables = {r[0] for r in sqlite3.connect(db_path).execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name != 'alembic_version'"
    )}
    assert tables == set()

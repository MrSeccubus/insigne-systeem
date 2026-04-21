"""Run Alembic migrations, auto-stamping existing unversioned databases."""
import re
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from alembic import command
from alembic.config import Config
from alembic.script import ScriptDirectory
from insigne.config import config as app_config

ALEMBIC_INI = str(Path(__file__).parent / "alembic.ini")


def main() -> None:
    ac = Config(ALEMBIC_INI)

    m = re.match(r"sqlite:///(.+)", app_config.database_url)
    if m:
        db_path = Path(m.group(1))
        if db_path.exists():
            conn = sqlite3.connect(db_path)
            tables = {r[0] for r in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            )}
            versioned = (
                "alembic_version" in tables
                and bool(list(conn.execute("SELECT 1 FROM alembic_version LIMIT 1")))
            )
            conn.close()
            user_tables = tables - {"alembic_version"}
            if user_tables and not versioned:
                # Stamp at the oldest revision so that only migrations after
                # the initial schema creation run (tables already exist).
                revisions = list(ScriptDirectory.from_config(ac).walk_revisions())
                initial_rev = revisions[-1].revision
                print(f"Existing database detected — stamping at {initial_rev}...")
                command.stamp(ac, initial_rev)

    command.upgrade(ac, "head")


if __name__ == "__main__":
    main()

"""Run Alembic migrations, auto-stamping existing unversioned databases."""
import re
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from alembic import command
from alembic.config import Config
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
                print("Existing database detected — stamping initial revision...")
                command.stamp(ac, "head")

    command.upgrade(ac, "head")


if __name__ == "__main__":
    main()

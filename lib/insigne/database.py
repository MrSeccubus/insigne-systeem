from typing import Generator

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import NullPool

from .config import config
from .models import Base  # noqa: F401 — re-exported for callers

_is_sqlite = config.database_url.startswith("sqlite")

engine = create_engine(
    config.database_url,
    connect_args={"check_same_thread": False} if _is_sqlite else {},
    # SQLite connections are cheap; NullPool avoids the default QueuePool
    # (pool_size=5) becoming a bottleneck / deadlock source under a proxy.
    poolclass=NullPool if _is_sqlite else None,
)

SessionLocal = sessionmaker(autocommit=False, autoflush=True, bind=engine)


def get_db() -> Generator[Session, None, None]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

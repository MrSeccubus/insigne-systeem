import os
import sys
from pathlib import Path

# Must be set before any insigne module is imported (config.py reads it at module level)
os.environ["INSIGNE_CONFIG"] = str(Path(__file__).parent / "fixtures" / "config.yml")
# Tests assert production behaviour (immutable static cache, SW registration);
# make sure a dev shell's INSIGNE_DEV doesn't flip the app into dev mode.
os.environ.pop("INSIGNE_DEV", None)

# Make api/ importable for TestClient tests
sys.path.insert(0, str(Path(__file__).parent.parent / "api"))

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from insigne.config import config as _config
from insigne.database import get_db
from insigne.models import Base


@pytest.fixture(autouse=True)
def reset_config():
    """Restore mutable config fields after each test to prevent cross-test pollution."""
    saved_admins = list(_config.admins)
    saved_allow = _config.allow_any_user_to_create_groups
    saved_rl = (
        _config.rate_limit.enabled,
        _config.rate_limit.register,
        _config.rate_limit.forgot_password,
        _config.rate_limit.contact,
    )
    yield
    _config.admins = saved_admins
    _config.allow_any_user_to_create_groups = saved_allow
    (
        _config.rate_limit.enabled,
        _config.rate_limit.register,
        _config.rate_limit.forgot_password,
        _config.rate_limit.contact,
    ) = saved_rl
    # Clear the in-memory limiter counters so one test's requests can't leak
    # into another's budget (the limiter lives on the app singleton).
    try:
        from ratelimit import limiter
        limiter.reset()
    except Exception:
        pass


@pytest.fixture
def db():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    session = Session()
    yield session
    session.close()
    engine.dispose()


@pytest.fixture
def client(db):
    from main import app

    def _override():
        yield db

    app.dependency_overrides[get_db] = _override
    # CSRF middleware (#99) requires Origin or Referer on state-changing
    # requests to non-/api/ paths. Set a matching default Origin so individual
    # tests don't have to. Tests that exercise the middleware itself override
    # this on a per-request basis.
    from insigne.config import config as _cfg
    with TestClient(app, raise_server_exceptions=True, headers={"Origin": _cfg.base_url}) as c:
        yield c
    app.dependency_overrides.pop(get_db, None)

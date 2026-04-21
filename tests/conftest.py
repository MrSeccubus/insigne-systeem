import os
import sys
from pathlib import Path

# Must be set before any insigne module is imported (config.py reads it at module level)
os.environ["INSIGNE_CONFIG"] = str(Path(__file__).parent / "fixtures" / "config.yml")

# Make api/ importable for TestClient tests
sys.path.insert(0, str(Path(__file__).parent.parent / "api"))

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from insigne.database import get_db
from insigne.models import Base


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
    with TestClient(app, raise_server_exceptions=True) as c:
        yield c
    app.dependency_overrides.pop(get_db, None)

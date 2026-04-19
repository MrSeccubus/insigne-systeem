import os
from pathlib import Path

# Must be set before any insigne module is imported (config.py reads it at module level)
os.environ["INSIGNE_CONFIG"] = str(Path(__file__).parent / "fixtures" / "config.yml")

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from insigne.models import Base


@pytest.fixture
def db():
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    session = Session()
    yield session
    session.close()
    engine.dispose()

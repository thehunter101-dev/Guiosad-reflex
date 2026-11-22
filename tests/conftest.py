import os

import pytest
import sqlalchemy as sa
from sqlmodel import Session, SQLModel, create_engine

os.environ.setdefault("AUTH_SECRET_KEY", "test-secret")

import guiospro.models.database  # noqa: E402,F401
from guiospro.core.catalog import get_catalog  # noqa: E402
from guiospro.models import repository as repo  # noqa: E402


@pytest.fixture
def engine(tmp_path):
    eng = create_engine(f"sqlite:///{tmp_path / 'test.db'}")

    @sa.event.listens_for(eng, "connect")
    def _fk(conn, _):
        conn.execute("PRAGMA foreign_keys=ON")

    SQLModel.metadata.create_all(eng)
    with Session(eng) as s:
        repo.seed_catalog(s, get_catalog())
        s.commit()
    return eng


@pytest.fixture
def session(engine):
    with Session(engine, expire_on_commit=False) as s:
        yield s
        s.rollback()


@pytest.fixture
def user(session):
    return repo.create_user(session, "Ana Pérez", "Ana@Example.org", "hash", "UNEMI")

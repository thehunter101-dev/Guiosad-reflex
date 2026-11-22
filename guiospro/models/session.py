"""Motor y sesiones de base de datos."""

from collections.abc import Iterator
from contextlib import contextmanager
from functools import cache

import sqlalchemy as sa
from sqlmodel import Session, create_engine

from ..settings import get_settings


@cache
def get_engine(url: str | None = None) -> sa.Engine:
    url = url or get_settings().database_url
    kwargs: dict = {"pool_pre_ping": True}
    if url.startswith("sqlite"):
        kwargs["connect_args"] = {"check_same_thread": False}
        engine = create_engine(url, **kwargs)

        @sa.event.listens_for(engine, "connect")
        def _fk_on(dbapi_conn, _):  # Cascadas también en SQLite.
            dbapi_conn.execute("PRAGMA foreign_keys=ON")

        return engine
    return create_engine(url, **kwargs)


@contextmanager
def session_scope(engine: sa.Engine | None = None) -> Iterator[Session]:
    with Session(engine or get_engine(), expire_on_commit=False) as session:
        try:
            yield session
            session.commit()
        except Exception:
            session.rollback()
            raise

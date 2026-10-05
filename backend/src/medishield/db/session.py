"""Engine / session factory. SQLite by default (WAL), Postgres via ``DATABASE_URL``."""

from __future__ import annotations

import threading
from collections.abc import Iterator
from contextlib import contextmanager

from sqlalchemy import create_engine, event
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from medishield.config import get_settings
from medishield.db.models import Base

_lock = threading.Lock()
_engine: Engine | None = None
_factory: sessionmaker[Session] | None = None


def get_engine() -> Engine:
    global _engine, _factory
    with _lock:
        if _engine is None:
            s = get_settings()
            s.state_dir.mkdir(parents=True, exist_ok=True)
            kwargs = {"connect_args": {"check_same_thread": False, "timeout": 30}} if s.database_url.startswith("sqlite") else {}
            _engine = create_engine(s.database_url, future=True, **kwargs)
            if s.database_url.startswith("sqlite"):
                @event.listens_for(_engine, "connect")
                def _pragmas(conn, _rec):                 # concurrent API + worker access
                    cur = conn.cursor()
                    cur.execute("PRAGMA journal_mode=WAL")
                    cur.execute("PRAGMA foreign_keys=ON")
                    cur.close()
            Base.metadata.create_all(_engine)
            _factory = sessionmaker(_engine, expire_on_commit=False)
        return _engine


def reset_engine() -> None:
    """Dispose the engine (tests point the settings at a fresh state dir)."""
    global _engine, _factory
    with _lock:
        if _engine is not None:
            _engine.dispose()
        _engine, _factory = None, None


@contextmanager
def session_scope() -> Iterator[Session]:
    get_engine()
    assert _factory is not None
    session = _factory()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()

"""Engine / session factory. SQLite by default (WAL), Postgres via ``DATABASE_URL``."""

from __future__ import annotations

import threading
from collections.abc import Iterator
from contextlib import contextmanager

from sqlalchemy import create_engine, event, inspect, text
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
            add_missing_columns(_engine)
            _factory = sessionmaker(_engine, expire_on_commit=False)
        return _engine


def add_missing_columns(engine: Engine) -> list[str]:
    """Additive schema upgrade: a database created by an older version gets the columns added since (with their defaults).

    Only ever adds nullable-or-defaulted columns; it never drops, renames or rewrites data. Larger changes would need a real
    migration tool (Alembic)."""
    added = []
    insp = inspect(engine)
    for table in Base.metadata.sorted_tables:
        if not insp.has_table(table.name):
            continue
        have = {c["name"] for c in insp.get_columns(table.name)}
        for col in table.columns:
            if col.name in have:
                continue
            ddl = col.type.compile(dialect=engine.dialect)
            default = col.default.arg if col.default is not None and not col.default.is_callable else None
            clause = f" DEFAULT {default!r}" if isinstance(default, (int, float, str)) and not isinstance(default, bool) else (
                f" DEFAULT {int(default)}" if isinstance(default, bool) else "")
            with engine.begin() as conn:
                conn.execute(text(f'ALTER TABLE "{table.name}" ADD COLUMN "{col.name}" {ddl}{clause}'))
            added.append(f"{table.name}.{col.name}")
    return added


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

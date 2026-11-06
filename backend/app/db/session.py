from __future__ import annotations

import logging
import threading
import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager

from sqlalchemy import create_engine, event
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import get_settings

_engine: Engine | None = None
_SessionLocal: sessionmaker[Session] | None = None


def _configure_sqlite(engine: Engine) -> None:
    @event.listens_for(engine, "connect")
    def _on_connect(dbapi_conn, _record):  # pragma: no cover - driver hook
        cur = dbapi_conn.cursor()
        cur.execute("PRAGMA journal_mode=WAL")
        cur.execute("PRAGMA synchronous=NORMAL")
        cur.execute("PRAGMA foreign_keys=ON")
        cur.execute("PRAGMA busy_timeout=60000")
        cur.close()


def get_engine() -> Engine:
    global _engine, _SessionLocal
    if _engine is None:
        settings = get_settings()
        kwargs: dict = {"pool_pre_ping": True}
        if settings.is_sqlite:
            kwargs["connect_args"] = {"check_same_thread": False, "timeout": 60}
            # Many synthesis threads read briefly at once; don't make them queue for a connection.
            kwargs.update(pool_size=20, max_overflow=80, pool_timeout=120)
        elif settings.database_url.startswith("postgresql+psycopg"):
            # Supabase's pooler (Supavisor, port 6543) runs in transaction mode, which
            # can't keep server-side prepared statements; psycopg must not create them.
            kwargs["connect_args"] = {"prepare_threshold": None}
            kwargs.update(pool_size=10, max_overflow=20, pool_timeout=60, pool_recycle=1800)
        _engine = create_engine(settings.database_url, **kwargs)
        if settings.is_sqlite:
            _configure_sqlite(_engine)
        _SessionLocal = sessionmaker(bind=_engine, expire_on_commit=False, autoflush=False)
    return _engine


def reset_engine() -> None:
    """Dispose the engine (used by tests that swap DATABASE_URL)."""
    global _engine, _SessionLocal
    if _engine is not None:
        _engine.dispose()
    _engine = None
    _SessionLocal = None


def SessionLocal() -> Session:
    get_engine()
    assert _SessionLocal is not None
    return _SessionLocal()


_scope_state = threading.local()
# Background writers queue here, in-process, *before* taking a connection: SQLite's
# own busy handler polls with sleeps, so with dozens of waiting threads some starve
# past the timeout (and each waiter would pin a pooled connection meanwhile).
_WRITE_MUTEX = threading.Lock()


@contextmanager
def session_scope(*, write: bool = True) -> Iterator[Session]:
    """A committed unit of work. On SQLite, write scopes take the write lock up
    front (BEGIN IMMEDIATE, waiting up to busy_timeout) so background read-then-write
    work queues fairly behind other writers instead of racing them. Keep scopes
    short; pass write=False for read-only polling."""
    depth = getattr(_scope_state, "depth", 0)
    # Nested scopes on one thread would wait on their own outer lock, so only the
    # outermost write scope serializes.
    exclusive = write and depth == 0 and get_settings().is_sqlite
    if exclusive:
        _WRITE_MUTEX.acquire()
    session = SessionLocal()
    _scope_state.depth = depth + 1
    try:
        if exclusive:
            session.connection().exec_driver_sql("BEGIN IMMEDIATE")
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        _scope_state.depth = depth
        session.close()
        if exclusive:
            _WRITE_MUTEX.release()


def is_lock_error(exc: BaseException) -> bool:
    """Transient contention: SQLite busy/locked, or no pooled connection free in time."""
    from sqlalchemy.exc import OperationalError, TimeoutError as PoolTimeout

    if isinstance(exc, PoolTimeout):
        return True
    return isinstance(exc, OperationalError) and any(k in str(exc).lower() for k in ("locked", "busy"))


def best_effort_write(fn: Callable[[Session], object], *, attempts: int = 3) -> bool:
    """Run a small, non-critical write (heartbeat, progress). Retries briefly if the
    database is busy and gives up quietly: losing one progress tick must never fail a job."""
    for attempt in range(attempts):
        try:
            with session_scope() as db:
                fn(db)
            return True
        except Exception as exc:
            if not is_lock_error(exc):
                raise
            time.sleep(0.5 * (attempt + 1))
    logging.getLogger(__name__).warning("db.write_skipped_busy")
    return False


def get_db() -> Iterator[Session]:
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()

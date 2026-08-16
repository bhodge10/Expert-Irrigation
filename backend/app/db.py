"""Database engine, session factory, and the declarative base."""

from datetime import datetime, timezone
from typing import Iterator

from sqlalchemy import create_engine, event
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from .config import settings

_url = settings.database_url_resolved

# check_same_thread is a SQLite-only quirk; harmless to skip elsewhere.
# timeout is SQLite's busy wait: with the portal and the worker sharing one
# file, a collision should wait a few seconds, not fail with "locked".
_connect_args = (
    {"check_same_thread": False, "timeout": 15} if _url.startswith("sqlite") else {}
)

engine = create_engine(_url, connect_args=_connect_args, pool_pre_ping=True)

if _url.startswith("sqlite"):

    @event.listens_for(engine, "connect")
    def _sqlite_wal(dbapi_conn, _record):
        # WAL lets the portal read while the worker writes. Persistent, but
        # cheap to set on every connect and self-healing on fresh files.
        dbapi_conn.execute("PRAGMA journal_mode=WAL")
SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


class Base(DeclarativeBase):
    pass


def get_db() -> Iterator[Session]:
    """FastAPI dependency: one database session per request."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def utcnow() -> datetime:
    """Timezone-aware 'now'. Everything in the database is stored in UTC."""
    return datetime.now(timezone.utc)


def as_utc(value: datetime | None) -> datetime | None:
    """SQLite hands back naive datetimes. Treat those as UTC."""
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value

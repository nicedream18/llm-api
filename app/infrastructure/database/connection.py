"""Database connection pool using SQLAlchemy."""
import logging
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.config import config

logger = logging.getLogger(__name__)

engine = create_engine(
    config.db.url,
    pool_size=config.db.pool_size,
    max_overflow=config.db.max_overflow,
    pool_pre_ping=True,
    pool_recycle=1800,
    echo=False,
    future=True,
)

SessionLocal = sessionmaker(bind=engine, autocommit=False, autoflush=False, future=True)


@contextmanager
def get_db() -> Iterator[Session]:
    db = SessionLocal()
    try:
        yield db
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def affected_rows(result: Any) -> int:
    """Return a portable DML row count across SQLAlchemy result implementations."""
    return int(getattr(result, "rowcount", 0) or 0)


def row_lock_suffix(db: Any) -> str:
    """Resolve the actual dialect for both ORM sessions and Core connections."""
    bind = db.get_bind() if isinstance(db, Session) else getattr(db, "engine", None)
    return " FOR UPDATE" if getattr(getattr(bind, "dialect", None), "name", None) == "mysql" else ""

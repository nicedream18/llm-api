"""Database connection pool using SQLAlchemy."""
import logging
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, Session
from contextlib import contextmanager

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
def get_db() -> Session:
    db = SessionLocal()
    try:
        yield db
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()

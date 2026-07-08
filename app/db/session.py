"""Azure DB client: connection lifecycle and session management.

Other services should go through `azure_db_client` rather than importing
the SQLAlchemy engine/session factory directly, so the underlying database
technology stays swappable behind one interface.
"""

from __future__ import annotations

import logging
from collections.abc import Generator
from contextlib import contextmanager

from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import azure_settings
from app.db.base import Base

logger = logging.getLogger(__name__)


def _build_engine():
    connect_args = {}
    url = azure_settings.sqlalchemy_database_url
    if url.startswith("sqlite"):
        connect_args = {"check_same_thread": False}

    return create_engine(
        url,
        echo=azure_settings.sql_echo,
        pool_pre_ping=True,
        connect_args=connect_args,
    )


engine = _build_engine()
SessionLocal = sessionmaker(bind=engine, autocommit=False, autoflush=False)


def get_db() -> Generator[Session, None, None]:
    """FastAPI dependency that yields a DB session.

    Commits on successful request completion, rolls back on any exception,
    and always closes the session afterwards.
    """
    db = SessionLocal()
    try:
        yield db
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


class AzureDatabaseClient:
    """Thin, reusable wrapper around the Azure DB connection and sessions."""

    def __init__(self) -> None:
        self._engine = engine
        self._session_factory = SessionLocal

    def init_db(self) -> None:
        """Create any tables that don't exist yet. Safe to call on startup."""
        logger.info("Initializing Azure DB schema")
        Base.metadata.create_all(bind=self._engine)

    def check_connection(self) -> bool:
        """Lightweight health check used by startup/readiness probes."""
        try:
            with self._engine.connect() as connection:
                connection.execute(text("SELECT 1"))
            return True
        except Exception:
            logger.exception("Azure DB connection check failed")
            return False

    @contextmanager
    def session_scope(self) -> Generator[Session, None, None]:
        """Context manager that commits on success and rolls back on error."""
        session = self._session_factory()
        try:
            yield session
            session.commit()
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()


azure_db_client = AzureDatabaseClient()

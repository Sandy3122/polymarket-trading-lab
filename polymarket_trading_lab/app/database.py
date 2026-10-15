"""SQLAlchemy setup that works with SQLite and PostgreSQL URLs."""

from collections.abc import Generator

from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker
from sqlalchemy.pool import StaticPool

from .config import Settings, get_settings


class Base(DeclarativeBase):
    """Declarative base for all domain models."""


def create_engine_for_settings(settings: Settings) -> Engine:
    """Create an engine without relying on a dialect-specific feature."""

    connect_args: dict[str, object] = {}
    engine_kwargs: dict[str, object] = {"future": True}
    if settings.database_url.startswith("sqlite"):
        connect_args["check_same_thread"] = False
        if settings.database_url.endswith(":memory:"):
            engine_kwargs["poolclass"] = StaticPool

    return create_engine(
        settings.database_url,
        connect_args=connect_args,
        **engine_kwargs,
    )


settings = get_settings()
engine = create_engine_for_settings(settings)
SessionLocal = sessionmaker(
    bind=engine,
    autoflush=False,
    expire_on_commit=False,
    class_=Session,
)


def get_session() -> Generator[Session, None, None]:
    """Yield a session and always close it for callers that use the generator."""

    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()


def init_db(target_engine: Engine = engine) -> None:
    """Create all mapped tables for a local database."""

    # Importing models here registers every table on Base.metadata without
    # introducing an import cycle when database.py is imported by models.py.
    from . import models  # noqa: F401

    Base.metadata.create_all(target_engine)

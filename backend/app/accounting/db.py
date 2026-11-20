"""Engine e sessões SQLAlchemy. SQLite em demo, PostgreSQL em produção (mesma API)."""

from __future__ import annotations

from pathlib import Path

from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import sessionmaker

from app.accounting.tables import Base

SQLITE_PREFIX = "sqlite:///"


def make_engine(url: str) -> Engine:
    connect_args: dict[str, object] = {}
    if url.startswith("sqlite"):
        connect_args["check_same_thread"] = False
        if url.startswith(SQLITE_PREFIX) and url != "sqlite://":
            path = Path(url[len(SQLITE_PREFIX) :])
            path.parent.mkdir(parents=True, exist_ok=True)
    return create_engine(url, connect_args=connect_args)


def init_schema(engine: Engine) -> None:
    # Demo: criação directa. Migrações Alembic ficam como TODO (ver docs/architecture.md).
    Base.metadata.create_all(engine)


def make_session_factory(engine: Engine) -> sessionmaker:
    return sessionmaker(bind=engine, expire_on_commit=False)

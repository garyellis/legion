"""Shared SQLAlchemy infrastructure.

Single Base and engine factory used by all layers.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import Engine
from sqlalchemy import create_engine as _sa_create_engine
from sqlalchemy.orm import DeclarativeBase
from sqlalchemy.pool import StaticPool


class Base(DeclarativeBase):
    """Shared ORM base for all legion models."""

    pass


def is_in_memory_sqlite_url(db_url: str) -> bool:
    """Return whether the URL points at SQLite's in-memory database."""
    return db_url.startswith("sqlite") and ":memory:" in db_url


def create_engine(db_url: str, **kwargs: Any) -> Engine:
    """Create a SQLAlchemy engine with sensible defaults.

    For SQLite URLs, automatically sets ``check_same_thread=False`` so the
    engine can be used from multiple threads (e.g. async handlers + scheduler).
    """
    kwargs.setdefault("pool_pre_ping", True)

    if db_url.startswith("sqlite"):
        connect_args = dict(kwargs.pop("connect_args", {}) or {})  # type: ignore[arg-type]
        connect_args.setdefault("check_same_thread", False)
        kwargs["connect_args"] = connect_args

        # In-memory SQLite needs StaticPool so all connections share one DB.
        if is_in_memory_sqlite_url(db_url):
            kwargs.setdefault("poolclass", StaticPool)

    return _sa_create_engine(db_url, **kwargs)  # type: ignore[arg-type]


def create_all(engine: Engine) -> None:
    """Create all registered tables directly from ORM metadata."""
    Base.metadata.create_all(engine)

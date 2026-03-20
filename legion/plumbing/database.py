"""Shared SQLAlchemy infrastructure.

Single Base and engine factory used by all layers.
"""

from __future__ import annotations

from sqlalchemy import Engine
from sqlalchemy import create_engine as _sa_create_engine
from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    """Shared ORM base for all legion models."""

    pass


def create_engine(db_url: str, **kwargs: object) -> Engine:
    """Create a SQLAlchemy engine with sensible defaults.

    For SQLite URLs, automatically sets ``check_same_thread=False`` so the
    engine can be used from multiple threads (e.g. async handlers + scheduler).
    """
    kwargs.setdefault("pool_pre_ping", True)

    if db_url.startswith("sqlite"):
        connect_args = dict(kwargs.pop("connect_args", {}) or {})  # type: ignore[arg-type]
        connect_args.setdefault("check_same_thread", False)
        kwargs["connect_args"] = connect_args

    return _sa_create_engine(db_url, **kwargs)  # type: ignore[arg-type]


def create_all(engine: Engine) -> None:
    """Create all registered tables."""
    Base.metadata.create_all(engine)

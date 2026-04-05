"""Cursor-based pagination primitives for repository queries."""
from __future__ import annotations

import base64
from dataclasses import dataclass
from datetime import datetime
from typing import Generic, TypeVar

T = TypeVar("T")


@dataclass(frozen=True)
class Page(Generic[T]):
    """A single page of results with an opaque continuation cursor."""

    items: list[T]
    next_cursor: str | None  # None means last page
    has_more: bool


_CURSOR_VERSION = "v1"


def encode_cursor(created_at: datetime, id: str) -> str:
    """Encode a (created_at, id) pair as an opaque cursor token."""
    if created_at.tzinfo is None:
        raise ValueError("encode_cursor requires a timezone-aware datetime")
    raw = f"{created_at.isoformat()}|{id}"
    encoded = base64.urlsafe_b64encode(raw.encode()).decode()
    return f"{_CURSOR_VERSION}:{encoded}"


class _CursorVersionError(ValueError):
    """Internal marker for version mismatch — always re-raised as-is."""


def decode_cursor(cursor: str) -> tuple[datetime, str]:
    """Decode an opaque cursor token into (created_at, id)."""
    try:
        if ":" in cursor:
            version, encoded = cursor.split(":", 1)
            if version != _CURSOR_VERSION:
                raise _CursorVersionError(
                    f"Unsupported cursor version: {version}"
                )
        else:
            encoded = cursor  # backward compat with unversioned cursors
        raw = base64.urlsafe_b64decode(encoded.encode()).decode()
        ts_str, id_ = raw.rsplit("|", 1)
        return datetime.fromisoformat(ts_str), id_
    except _CursorVersionError:
        raise
    except Exception as exc:
        raise ValueError(f"Invalid pagination cursor: {cursor!r}") from exc

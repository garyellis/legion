"""Metadata-only helpers for annotating tool functions."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable


@dataclass(frozen=True)
class ToolMeta:
    name: str
    description: str
    tags: tuple[str, ...] = ()
    version: str = "1.0"


def tool(
    name: str,
    *,
    description: str = "",
    tags: tuple[str, ...] = (),
    version: str = "1.0",
) -> Callable[[Callable[..., object]], Callable[..., object]]:
    """Attach immutable tool metadata without altering function execution."""
    meta = ToolMeta(
        name=name,
        description=description,
        tags=tuple(tags),
        version=version,
    )

    def decorator(func: Callable[..., object]) -> Callable[..., object]:
        setattr(func, "__tool_meta__", meta)
        return func

    return decorator


def get_tool_meta(func: Callable[..., object]) -> ToolMeta | None:
    """Return attached tool metadata, if present."""
    meta = getattr(func, "__tool_meta__", None)
    return meta if isinstance(meta, ToolMeta) else None

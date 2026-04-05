"""Metadata-only helpers for annotating tool functions."""

from __future__ import annotations

import logging
from importlib.metadata import entry_points
from dataclasses import dataclass
from typing import Callable

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ToolMeta:
    name: str
    description: str
    category: str
    read_only: bool = True
    tags: tuple[str, ...] = ()
    version: str = "1.0"


def tool(
    name: str,
    *,
    description: str = "",
    category: str,
    read_only: bool = True,
    tags: tuple[str, ...] = (),
    version: str = "1.0",
) -> Callable[[Callable[..., object]], Callable[..., object]]:
    """Attach immutable tool metadata without altering function execution."""
    meta = ToolMeta(
        name=name,
        description=description,
        category=category,
        read_only=read_only,
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


ENTRY_POINT_GROUP = "legion.tools"


@dataclass(frozen=True)
class DiscoveredTool:
    """A loaded callable paired with its ToolMeta and entry point string."""

    func: Callable[..., object]
    meta: ToolMeta
    entry_point: str  # e.g. "pod_status = legion.core.kubernetes.pods:pod_status"


def load_tool_callables(
    *,
    categories: list[str] | None = None,
    read_only_only: bool = False,
) -> list[DiscoveredTool]:
    """Discover all ``legion.tools`` entry points, load each, and return DiscoveredTool objects.

    Parameters
    ----------
    categories:
        If provided, only return tools whose ``meta.category`` is in this list.
    read_only_only:
        If ``True``, only return tools where ``meta.read_only`` is ``True``.
    """
    if categories is not None and not categories:
        categories = None

    eps = entry_points(group=ENTRY_POINT_GROUP)
    if not eps:
        logger.info("No legion.tools entry points found")
        return []

    seen_names: dict[str, str] = {}  # tool name → entry_point string
    results: list[DiscoveredTool] = []

    for ep in eps:
        ep_str = f"{ep.name} = {ep.value}"

        try:
            func = ep.load()
        except Exception:
            logger.warning("Failed to load entry point %s", ep_str, exc_info=True)
            continue

        meta = get_tool_meta(func)
        if meta is None:
            logger.warning(
                "Entry point %s has no __tool_meta__; skipping", ep_str
            )
            continue

        if meta.name in seen_names:
            logger.warning(
                "Duplicate tool name %r from %s (already loaded from %s); skipping",
                meta.name,
                ep_str,
                seen_names[meta.name],
            )
            continue

        seen_names[meta.name] = ep_str

        if categories is not None and meta.category not in categories:
            continue

        if read_only_only and not meta.read_only:
            continue

        results.append(DiscoveredTool(func=func, meta=meta, entry_point=ep_str))

    return results


def discover_tool_metadata() -> list[ToolMeta]:
    """Return ToolMeta for every discoverable ``legion.tools`` entry point."""
    return [dt.meta for dt in load_tool_callables()]

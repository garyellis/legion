"""LangChain StructuredTool adapter for discovered tool plugins."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from legion.plumbing.plugins import load_tool_callables

if TYPE_CHECKING:
    from langchain_core.tools import BaseTool

logger = logging.getLogger(__name__)


def discover_tools(
    *,
    categories: list[str] | None = None,
    read_only_only: bool = False,
) -> list[BaseTool]:
    """Discover all legion.tools entry points and wrap as StructuredTool.

    Optional filters:
    - categories: only return tools matching these categories
    - read_only_only: only return tools with read_only=True
    """
    try:
        from langchain_core.tools import StructuredTool
    except ImportError as exc:
        raise ImportError(
            "discover_tools() requires langchain-core. "
            "Install the agents optional dependency group.",
        ) from exc

    discovered = load_tool_callables(
        categories=categories,
        read_only_only=read_only_only,
    )

    tools: list[BaseTool] = []
    for item in discovered:
        try:
            adapted = StructuredTool.from_function(
                func=item.func,
                name=item.meta.name,
                description=item.meta.description or f"Run the {item.meta.name} tool.",
            )
        except Exception:
            logger.warning("Failed to adapt tool %s as StructuredTool", item.meta.name, exc_info=True)
            continue
        tools.append(adapted)
        logger.debug("adapted tool %s as StructuredTool", item.meta.name)

    logger.info("discover_tools: %d tools adapted", len(tools))
    return tools

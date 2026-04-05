"""Tests for agents.tools.discover_tools — LangChain StructuredTool adapter."""

from __future__ import annotations

from unittest.mock import patch

from legion.plumbing.plugins import DiscoveredTool, tool


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_discovered_tool(
    name: str,
    description: str = "",
    category: str = "test",
    read_only: bool = True,
) -> DiscoveredTool:
    """Build a DiscoveredTool with a real callable and ToolMeta."""

    @tool(
        name=name,
        description=description,
        category=category,
        read_only=read_only,
    )
    def func() -> str:
        return name

    meta = func.__tool_meta__  # type: ignore[attr-defined]
    return DiscoveredTool(func=func, meta=meta, entry_point=f"{name} = mod:{name}")


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@patch("legion.agents.tools.load_tool_callables")
def test_discover_tools_returns_structured_tools(mock_load):
    from langchain_core.tools import StructuredTool

    mock_load.return_value = [
        _make_discovered_tool("tool_a", description="Tool A"),
        _make_discovered_tool("tool_b", description="Tool B"),
    ]

    from legion.agents.tools import discover_tools

    result = discover_tools()

    assert len(result) == 2
    assert all(isinstance(t, StructuredTool) for t in result)
    assert result[0].name == "tool_a"
    assert result[1].name == "tool_b"


@patch("legion.agents.tools.load_tool_callables")
def test_discover_tools_passes_filters(mock_load):
    mock_load.return_value = []

    from legion.agents.tools import discover_tools

    discover_tools(categories=["k8s", "monitoring"], read_only_only=True)

    mock_load.assert_called_once_with(
        categories=["k8s", "monitoring"],
        read_only_only=True,
    )


@patch("legion.agents.tools.load_tool_callables")
def test_discover_tools_empty_list(mock_load):
    mock_load.return_value = []

    from legion.agents.tools import discover_tools

    result = discover_tools()

    assert result == []


@patch("legion.agents.tools.load_tool_callables")
def test_discover_tools_uses_description_fallback(mock_load):
    mock_load.return_value = [
        _make_discovered_tool("empty_desc", description=""),
    ]

    from legion.agents.tools import discover_tools

    result = discover_tools()

    assert len(result) == 1
    assert result[0].description == "Run the empty_desc tool."

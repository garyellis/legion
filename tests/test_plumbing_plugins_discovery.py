"""Tests for plumbing.plugins: load_tool_callables and discover_tool_metadata."""

from __future__ import annotations

import dataclasses
from unittest.mock import MagicMock, patch

from legion.plumbing.plugins import (
    DiscoveredTool,
    ToolMeta,
    discover_tool_metadata,
    load_tool_callables,
    tool,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_entry_point(name: str, func: object) -> MagicMock:
    """Build a mock entry point with .name, .value, and .load()."""
    ep = MagicMock()
    ep.name = name
    ep.value = f"some.module:{name}"
    ep.load.return_value = func
    return ep


def _make_tool_func(
    name: str, category: str = "test", read_only: bool = True
) -> object:
    """Return a function decorated with @tool so it carries __tool_meta__."""

    @tool(name=name, description=f"{name} description", category=category, read_only=read_only)
    def func() -> str:
        return name

    return func


# ---------------------------------------------------------------------------
# load_tool_callables
# ---------------------------------------------------------------------------


@patch("legion.plumbing.plugins.entry_points")
def test_load_tool_callables_returns_discovered_tools(mock_eps):
    func_a = _make_tool_func("alpha", category="k8s")
    func_b = _make_tool_func("beta", category="monitoring")
    mock_eps.return_value = [
        _make_entry_point("alpha", func_a),
        _make_entry_point("beta", func_b),
    ]

    result = load_tool_callables()

    assert len(result) == 2
    assert all(isinstance(dt, DiscoveredTool) for dt in result)
    assert result[0].meta.name == "alpha"
    assert result[0].meta.category == "k8s"
    assert result[1].meta.name == "beta"
    assert result[1].meta.category == "monitoring"


@patch("legion.plumbing.plugins.entry_points")
def test_load_tool_callables_empty_group(mock_eps):
    mock_eps.return_value = []

    result = load_tool_callables()

    assert result == []


@patch("legion.plumbing.plugins.entry_points")
def test_load_tool_callables_skips_broken_entry_point(mock_eps):
    func_good = _make_tool_func("good_tool")
    ep_broken = _make_entry_point("broken", None)
    ep_broken.load.side_effect = ImportError("missing module")

    mock_eps.return_value = [
        ep_broken,
        _make_entry_point("good_tool", func_good),
    ]

    result = load_tool_callables()

    assert len(result) == 1
    assert result[0].meta.name == "good_tool"


@patch("legion.plumbing.plugins.entry_points")
def test_load_tool_callables_skips_missing_meta(mock_eps):
    func_with_meta = _make_tool_func("has_meta")

    def bare_func() -> str:
        return "no meta"

    mock_eps.return_value = [
        _make_entry_point("bare", bare_func),
        _make_entry_point("has_meta", func_with_meta),
    ]

    result = load_tool_callables()

    assert len(result) == 1
    assert result[0].meta.name == "has_meta"


@patch("legion.plumbing.plugins.entry_points")
def test_load_tool_callables_skips_duplicate_names(mock_eps):
    func_first = _make_tool_func("dupe_tool", category="first")
    func_second = _make_tool_func("dupe_tool", category="second")

    mock_eps.return_value = [
        _make_entry_point("ep_first", func_first),
        _make_entry_point("ep_second", func_second),
    ]

    result = load_tool_callables()

    assert len(result) == 1
    assert result[0].meta.category == "first"


@patch("legion.plumbing.plugins.entry_points")
def test_load_tool_callables_filters_by_category(mock_eps):
    func_k8s_1 = _make_tool_func("pods", category="k8s")
    func_k8s_2 = _make_tool_func("nodes", category="k8s")
    func_mon = _make_tool_func("metrics", category="monitoring")

    mock_eps.return_value = [
        _make_entry_point("pods", func_k8s_1),
        _make_entry_point("nodes", func_k8s_2),
        _make_entry_point("metrics", func_mon),
    ]

    result = load_tool_callables(categories=["k8s"])

    assert len(result) == 2
    assert all(dt.meta.category == "k8s" for dt in result)


@patch("legion.plumbing.plugins.entry_points")
def test_load_tool_callables_filters_by_read_only(mock_eps):
    func_ro = _make_tool_func("reader", read_only=True)
    func_rw = _make_tool_func("writer", read_only=False)
    func_ro2 = _make_tool_func("checker", read_only=True)

    mock_eps.return_value = [
        _make_entry_point("reader", func_ro),
        _make_entry_point("writer", func_rw),
        _make_entry_point("checker", func_ro2),
    ]

    result = load_tool_callables(read_only_only=True)

    assert len(result) == 2
    assert all(dt.meta.read_only is True for dt in result)
    names = {dt.meta.name for dt in result}
    assert names == {"reader", "checker"}


# ---------------------------------------------------------------------------
# discover_tool_metadata
# ---------------------------------------------------------------------------


@patch("legion.plumbing.plugins.entry_points")
def test_discover_tool_metadata_returns_toolmeta_list(mock_eps):
    func_a = _make_tool_func("alpha")
    func_b = _make_tool_func("beta")
    mock_eps.return_value = [
        _make_entry_point("alpha", func_a),
        _make_entry_point("beta", func_b),
    ]

    result = discover_tool_metadata()

    assert len(result) == 2
    assert all(isinstance(m, ToolMeta) for m in result)
    # Must NOT be DiscoveredTool instances
    assert not any(isinstance(m, DiscoveredTool) for m in result)


# ---------------------------------------------------------------------------
# DiscoveredTool immutability
# ---------------------------------------------------------------------------


def test_discovered_tool_is_frozen():
    func = _make_tool_func("immutable_tool")
    meta = func.__tool_meta__  # type: ignore[attr-defined]
    dt = DiscoveredTool(func=func, meta=meta, entry_point="x = y:z")  # type: ignore[arg-type]

    try:
        dt.meta = meta  # type: ignore[misc]
        raised = False
    except (dataclasses.FrozenInstanceError, AttributeError):
        raised = True

    assert raised, "DiscoveredTool should be frozen (immutable)"

"""Tests for the plugins CLI command."""

from __future__ import annotations

import json
from unittest.mock import patch

import typer
from typer.testing import CliRunner

from legion.plumbing.plugins import ToolMeta


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

runner = CliRunner()

SAMPLE_TOOLS = [
    ToolMeta(
        name="pod_status",
        description="Get pod status",
        category="k8s",
        read_only=True,
        version="1.0",
    ),
    ToolMeta(
        name="restart_deployment",
        description="Restart a deployment",
        category="k8s",
        read_only=False,
        version="1.2",
    ),
]


def _get_app() -> typer.Typer:
    """Build a fresh Typer app with plugins commands registered."""
    from legion.plumbing.registry import get_registry

    import legion.cli.commands.plugins as _plugins_mod  # noqa: F401
    del _plugins_mod

    app = typer.Typer()
    group_apps: dict[str, typer.Typer] = {}

    for group, name, func in get_registry():
        parts = group.split(".")
        for i, part in enumerate(parts):
            key = ".".join(parts[: i + 1])
            if key not in group_apps:
                group_apps[key] = typer.Typer()
                parent_key = ".".join(parts[:i]) if i > 0 else None
                parent = group_apps[parent_key] if parent_key else app
                parent.add_typer(group_apps[key], name=part)
        group_apps[group].command(name)(func)

    return app


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@patch("legion.cli.commands.plugins.discover_tool_metadata")
def test_plugins_list_table_output(mock_discover):
    mock_discover.return_value = SAMPLE_TOOLS

    app = _get_app()
    result = runner.invoke(app, ["plugins", "list"])

    assert result.exit_code == 0
    assert "pod_status" in result.output
    assert "restart_deployment" in result.output


@patch("legion.cli.commands.plugins.discover_tool_metadata")
def test_plugins_list_json_output(mock_discover):
    mock_discover.return_value = SAMPLE_TOOLS

    app = _get_app()
    result = runner.invoke(app, ["plugins", "list", "--output", "json"])

    assert result.exit_code == 0
    data = json.loads(result.output)
    assert len(data) == 2
    names = {item["name"] for item in data}
    assert names == {"pod_status", "restart_deployment"}
    # Verify structure has expected keys
    for item in data:
        assert "name" in item
        assert "category" in item
        assert "read_only" in item
        assert "version" in item


@patch("legion.cli.commands.plugins.discover_tool_metadata")
def test_plugins_list_empty(mock_discover):
    mock_discover.return_value = []

    app = _get_app()
    result = runner.invoke(app, ["plugins", "list"])

    assert result.exit_code == 0
    assert "No tool plugins installed" in result.output

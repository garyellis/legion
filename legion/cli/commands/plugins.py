"""Plugin discovery commands."""

from __future__ import annotations

from typing import Annotated

import typer

from legion.plumbing.registry import register_command
from legion.cli.views import render_error
from legion.cli.views.plugins import display_plugin_list
from legion.plumbing.plugins import discover_tool_metadata


@register_command("plugins", "list")
def plugins_list(
    output: Annotated[str, typer.Option("--output", "-o", help="Output format: table or json")] = "table",
) -> None:
    """List all installed tool plugins."""
    try:
        tools = discover_tool_metadata()
        display_plugin_list(tools, output=output)
    except Exception as e:
        render_error(str(e))
        raise typer.Exit(1)

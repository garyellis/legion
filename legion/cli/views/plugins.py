"""Rich views for plugin commands."""

from __future__ import annotations

import json

from rich.table import Table

from legion.cli.views.base import console
from legion.plumbing.plugins import ToolMeta


def display_plugin_list(tools: list[ToolMeta], *, output: str = "table") -> None:
    """Display discovered tool plugins."""
    if output == "json":
        print(json.dumps(
            [
                {
                    "name": t.name,
                    "category": t.category,
                    "read_only": t.read_only,
                    "version": t.version,
                    "tags": list(t.tags),
                    "description": t.description,
                }
                for t in tools
            ],
            indent=2,
        ))
        return

    if not tools:
        console.print("[dim]No tool plugins installed.[/dim]")
        return

    table = Table(title="Installed Tool Plugins")
    table.add_column("Name", style="cyan")
    table.add_column("Category", style="green")
    table.add_column("Read Only")
    table.add_column("Version")

    for t in tools:
        table.add_row(
            t.name,
            t.category,
            "Yes" if t.read_only else "No",
            t.version,
        )

    console.print(table)

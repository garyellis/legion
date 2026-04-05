"""Rendering helpers for DB migration commands."""

from __future__ import annotations

from rich.table import Table

from legion.cli.views.base import console, print_message
from legion.plumbing.migrations import MigrationRevision, MigrationStatus


def display_migration_status(status: MigrationStatus, *, output: str) -> None:
    """Render current vs head migration status."""
    if output == "json":
        console.print_json(
            data={
                "current_revision": status.current_revision,
                "head_revision": status.head_revision,
                "is_current": status.is_current,
            }
        )
        return

    table = Table(title="Database Schema Status")
    table.add_column("Current")
    table.add_column("Head")
    table.add_column("Status")
    table.add_row(
        status.current_revision or "unversioned",
        status.head_revision,
        "current" if status.is_current else "behind",
    )
    console.print(table)


def display_migration_history(history: list[MigrationRevision], *, output: str) -> None:
    """Render Alembic revision history."""
    if output == "json":
        console.print_json(
            data=[
                {
                    "revision": entry.revision,
                    "down_revision": entry.down_revision,
                    "message": entry.message,
                }
                for entry in history
            ]
        )
        return

    table = Table(title="Migration History")
    table.add_column("Revision")
    table.add_column("Down Revision")
    table.add_column("Message")
    for entry in history:
        down_revision = entry.down_revision
        if isinstance(down_revision, tuple):
            down_text = ", ".join(down_revision)
        else:
            down_text = down_revision or "base"
        table.add_row(entry.revision, down_text, entry.message or "")
    console.print(table)


def display_upgrade_success(status: MigrationStatus) -> None:
    """Render a successful migration completion message."""
    print_message(
        f"Database upgraded to {status.head_revision}",
        style="bold green",
    )

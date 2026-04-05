"""Tests for the operator-facing DB CLI commands."""

from __future__ import annotations

from types import SimpleNamespace

import pytest
import typer
from typer.testing import CliRunner

from legion.plumbing.migrations import MigrationStatus


runner = CliRunner()


def _build_app() -> typer.Typer:
    """Build a fresh Typer app with the CLI registry loaded."""
    from legion.plumbing.registry import get_registry

    import legion.cli.commands.db  # noqa: F401

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


def test_db_group_registers_operator_commands() -> None:
    from legion.plumbing.registry import get_registry

    import legion.cli.commands.db  # noqa: F401

    commands = {
        name for group, name, _ in get_registry()
        if group == "db"
    }

    assert commands == {"current", "history", "upgrade"}


def test_db_history_does_not_load_runtime_database_config(monkeypatch: pytest.MonkeyPatch) -> None:
    import legion.cli.commands.db as db_commands

    monkeypatch.setattr(
        db_commands,
        "_create_db_engine",
        lambda db_url: (_ for _ in ()).throw(AssertionError("runtime DB config should not be loaded")),
    )
    monkeypatch.setattr(
        db_commands,
        "get_migration_history",
        lambda: [SimpleNamespace(revision="rev-1", down_revision=None, message="baseline")],
    )
    monkeypatch.setattr(db_commands, "display_migration_history", lambda history, output: None)

    result = runner.invoke(_build_app(), ["db", "history"])

    assert result.exit_code == 0


def test_db_current_loads_runtime_database_config_once_and_reports_status(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import legion.cli.commands.db as db_commands

    build_calls: list[object] = []
    display_calls: list[MigrationStatus] = []
    dummy_engine = object()

    monkeypatch.setattr(
        db_commands,
        "_create_db_engine",
        lambda db_url: build_calls.append(object()) or dummy_engine,
    )
    monkeypatch.setattr(
        db_commands,
        "get_migration_status",
        lambda engine: MigrationStatus(current_revision="rev-old", head_revision="rev-head"),
    )
    monkeypatch.setattr(
        db_commands,
        "display_migration_status",
        lambda status, output: display_calls.append(status),
    )

    result = runner.invoke(_build_app(), ["db", "current"])

    assert result.exit_code == 1
    assert len(build_calls) == 1
    assert display_calls == [MigrationStatus(current_revision="rev-old", head_revision="rev-head")]


def test_db_upgrade_loads_runtime_database_config_once_and_calls_upgrade_helper(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import legion.cli.commands.db as db_commands

    build_calls: list[object] = []
    upgrade_calls: list[object] = []
    display_calls: list[MigrationStatus] = []
    dummy_engine = object()

    monkeypatch.setattr(
        db_commands,
        "_create_db_engine",
        lambda db_url: build_calls.append(object()) or dummy_engine,
    )
    monkeypatch.setattr(
        db_commands,
        "upgrade_database_schema",
        lambda engine: upgrade_calls.append(engine),
    )
    monkeypatch.setattr(
        db_commands,
        "get_migration_status",
        lambda engine: MigrationStatus(current_revision="rev-head", head_revision="rev-head"),
    )
    monkeypatch.setattr(
        db_commands,
        "display_upgrade_success",
        lambda status: display_calls.append(status),
    )

    result = runner.invoke(_build_app(), ["db", "upgrade"])

    assert result.exit_code == 0
    assert len(build_calls) == 1
    assert upgrade_calls == [dummy_engine]
    assert display_calls == [MigrationStatus(current_revision="rev-head", head_revision="rev-head")]

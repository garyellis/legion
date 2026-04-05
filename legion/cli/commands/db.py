"""Operator-facing database migration commands."""

from __future__ import annotations

from typing import Annotated

import typer

from legion.cli.views import render_error
from legion.cli.views.db import (
    display_migration_history,
    display_migration_status,
    display_upgrade_success,
)
from legion.plumbing.config.db_admin import DatabaseAdminConfig
from legion.plumbing.database import create_engine
from legion.plumbing.exceptions import DatabaseSchemaError
from legion.plumbing.migrations import (
    get_migration_history,
    get_migration_status,
    upgrade_database_schema,
)
from legion.plumbing.registry import register_command

_OutputOpt = Annotated[str, typer.Option("--output", "-o", help="Output format: table or json")]
_DbUrlOpt = Annotated[
    str | None,
    typer.Option(
        "--db-url",
        envvar="LEGION_DB_URL",
        help="Direct database URL for operator migration commands",
    ),
]


def _create_db_engine(db_url: str | None):
    config = DatabaseAdminConfig()
    resolved_url = db_url if db_url is not None else config.url
    return create_engine(
        resolved_url,
        echo=config.echo,
        pool_pre_ping=config.pool_pre_ping,
    )


def _handle_db_error(error: Exception) -> None:
    if isinstance(error, DatabaseSchemaError):
        render_error(error.message)
        return
    render_error(str(error))


@register_command("db", "current")
def db_current(
    output: _OutputOpt = "table",
    db_url: _DbUrlOpt = None,
) -> None:
    """Show the current and head Alembic revisions for the target database."""
    try:
        engine = _create_db_engine(db_url)
        status = get_migration_status(engine)
        display_migration_status(status, output=output)
        if not status.is_current:
            raise typer.Exit(1)
    except typer.Exit:
        raise
    except Exception as error:
        _handle_db_error(error)
        raise typer.Exit(1)


@register_command("db", "history")
def db_history(
    output: _OutputOpt = "table",
) -> None:
    """Show the Alembic revision history shipped with this Legion build."""
    try:
        display_migration_history(get_migration_history(), output=output)
    except Exception as error:
        _handle_db_error(error)
        raise typer.Exit(1)


@register_command("db", "upgrade")
def db_upgrade(
    db_url: _DbUrlOpt = None,
) -> None:
    """Upgrade the target database to the repo Alembic head revision."""
    try:
        engine = _create_db_engine(db_url)
        upgrade_database_schema(engine)
        display_upgrade_success(get_migration_status(engine))
    except Exception as error:
        _handle_db_error(error)
        raise typer.Exit(1)

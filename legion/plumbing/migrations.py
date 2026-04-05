"""Alembic helpers for explicit migration lifecycle operations."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from alembic import command
from alembic.config import Config
from alembic.runtime.migration import MigrationContext
from alembic.script import ScriptDirectory
from sqlalchemy import Engine

from legion.plumbing.exceptions import DatabaseSchemaOutOfDateError


@dataclass(frozen=True)
class MigrationStatus:
    current_revision: str | None
    head_revision: str

    @property
    def is_current(self) -> bool:
        return self.current_revision == self.head_revision


@dataclass(frozen=True)
class MigrationRevision:
    revision: str
    down_revision: str | tuple[str, ...] | None
    message: str | None


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _alembic_ini_path() -> Path:
    return _repo_root() / "alembic.ini"


def _script_location() -> Path:
    return _repo_root() / "alembic"


def _build_config(engine: Engine | None = None) -> Config:
    config = Config(str(_alembic_ini_path()))
    config.set_main_option("script_location", str(_script_location()))
    if engine is not None:
        config.set_main_option("sqlalchemy.url", str(engine.url))
    config.attributes["configure_logger"] = False
    return config


def _script_directory() -> ScriptDirectory:
    return ScriptDirectory.from_config(_build_config())


def get_head_revision() -> str:
    """Return the current Alembic head revision for the repo."""
    head = _script_directory().get_current_head()
    if head is None:  # pragma: no cover - defensive
        raise RuntimeError("Alembic head revision is not defined")
    return head


def get_current_revision(engine: Engine) -> str | None:
    """Return the current database revision, if any."""
    with engine.connect() as connection:
        context = MigrationContext.configure(connection)
        return context.get_current_revision()


def get_migration_status(engine: Engine) -> MigrationStatus:
    """Return current vs head revision status for a database."""
    return MigrationStatus(
        current_revision=get_current_revision(engine),
        head_revision=get_head_revision(),
    )


def get_migration_history() -> list[MigrationRevision]:
    """Return revision history from head back to base."""
    revisions: list[MigrationRevision] = []
    for revision in _script_directory().walk_revisions():
        down_revision = revision.down_revision
        if isinstance(down_revision, list):
            normalized_down_revision: str | tuple[str, ...] | None = tuple(down_revision)
        else:
            normalized_down_revision = down_revision
        revisions.append(
            MigrationRevision(
                revision=revision.revision,
                down_revision=normalized_down_revision,
                message=revision.doc,
            ),
        )
    return revisions


def upgrade_database_schema(engine: Engine, revision: str = "head") -> None:
    """Upgrade the target database to the requested Alembic revision."""
    config = _build_config(engine)
    with engine.begin() as connection:
        config.attributes["connection"] = connection
        command.upgrade(config, revision)


def validate_database_schema_current(engine: Engine) -> None:
    """Raise when the target database is not already at the repo head."""
    status = get_migration_status(engine)
    if status.is_current:
        return

    current = status.current_revision or "unversioned"
    raise DatabaseSchemaOutOfDateError(
        "Database schema is not at the expected revision. "
        f"Current={current}, head={status.head_revision}. "
        "Run 'legion-cli db upgrade' before starting Legion surfaces.",
    )


def validate_database_schema(engine: Engine) -> None:
    """Backward-compatible alias for validating the current revision."""
    validate_database_schema_current(engine)


def ensure_database_schema(engine: Engine) -> None:
    """Backward-compatible alias for upgrading the database schema."""
    upgrade_database_schema(engine)

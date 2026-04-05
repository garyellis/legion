"""Tests for shared database and migration plumbing."""

from __future__ import annotations

import importlib.util
import io
import json
import sqlite3
import subprocess
import sys
from pathlib import Path
from textwrap import dedent

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import inspect
from sqlalchemy import text

from legion.plumbing.database import Base, create_all, create_engine
from legion.plumbing.exceptions import DatabaseSchemaOutOfDateError
from legion.plumbing.migrations import get_head_revision
from legion.plumbing.migrations import get_migration_history
from legion.plumbing.migrations import get_migration_status
from legion.plumbing.migrations import upgrade_database_schema
from legion.plumbing.migrations import validate_database_schema_current
from legion.orm_registry import register_all_models
from legion.services.fleet_repository import OrganizationRow


def test_create_all_keeps_in_memory_sqlite_on_direct_metadata() -> None:
    register_all_models()
    engine = create_engine("sqlite:///:memory:")

    create_all(engine)

    tables = set(inspect(engine).get_table_names())
    assert "alembic_version" not in tables
    assert "organizations" in tables
    assert "jobs" in tables
    assert "messages" in tables


def test_upgrade_database_schema_adopts_unmanaged_persistent_sqlite_db(
    tmp_path: Path,
) -> None:
    engine = create_engine(f"sqlite:///{tmp_path / 'legion.db'}")
    OrganizationRow.__table__.create(engine)

    upgrade_database_schema(engine)

    tables = set(inspect(engine).get_table_names())
    expected = {
        "agent_groups",
        "agent_session_tokens",
        "agents",
        "channel_mappings",
        "filter_rules",
        "incidents",
        "jobs",
        "messages",
        "organizations",
        "projects",
        "prompt_configs",
        "sessions",
        "slack_incident_state",
    }
    assert expected.issubset(tables)

    with engine.connect() as connection:
        version = connection.exec_driver_sql(
            "select version_num from alembic_version"
        ).scalar_one()

    assert version == get_head_revision()
    validate_database_schema_current(engine)
    assert get_migration_status(engine).is_current


def test_validate_database_schema_rejects_unversioned_database(tmp_path: Path) -> None:
    engine = create_engine(f"sqlite:///{tmp_path / 'fresh.db'}")

    with pytest.raises(DatabaseSchemaOutOfDateError, match="not at the expected revision"):
        validate_database_schema_current(engine)


def test_upgrade_database_schema_backfills_legacy_jobs_session_id_idempotently(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "legacy-jobs.db"
    with sqlite3.connect(db_path) as connection:
        connection.executescript(
            """
            CREATE TABLE jobs (
                id TEXT PRIMARY KEY,
                org_id TEXT NOT NULL,
                agent_group_id TEXT NOT NULL,
                agent_id TEXT NULL,
                type TEXT NOT NULL,
                status TEXT NOT NULL,
                payload TEXT NOT NULL,
                result TEXT NULL,
                error TEXT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );

            INSERT INTO jobs (
                id, org_id, agent_group_id, agent_id, type, status, payload,
                result, error, created_at, updated_at
            ) VALUES (
                'job-1', 'org-1', 'ag-1', 'agent-1', 'TRIAGE', 'COMPLETED', 'alert',
                NULL, NULL,
                '2026-04-04T12:00:00+00:00', '2026-04-04T12:05:00+00:00'
            );
            """
        )
        connection.commit()

    engine = create_engine(f"sqlite:///{db_path}")
    upgrade_database_schema(engine)
    upgrade_database_schema(engine)

    columns = {column["name"] for column in inspect(engine).get_columns("jobs")}
    assert "session_id" in columns

    with engine.connect() as connection:
        job_row = connection.execute(
            text("SELECT session_id, required_capabilities FROM jobs WHERE id = 'job-1'")
        ).mappings().one()
        session_row = connection.execute(
            text(
                """
                SELECT id, org_id, agent_group_id, agent_id, status
                FROM sessions
                WHERE id = :session_id
                """
            ),
            {"session_id": job_row["session_id"]},
        ).mappings().one()
        session_count = connection.execute(text("SELECT count(*) FROM sessions")).scalar_one()

    assert job_row["session_id"] == "legacy-job-session-job-1"
    assert job_row["required_capabilities"] == "[]"
    assert session_count == 1
    assert session_row == {
        "id": "legacy-job-session-job-1",
        "org_id": "org-1",
        "agent_group_id": "ag-1",
        "agent_id": "agent-1",
        "status": "CLOSED",
    }
    validate_database_schema_current(engine)


def test_upgrade_database_schema_rejects_unsupported_legacy_shape(tmp_path: Path) -> None:
    db_path = tmp_path / "unsupported.db"
    with sqlite3.connect(db_path) as connection:
        connection.executescript(
            """
            CREATE TABLE sessions (
                id TEXT PRIMARY KEY,
                org_id TEXT NOT NULL,
                agent_group_id TEXT NOT NULL,
                status TEXT NOT NULL,
                created_at TEXT NOT NULL
            );
            """
        )
        connection.commit()

    engine = create_engine(f"sqlite:///{db_path}")
    with pytest.raises(RuntimeError, match="Unsupported legacy database shape for sessions"):
        upgrade_database_schema(engine)


def test_alembic_env_registers_shared_metadata_in_standalone_mode() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    env_path = repo_root / "alembic" / "env.py"
    code = dedent(
        f"""
        import importlib.util
        import json
        from contextlib import contextmanager
        from pathlib import Path
        from types import SimpleNamespace

        import alembic

        class FakeContext:
            def __init__(self) -> None:
                self.config = SimpleNamespace(
                    config_file_name=None,
                    attributes={{"connection": SimpleNamespace(dialect=SimpleNamespace(name="sqlite"))}},
                    config_ini_section="alembic",
                )

            def is_offline_mode(self) -> bool:
                return False

            def configure(self, **kwargs: object) -> None:
                self.configured = kwargs

            @contextmanager
            def begin_transaction(self):
                yield

            def run_migrations(self) -> None:
                return None

        alembic.context = FakeContext()
        spec = importlib.util.spec_from_file_location("legion_alembic_env_test", Path({str(env_path)!r}))
        assert spec is not None and spec.loader is not None
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        print(json.dumps(sorted(module.target_metadata.tables)))
        """
    )

    result = subprocess.run(
        [sys.executable, "-c", code],
        cwd=repo_root,
        check=True,
        capture_output=True,
        text=True,
    )
    tables = set(json.loads(result.stdout.strip()))
    expected = {
        "agent_groups",
        "agent_session_tokens",
        "agents",
        "channel_mappings",
        "filter_rules",
        "incidents",
        "jobs",
        "messages",
        "organizations",
        "projects",
        "prompt_configs",
        "sessions",
        "slack_incident_state",
    }
    assert expected.issubset(tables)


def test_phase_1_baseline_downgrade_is_unsupported() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    baseline_path = repo_root / "alembic" / "versions" / "20260404_01_phase_1_baseline.py"
    spec = importlib.util.spec_from_file_location("phase_1_baseline_test", baseline_path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    with pytest.raises(RuntimeError, match="Downgrading the baseline migration is unsupported"):
        module.downgrade()


def test_get_migration_history_includes_head_revision() -> None:
    history = get_migration_history()
    assert history
    assert history[0].revision == get_head_revision()


def test_alembic_offline_upgrade_supports_postgres_dialect() -> None:
    config = Config("alembic.ini")
    config.set_main_option("script_location", "alembic")
    config.set_main_option("sqlalchemy.url", "postgresql://user:pass@localhost/legion")
    config.output_buffer = io.StringIO()
    config.attributes["configure_logger"] = False

    command.upgrade(config, "head", sql=True)

    sql = config.output_buffer.getvalue()
    assert "CREATE TABLE alembic_version" in sql
    assert "CREATE TABLE organizations" in sql


def test_shared_metadata_includes_all_persistent_tables() -> None:
    expected = {
        "agent_groups",
        "agent_session_tokens",
        "agents",
        "channel_mappings",
        "filter_rules",
        "incidents",
        "jobs",
        "messages",
        "organizations",
        "projects",
        "prompt_configs",
        "sessions",
        "slack_incident_state",
    }

    assert expected.issubset(set(Base.metadata.tables))

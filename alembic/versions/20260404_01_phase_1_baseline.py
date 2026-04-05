"""Phase 1 Alembic baseline.

Create the full current schema for fresh databases and adopt unmanaged legacy
databases that already use current table names but predate migration support.
"""

from __future__ import annotations

from collections.abc import Iterable
from datetime import datetime

from alembic import context
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "20260404_01"
down_revision = None
branch_labels = None
depends_on = None

_CURRENT_COLUMNS: dict[str, set[str]] = {
    "organizations": {"id", "name", "slug", "created_at", "updated_at"},
    "projects": {"id", "org_id", "name", "slug", "created_at", "updated_at"},
    "agent_groups": {
        "id", "org_id", "project_id", "name", "slug", "environment", "provider",
        "execution_mode", "registration_token_hash", "registration_token_rotated_at",
        "created_at", "updated_at",
    },
    "agents": {
        "id", "agent_group_id", "name", "status", "current_job_id", "capabilities",
        "last_heartbeat", "created_at", "updated_at",
    },
    "channel_mappings": {
        "id", "org_id", "channel_id", "agent_group_id", "mode", "created_at", "updated_at",
    },
    "filter_rules": {
        "id", "channel_mapping_id", "pattern", "action", "priority", "created_at", "updated_at",
    },
    "prompt_configs": {
        "id", "agent_group_id", "system_prompt", "stack_manifest", "persona", "created_at", "updated_at",
    },
    "sessions": {
        "id", "org_id", "agent_group_id", "agent_id", "slack_channel_id", "slack_thread_ts",
        "status", "created_at", "last_activity",
    },
    "jobs": {
        "id", "org_id", "agent_group_id", "session_id", "agent_id", "event_id", "type",
        "status", "payload", "result", "error", "incident_id", "required_capabilities",
        "created_at", "updated_at", "dispatched_at", "completed_at",
    },
    "messages": {
        "id", "org_id", "session_id", "author_id", "author_type", "message_type",
        "content", "job_id", "metadata", "created_at",
    },
    "agent_session_tokens": {"id", "agent_id", "token_hash", "expires_at", "created_at"},
    "incidents": {
        "id", "title", "description", "severity", "status", "commander_id",
        "created_at", "updated_at", "resolved_at", "duration_seconds", "check_in_interval",
    },
    "slack_incident_state": {"incident_id", "channel_id", "dashboard_message_ts"},
}

_SUPPORTED_MISSING_COLUMNS: dict[str, set[str]] = {
    "jobs": {
        "session_id", "event_id", "result", "error", "incident_id",
        "required_capabilities", "dispatched_at", "completed_at",
    },
    "messages": {"job_id", "metadata"},
}


def _dialect_name() -> str:
    return op.get_bind().dialect.name


def _inspector() -> sa.Inspector:
    return sa.inspect(op.get_bind())


def _table_names() -> set[str]:
    return set(_inspector().get_table_names())


def _column_names(table_name: str) -> set[str]:
    return {column["name"] for column in _inspector().get_columns(table_name)}


def _ensure_supported_legacy_shape(existing_tables: set[str]) -> None:
    for table_name in existing_tables & set(_CURRENT_COLUMNS):
        current_columns = _column_names(table_name)
        expected_columns = _CURRENT_COLUMNS[table_name]
        allowed_missing = _SUPPORTED_MISSING_COLUMNS.get(table_name, set())
        missing = expected_columns - current_columns
        unsupported_missing = missing - allowed_missing
        extra = current_columns - expected_columns
        if unsupported_missing or extra:
            problems: list[str] = []
            if unsupported_missing:
                problems.append(f"missing columns: {', '.join(sorted(unsupported_missing))}")
            if extra:
                problems.append(f"unexpected columns: {', '.join(sorted(extra))}")
            joined = "; ".join(problems)
            raise RuntimeError(
                f"Unsupported legacy database shape for {table_name}: {joined}. "
                "Only explicitly supported unmanaged legacy shapes may be adopted.",
            )


def _create_organizations_table() -> None:
    op.create_table(
        "organizations",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("slug", sa.String(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("slug"),
    )


def _create_projects_table() -> None:
    op.create_table(
        "projects",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("org_id", sa.String(), nullable=False),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("slug", sa.String(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["org_id"], ["organizations.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("slug"),
    )


def _create_agent_groups_table() -> None:
    op.create_table(
        "agent_groups",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("org_id", sa.String(), nullable=False),
        sa.Column("project_id", sa.String(), nullable=False),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("slug", sa.String(), nullable=False),
        sa.Column("environment", sa.String(), nullable=False),
        sa.Column("provider", sa.String(), nullable=False),
        sa.Column("execution_mode", sa.String(), nullable=False),
        sa.Column("registration_token_hash", sa.String(), nullable=True),
        sa.Column("registration_token_rotated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["org_id"], ["organizations.id"]),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"]),
        sa.PrimaryKeyConstraint("id"),
    )


def _create_agents_table() -> None:
    op.create_table(
        "agents",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("agent_group_id", sa.String(), nullable=False),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("current_job_id", sa.String(), nullable=True),
        sa.Column("capabilities", sa.Text(), nullable=False),
        sa.Column("last_heartbeat", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["agent_group_id"], ["agent_groups.id"]),
        sa.PrimaryKeyConstraint("id"),
    )


def _create_channel_mappings_table() -> None:
    op.create_table(
        "channel_mappings",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("org_id", sa.String(), nullable=False),
        sa.Column("channel_id", sa.String(), nullable=False),
        sa.Column("agent_group_id", sa.String(), nullable=False),
        sa.Column("mode", sa.String(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["agent_group_id"], ["agent_groups.id"]),
        sa.ForeignKeyConstraint(["org_id"], ["organizations.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("channel_id"),
    )


def _create_filter_rules_table() -> None:
    op.create_table(
        "filter_rules",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("channel_mapping_id", sa.String(), nullable=False),
        sa.Column("pattern", sa.String(), nullable=False),
        sa.Column("action", sa.String(), nullable=False),
        sa.Column("priority", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["channel_mapping_id"], ["channel_mappings.id"]),
        sa.PrimaryKeyConstraint("id"),
    )


def _create_prompt_configs_table() -> None:
    op.create_table(
        "prompt_configs",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("agent_group_id", sa.String(), nullable=False),
        sa.Column("system_prompt", sa.Text(), nullable=False),
        sa.Column("stack_manifest", sa.Text(), nullable=False),
        sa.Column("persona", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["agent_group_id"], ["agent_groups.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("agent_group_id"),
    )


def _create_sessions_table() -> None:
    op.create_table(
        "sessions",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("org_id", sa.String(), nullable=False),
        sa.Column("agent_group_id", sa.String(), nullable=False),
        sa.Column("agent_id", sa.String(), nullable=True),
        sa.Column("slack_channel_id", sa.String(), nullable=True),
        sa.Column("slack_thread_ts", sa.String(), nullable=True),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_activity", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )


def _create_jobs_table() -> None:
    op.create_table(
        "jobs",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("org_id", sa.String(), nullable=False),
        sa.Column("agent_group_id", sa.String(), nullable=False),
        sa.Column("session_id", sa.String(), nullable=False),
        sa.Column("agent_id", sa.String(), nullable=True),
        sa.Column("event_id", sa.String(), nullable=True),
        sa.Column("type", sa.String(), nullable=False),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("payload", sa.Text(), nullable=False),
        sa.Column("result", sa.Text(), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("incident_id", sa.String(), nullable=True),
        sa.Column("required_capabilities", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("dispatched_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )


def _create_messages_table() -> None:
    op.create_table(
        "messages",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("org_id", sa.String(), nullable=False),
        sa.Column("session_id", sa.String(), nullable=False),
        sa.Column("author_id", sa.String(), nullable=False),
        sa.Column("author_type", sa.String(), nullable=False),
        sa.Column("message_type", sa.String(), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("job_id", sa.String(), nullable=True),
        sa.Column("metadata", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )


def _create_agent_session_tokens_table() -> None:
    op.create_table(
        "agent_session_tokens",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("agent_id", sa.String(), nullable=False),
        sa.Column("token_hash", sa.String(), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("token_hash"),
    )


def _create_incidents_table() -> None:
    op.create_table(
        "incidents",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("title", sa.String(), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("severity", sa.String(), nullable=False),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("commander_id", sa.String(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("duration_seconds", sa.Integer(), nullable=True),
        sa.Column("check_in_interval", sa.Integer(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )


def _create_slack_incident_state_table() -> None:
    op.create_table(
        "slack_incident_state",
        sa.Column("incident_id", sa.String(), nullable=False),
        sa.Column("channel_id", sa.String(), nullable=False),
        sa.Column("dashboard_message_ts", sa.String(), nullable=True),
        sa.PrimaryKeyConstraint("incident_id"),
    )
    op.create_index(
        "ix_slack_incident_state_channel_id",
        "slack_incident_state",
        ["channel_id"],
        unique=True,
    )


def _ensure_missing_tables(existing_tables: set[str]) -> None:
    creators = [
        ("organizations", _create_organizations_table),
        ("projects", _create_projects_table),
        ("agent_groups", _create_agent_groups_table),
        ("agents", _create_agents_table),
        ("channel_mappings", _create_channel_mappings_table),
        ("filter_rules", _create_filter_rules_table),
        ("prompt_configs", _create_prompt_configs_table),
        ("sessions", _create_sessions_table),
        ("jobs", _create_jobs_table),
        ("messages", _create_messages_table),
        ("agent_session_tokens", _create_agent_session_tokens_table),
        ("incidents", _create_incidents_table),
        ("slack_incident_state", _create_slack_incident_state_table),
    ]
    for table_name, creator in creators:
        if table_name not in existing_tables:
            creator()
            existing_tables.add(table_name)


def _select_all_jobs_without_session_id() -> Iterable[sa.Row]:
    return op.get_bind().execute(
        sa.text(
            """
            SELECT id, org_id, agent_group_id, agent_id, status, created_at,
                   updated_at, dispatched_at, completed_at
            FROM jobs
            WHERE session_id IS NULL
            ORDER BY created_at, id
            """
        )
    )


def _normalize_dt(value: object) -> datetime | None:
    if isinstance(value, datetime):
        return value
    if isinstance(value, str):
        try:
            return datetime.fromisoformat(value)
        except ValueError:
            return None
    return None


def _session_status_for_job(job_status: str | None) -> str:
    if job_status in {"COMPLETED", "FAILED", "CANCELLED"}:
        return "CLOSED"
    return "ACTIVE"


def _last_activity_for_job(row: sa.Row) -> datetime | None:
    mapping = row._mapping
    for key in ("completed_at", "updated_at", "dispatched_at", "created_at"):
        value = _normalize_dt(mapping[key])
        if value is not None:
            return value
    return None


def _backfill_sessions_for_jobs() -> None:
    bind = op.get_bind()
    rows = list(_select_all_jobs_without_session_id())
    for row in rows:
        data = row._mapping
        job_id = data["id"]
        session_id = f"legacy-job-session-{job_id}"
        expected_session = {
            "id": session_id,
            "org_id": data["org_id"],
            "agent_group_id": data["agent_group_id"],
            "agent_id": data["agent_id"],
            "status": _session_status_for_job(data["status"]),
            "created_at": _normalize_dt(data["created_at"]),
            "last_activity": _last_activity_for_job(row),
        }
        existing_session = bind.execute(
            sa.text(
                """
                SELECT id, org_id, agent_group_id, agent_id, status
                FROM sessions
                WHERE id = :id
                """
            ),
            {"id": session_id},
        ).mappings().first()
        if existing_session is None:
            bind.execute(
                sa.text(
                    """
                    INSERT INTO sessions (
                        id, org_id, agent_group_id, agent_id,
                        slack_channel_id, slack_thread_ts, status,
                        created_at, last_activity
                    ) VALUES (
                        :id, :org_id, :agent_group_id, :agent_id,
                        NULL, NULL, :status, :created_at, :last_activity
                    )
                    """
                ),
                expected_session,
            )
        else:
            if (
                existing_session["org_id"] != expected_session["org_id"]
                or existing_session["agent_group_id"] != expected_session["agent_group_id"]
            ):
                raise RuntimeError(
                    "Legacy session backfill collided with an existing session id. "
                    f"Refusing to adopt job {job_id} into session {session_id}.",
                )
        bind.execute(
            sa.text(
                "UPDATE jobs SET session_id = :session_id "
                "WHERE id = :job_id AND session_id IS NULL",
            ),
            {"session_id": session_id, "job_id": job_id},
        )


def _ensure_jobs_shape() -> None:
    columns = _column_names("jobs")
    session_id_added = False
    required_capabilities_added = False
    required_columns = {
        "id",
        "org_id",
        "agent_group_id",
        "type",
        "status",
        "payload",
        "created_at",
        "updated_at",
    }
    missing_required = required_columns - columns
    if missing_required:
        missing_names = ", ".join(sorted(missing_required))
        raise RuntimeError(
            "Unsupported legacy jobs table shape. "
            f"Missing columns: {missing_names}.",
        )

    if "session_id" not in columns:
        op.add_column("jobs", sa.Column("session_id", sa.String(), nullable=True))
        columns.add("session_id")
        session_id_added = True

    if "event_id" not in columns:
        op.add_column("jobs", sa.Column("event_id", sa.String(), nullable=True))
    if "result" not in columns:
        op.add_column("jobs", sa.Column("result", sa.Text(), nullable=True))
    if "error" not in columns:
        op.add_column("jobs", sa.Column("error", sa.Text(), nullable=True))
    if "incident_id" not in columns:
        op.add_column("jobs", sa.Column("incident_id", sa.String(), nullable=True))
    if "required_capabilities" not in columns:
        op.add_column(
            "jobs",
            sa.Column("required_capabilities", sa.Text(), nullable=True),
        )
        op.execute(sa.text("UPDATE jobs SET required_capabilities = '[]' WHERE required_capabilities IS NULL"))
        required_capabilities_added = True
    if "dispatched_at" not in columns:
        op.add_column("jobs", sa.Column("dispatched_at", sa.DateTime(timezone=True), nullable=True))
    if "completed_at" not in columns:
        op.add_column("jobs", sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True))

    _backfill_sessions_for_jobs()

    dialect = _dialect_name()
    if session_id_added or required_capabilities_added:
        if dialect == "sqlite":
            with op.batch_alter_table("jobs") as batch_op:
                if session_id_added:
                    batch_op.alter_column("session_id", existing_type=sa.String(), nullable=False)
                if required_capabilities_added:
                    batch_op.alter_column(
                        "required_capabilities",
                        existing_type=sa.Text(),
                        nullable=False,
                    )
        else:
            if session_id_added:
                op.alter_column("jobs", "session_id", existing_type=sa.String(), nullable=False)
            if required_capabilities_added:
                op.alter_column(
                    "jobs",
                    "required_capabilities",
                    existing_type=sa.Text(),
                    nullable=False,
                )


def _ensure_messages_shape() -> None:
    columns = _column_names("messages")
    metadata_added = False
    if "metadata" not in columns:
        op.add_column("messages", sa.Column("metadata", sa.Text(), nullable=True))
        op.execute(sa.text("UPDATE messages SET metadata = '{}' WHERE metadata IS NULL"))
        metadata_added = True

    if "job_id" not in columns:
        op.add_column("messages", sa.Column("job_id", sa.String(), nullable=True))

    if not metadata_added:
        return

    if _dialect_name() == "sqlite":
        with op.batch_alter_table("messages") as batch_op:
            batch_op.alter_column("metadata", existing_type=sa.Text(), nullable=False)
    else:
        op.alter_column("messages", "metadata", existing_type=sa.Text(), nullable=False)


def _ensure_agent_session_tokens_shape() -> None:
    columns = _column_names("agent_session_tokens")
    required_columns = {"id", "agent_id", "token_hash", "expires_at", "created_at"}
    missing = required_columns - columns
    if missing:
        missing_names = ", ".join(sorted(missing))
        raise RuntimeError(
            "Unsupported legacy agent_session_tokens table shape. "
            f"Missing columns: {missing_names}.",
        )


def _ensure_slack_incident_state_shape() -> None:
    columns = _column_names("slack_incident_state")
    required_columns = {"incident_id", "channel_id", "dashboard_message_ts"}
    missing = required_columns - columns
    if missing:
        missing_names = ", ".join(sorted(missing))
        raise RuntimeError(
            "Unsupported legacy slack_incident_state table shape. "
            f"Missing columns: {missing_names}.",
        )

    indexes = {index["name"] for index in _inspector().get_indexes("slack_incident_state")}
    if "ix_slack_incident_state_channel_id" not in indexes:
        op.create_index(
            "ix_slack_incident_state_channel_id",
            "slack_incident_state",
            ["channel_id"],
            unique=True,
        )


def upgrade() -> None:
    if context.is_offline_mode():
        _ensure_missing_tables(set())
        return

    existing_tables = _table_names()
    _ensure_supported_legacy_shape(existing_tables)
    _ensure_missing_tables(existing_tables)

    if "jobs" in existing_tables:
        _ensure_jobs_shape()
    if "messages" in existing_tables:
        _ensure_messages_shape()
    if "agent_session_tokens" in existing_tables:
        _ensure_agent_session_tokens_shape()
    if "slack_incident_state" in existing_tables:
        _ensure_slack_incident_state_shape()


def downgrade() -> None:
    raise RuntimeError(
        "Downgrading the baseline migration is unsupported. "
        "Restore from backup instead of reversing adopted production schema.",
    )

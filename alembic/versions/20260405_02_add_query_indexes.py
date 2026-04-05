"""Add composite query indexes for audit_events and messages.

Covers the primary read patterns: job-scoped, session-scoped, and
org-scoped queries ordered by created_at.
"""

from __future__ import annotations

from alembic import op

# revision identifiers, used by Alembic.
revision = "20260405_02"
down_revision = "20260405_01"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # audit_events — job-scoped queries (most common in agent execution)
    op.create_index("ix_audit_events_job_id_created_at", "audit_events", ["job_id", "created_at", "id"])

    # audit_events — session-scoped queries (session timeline views)
    op.create_index("ix_audit_events_session_id_created_at", "audit_events", ["session_id", "created_at", "id"])

    # audit_events — org-scoped queries (compliance dashboards, admin views)
    op.create_index("ix_audit_events_org_id_created_at", "audit_events", ["org_id", "created_at", "id"])

    # messages — session-scoped queries
    op.create_index("ix_messages_session_id_created_at", "messages", ["session_id", "created_at", "id"])

    # messages — job-scoped queries
    op.create_index("ix_messages_job_id_created_at", "messages", ["job_id", "created_at", "id"])

    # messages — org-scoped queries
    op.create_index("ix_messages_org_id_created_at", "messages", ["org_id", "created_at", "id"])


def _safe_drop_index(name: str, table: str) -> None:
    try:
        op.drop_index(name, table_name=table)
    except Exception:
        pass  # Index may not exist


def downgrade() -> None:
    _safe_drop_index("ix_messages_org_id_created_at", "messages")
    _safe_drop_index("ix_messages_job_id_created_at", "messages")
    _safe_drop_index("ix_messages_session_id_created_at", "messages")
    _safe_drop_index("ix_audit_events_org_id_created_at", "audit_events")
    _safe_drop_index("ix_audit_events_session_id_created_at", "audit_events")
    _safe_drop_index("ix_audit_events_job_id_created_at", "audit_events")

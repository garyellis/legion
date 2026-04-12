"""Move Slack session linkage out of shared sessions into a Slack sidecar."""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "20260411_01"
down_revision = "20260405_02"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "slack_session_links",
        sa.Column("channel_id", sa.String(), nullable=False),
        sa.Column("thread_ts", sa.String(), nullable=False),
        sa.Column("session_id", sa.String(), nullable=False),
        sa.ForeignKeyConstraint(["session_id"], ["sessions.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("channel_id", "thread_ts"),
        sa.UniqueConstraint("session_id"),
    )

    op.execute(
        sa.text(
            """
            INSERT INTO slack_session_links (channel_id, thread_ts, session_id)
            SELECT channel_id, thread_ts, session_id
            FROM (
                SELECT
                    slack_channel_id AS channel_id,
                    slack_thread_ts AS thread_ts,
                    id AS session_id,
                    ROW_NUMBER() OVER (
                        PARTITION BY slack_channel_id, slack_thread_ts
                        ORDER BY last_activity DESC, created_at DESC, id DESC
                    ) AS rn
                FROM sessions
                WHERE slack_channel_id IS NOT NULL
                  AND slack_thread_ts IS NOT NULL
            ) AS ranked
            WHERE rn = 1
            """
        )
    )

    with op.batch_alter_table("sessions") as batch_op:
        batch_op.drop_column("slack_channel_id")
        batch_op.drop_column("slack_thread_ts")


def downgrade() -> None:
    with op.batch_alter_table("sessions") as batch_op:
        batch_op.add_column(sa.Column("slack_channel_id", sa.String(), nullable=True))
        batch_op.add_column(sa.Column("slack_thread_ts", sa.String(), nullable=True))

    op.execute(
        sa.text(
            """
            UPDATE sessions
            SET
                slack_channel_id = (
                    SELECT channel_id
                    FROM slack_session_links
                    WHERE slack_session_links.session_id = sessions.id
                ),
                slack_thread_ts = (
                    SELECT thread_ts
                    FROM slack_session_links
                    WHERE slack_session_links.session_id = sessions.id
                )
            WHERE EXISTS (
                SELECT 1
                FROM slack_session_links
                WHERE slack_session_links.session_id = sessions.id
            )
            """
        )
    )

    op.drop_table("slack_session_links")


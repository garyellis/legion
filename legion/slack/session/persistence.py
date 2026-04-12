"""Database-backed Slack session link repository."""

from __future__ import annotations

from typing import Any, Optional, cast

from sqlalchemy import Column, Engine, ForeignKey, String
from sqlalchemy.orm import sessionmaker

from legion.plumbing.database import Base
from legion.services import session_repository  # noqa: F401
from legion.slack.session.models import SlackSessionLink


class SlackSessionLinkRow(Base):
    __tablename__ = "slack_session_links"

    channel_id = Column(String, primary_key=True)
    thread_ts = Column(String, primary_key=True)
    session_id = Column(
        String,
        ForeignKey("sessions.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
        index=True,
    )


class SQLiteSlackSessionLinkRepository:
    """SQLite/SQLAlchemy implementation for Slack thread-to-session lookup."""

    def __init__(self, engine: Engine) -> None:
        self._session_factory = sessionmaker(bind=engine)

    def save(self, link: SlackSessionLink) -> None:
        """Compatibility wrapper for existing Slack-side callers."""
        self.save_link(link.session_id, link.channel_id, link.thread_ts)

    def save_link(self, session_id: str, channel_id: str, thread_ts: str) -> None:
        """Persist or update the mapping for a Slack thread."""
        with self._session_factory() as session:
            existing_for_session = (
                session.query(SlackSessionLinkRow)
                .filter(SlackSessionLinkRow.session_id == session_id)
                .first()
            )
            if (
                existing_for_session is not None
                and (
                    existing_for_session.channel_id != channel_id
                    or existing_for_session.thread_ts != thread_ts
                )
            ):
                session.delete(existing_for_session)

            row = session.get(SlackSessionLinkRow, (channel_id, thread_ts))
            if row is None:
                row = SlackSessionLinkRow(
                    channel_id=channel_id,
                    thread_ts=thread_ts,
                )
                session.add(row)

            cast(Any, row).session_id = session_id
            session.commit()

    def get_session_id(self, channel_id: str, thread_ts: str) -> Optional[str]:
        with self._session_factory() as session:
            row = cast(
                SlackSessionLinkRow | None,
                session.get(SlackSessionLinkRow, (channel_id, thread_ts)),
            )
            if row is None:
                return None
            return cast(str, row.session_id)

    def get_by_session_id(self, session_id: str) -> Optional[SlackSessionLink]:
        with self._session_factory() as session:
            row = (
                session.query(SlackSessionLinkRow)
                .filter(SlackSessionLinkRow.session_id == session_id)
                .first()
            )
            if row is None:
                return None
            return self._to_domain(row)

    def delete_by_session_id(self, session_id: str) -> None:
        with self._session_factory() as session:
            row = (
                session.query(SlackSessionLinkRow)
                .filter(SlackSessionLinkRow.session_id == session_id)
                .first()
            )
            if row is None:
                return
            session.delete(row)
            session.commit()

    @staticmethod
    def _to_domain(row: SlackSessionLinkRow) -> SlackSessionLink:
        return SlackSessionLink(
            channel_id=cast(str, row.channel_id),
            thread_ts=cast(str, row.thread_ts),
            session_id=cast(str, row.session_id),
        )

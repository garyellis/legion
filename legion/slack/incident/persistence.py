"""Database-backed SlackIncidentIndex."""

from __future__ import annotations

from typing import Optional

from sqlalchemy import Column, Engine, String
from sqlalchemy.orm import sessionmaker

from legion.plumbing.database import Base
from legion.slack.incident.models import SlackIncidentIndex, SlackIncidentState


class SlackIncidentStateRow(Base):
    __tablename__ = "slack_incident_state"

    incident_id = Column(String, primary_key=True)
    channel_id = Column(String, nullable=False, unique=True, index=True)
    dashboard_message_ts = Column(String, nullable=True)


class SQLiteSlackIncidentIndex(SlackIncidentIndex):
    """Database-backed bidirectional incident/channel lookup."""

    def __init__(self, engine: Engine) -> None:
        self._session_factory = sessionmaker(bind=engine)

    def register(self, state: SlackIncidentState) -> None:
        with self._session_factory() as session:
            row = session.get(SlackIncidentStateRow, state.incident_id)
            if row is None:
                row = SlackIncidentStateRow(incident_id=state.incident_id)
                session.add(row)
            row.channel_id = state.channel_id
            row.dashboard_message_ts = state.dashboard_message_ts
            session.commit()

    def get_by_channel(self, channel_id: str) -> Optional[SlackIncidentState]:
        with self._session_factory() as session:
            row = (
                session.query(SlackIncidentStateRow)
                .filter(SlackIncidentStateRow.channel_id == channel_id)
                .first()
            )
            if row is None:
                return None
            return self._to_state(row)

    def get_by_incident(self, incident_id: str) -> Optional[SlackIncidentState]:
        with self._session_factory() as session:
            row = session.get(SlackIncidentStateRow, incident_id)
            if row is None:
                return None
            return self._to_state(row)

    @staticmethod
    def _to_state(row: SlackIncidentStateRow) -> SlackIncidentState:
        return SlackIncidentState(
            incident_id=row.incident_id,
            channel_id=row.channel_id,
            dashboard_message_ts=row.dashboard_message_ts,
        )

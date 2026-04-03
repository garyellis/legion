"""Incident persistence — ABC + SQLite implementation."""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from typing import Optional

from datetime import datetime, timezone

from sqlalchemy import Column, DateTime, Engine, Integer, String, Text
from sqlalchemy.orm import sessionmaker

from legion.domain.incident import Incident, IncidentSeverity, IncidentStatus
from legion.plumbing.database import Base

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# ABC
# ---------------------------------------------------------------------------

class IncidentRepository(ABC):
    @abstractmethod
    def save(self, incident: Incident) -> None: ...

    @abstractmethod
    def get_by_id(self, incident_id: str) -> Optional[Incident]: ...

    @abstractmethod
    def list_active(self) -> list[Incident]: ...


# ---------------------------------------------------------------------------
# SQLite / SQLAlchemy implementation
# ---------------------------------------------------------------------------

class IncidentRow(Base):
    __tablename__ = "incidents"

    id = Column(String, primary_key=True)
    title = Column(String, nullable=False)
    description = Column(Text, nullable=False)
    severity = Column(String, nullable=False)
    status = Column(String, nullable=False, default=IncidentStatus.OPEN.value)
    commander_id = Column(String, nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False)
    updated_at = Column(DateTime(timezone=True), nullable=False)
    resolved_at = Column(DateTime(timezone=True), nullable=True)
    duration_seconds = Column(Integer, nullable=True)
    check_in_interval = Column(Integer, nullable=False, default=30)


class SQLiteIncidentRepository(IncidentRepository):
    def __init__(self, engine: Engine) -> None:
        self._engine = engine
        self._session_factory = sessionmaker(bind=self._engine)

    def save(self, incident: Incident) -> None:
        with self._session_factory() as session:
            row = session.get(IncidentRow, incident.id)
            if row is None:
                row = IncidentRow(id=incident.id)
                session.add(row)
            row.title = incident.title
            row.description = incident.description
            row.severity = incident.severity.value
            row.status = incident.status.value
            row.commander_id = incident.commander_id
            row.created_at = incident.created_at
            row.updated_at = incident.updated_at
            row.resolved_at = incident.resolved_at
            row.duration_seconds = incident.duration_seconds
            row.check_in_interval = incident.check_in_interval
            session.commit()

    def get_by_id(self, incident_id: str) -> Optional[Incident]:
        with self._session_factory() as session:
            row = session.get(IncidentRow, incident_id)
            if row is None:
                return None
            return self._to_domain(row)

    def list_active(self) -> list[Incident]:
        with self._session_factory() as session:
            rows = (
                session.query(IncidentRow)
                .filter(
                    IncidentRow.status.notin_(
                        [IncidentStatus.RESOLVED.value, IncidentStatus.CLOSED.value]
                    )
                )
                .all()
            )
            return [self._to_domain(r) for r in rows]

    @staticmethod
    def _ensure_utc(dt: datetime | None) -> datetime | None:
        """Attach UTC tzinfo to naive datetimes (e.g. from SQLite)."""
        if dt is not None and dt.tzinfo is None:
            return dt.replace(tzinfo=timezone.utc)
        return dt

    @staticmethod
    def _to_domain(row: IncidentRow) -> Incident:
        ensure = SQLiteIncidentRepository._ensure_utc
        return Incident(
            id=row.id,
            title=row.title,
            description=row.description,
            severity=IncidentSeverity(row.severity),
            status=IncidentStatus(row.status),
            commander_id=row.commander_id,
            created_at=ensure(row.created_at),
            updated_at=ensure(row.updated_at),
            resolved_at=ensure(row.resolved_at),
            duration_seconds=row.duration_seconds,
            check_in_interval=row.check_in_interval,
        )

"""Session persistence — ABC + SQLite implementation."""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import Column, DateTime, Engine, String
from sqlalchemy.orm import sessionmaker

from legion.domain.session import Session, SessionStatus
from legion.plumbing.database import Base

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# ABC
# ---------------------------------------------------------------------------

class SessionRepository(ABC):
    @abstractmethod
    def save(self, session: Session) -> None: ...

    @abstractmethod
    def delete(self, session_id: str) -> None: ...

    @abstractmethod
    def get_by_id(self, session_id: str) -> Optional[Session]: ...

    @abstractmethod
    def list_active(self, agent_group_id: str | None = None) -> list[Session]: ...


# ---------------------------------------------------------------------------
# ORM Row class
# ---------------------------------------------------------------------------

class SessionRow(Base):
    __tablename__ = "sessions"

    id = Column(String, primary_key=True)
    org_id = Column(String, nullable=False)
    agent_group_id = Column(String, nullable=False)
    agent_id = Column(String, nullable=True)
    status = Column(String, nullable=False, default=SessionStatus.ACTIVE.value)
    created_at = Column(DateTime(timezone=True), nullable=False)
    last_activity = Column(DateTime(timezone=True), nullable=False)


# ---------------------------------------------------------------------------
# SQLite / SQLAlchemy implementation
# ---------------------------------------------------------------------------

class SQLiteSessionRepository(SessionRepository):
    def __init__(self, engine: Engine) -> None:
        self._engine = engine
        self._session_factory = sessionmaker(bind=self._engine)

    def save(self, session: Session) -> None:
        with self._session_factory() as db:
            row = db.get(SessionRow, session.id)
            if row is None:
                row = SessionRow(id=session.id)
                db.add(row)
            row.org_id = session.org_id
            row.agent_group_id = session.agent_group_id
            row.agent_id = session.agent_id
            row.status = session.status.value
            row.created_at = session.created_at
            row.last_activity = session.last_activity
            db.commit()

    def delete(self, session_id: str) -> None:
        with self._session_factory() as db:
            row = db.get(SessionRow, session_id)
            if row is None:
                return
            db.delete(row)
            db.commit()

    def get_by_id(self, session_id: str) -> Optional[Session]:
        with self._session_factory() as db:
            row = db.get(SessionRow, session_id)
            if row is None:
                return None
            return self._to_domain(row)

    def list_active(self, agent_group_id: str | None = None) -> list[Session]:
        with self._session_factory() as db:
            q = db.query(SessionRow).filter(
                SessionRow.status == SessionStatus.ACTIVE.value
            )
            if agent_group_id is not None:
                q = q.filter(SessionRow.agent_group_id == agent_group_id)
            return [self._to_domain(r) for r in q.all()]

    @staticmethod
    def _ensure_utc(dt: datetime | None) -> datetime | None:
        if dt is not None and dt.tzinfo is None:
            return dt.replace(tzinfo=timezone.utc)
        return dt

    @staticmethod
    def _to_domain(row: SessionRow) -> Session:
        ensure = SQLiteSessionRepository._ensure_utc
        return Session(
            id=row.id,
            org_id=row.org_id,
            agent_group_id=row.agent_group_id,
            agent_id=row.agent_id,
            status=SessionStatus(row.status),
            created_at=ensure(row.created_at),
            last_activity=ensure(row.last_activity),
        )

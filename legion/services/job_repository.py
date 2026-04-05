"""Job persistence — ABC + SQLite implementation."""

from __future__ import annotations

import json
import logging
from abc import ABC, abstractmethod
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import Column, DateTime, Engine, String, Text
from sqlalchemy.orm import sessionmaker

from legion.domain.job import Job, JobStatus, JobType
from legion.plumbing.database import Base

logger = logging.getLogger(__name__)

_TERMINAL_STATUSES = {JobStatus.COMPLETED, JobStatus.FAILED, JobStatus.CANCELLED}


# ---------------------------------------------------------------------------
# ABC
# ---------------------------------------------------------------------------

class JobRepository(ABC):
    @abstractmethod
    def save(self, job: Job) -> None: ...

    @abstractmethod
    def get_by_id(self, job_id: str) -> Optional[Job]: ...

    @abstractmethod
    def list_pending(self, agent_group_id: str) -> list[Job]: ...

    @abstractmethod
    def list_by_agent(self, agent_id: str) -> list[Job]: ...

    @abstractmethod
    def list_active(self, agent_group_id: str | None = None) -> list[Job]: ...


# ---------------------------------------------------------------------------
# ORM Row class
# ---------------------------------------------------------------------------

class JobRow(Base):
    __tablename__ = "jobs"

    id = Column(String, primary_key=True)
    org_id = Column(String, nullable=False)
    agent_group_id = Column(String, nullable=False)
    session_id = Column(String, nullable=False)
    agent_id = Column(String, nullable=True)
    event_id = Column(String, nullable=True)
    type = Column(String, nullable=False)
    status = Column(String, nullable=False, default=JobStatus.PENDING.value)
    payload = Column(Text, nullable=False)
    result = Column(Text, nullable=True)
    error = Column(Text, nullable=True)
    incident_id = Column(String, nullable=True)
    required_capabilities = Column(Text, nullable=False, default="[]")
    created_at = Column(DateTime(timezone=True), nullable=False)
    updated_at = Column(DateTime(timezone=True), nullable=False)
    dispatched_at = Column(DateTime(timezone=True), nullable=True)
    completed_at = Column(DateTime(timezone=True), nullable=True)


# ---------------------------------------------------------------------------
# SQLite / SQLAlchemy implementation
# ---------------------------------------------------------------------------

class SQLiteJobRepository(JobRepository):
    def __init__(self, engine: Engine) -> None:
        self._engine = engine
        self._session_factory = sessionmaker(bind=self._engine)

    def save(self, job: Job) -> None:
        with self._session_factory() as session:
            row = session.get(JobRow, job.id)
            if row is None:
                row = JobRow(id=job.id)
                session.add(row)
            row.org_id = job.org_id
            row.agent_group_id = job.agent_group_id
            row.session_id = job.session_id
            row.agent_id = job.agent_id
            row.event_id = job.event_id
            row.type = job.type.value
            row.status = job.status.value
            row.payload = job.payload
            row.result = job.result
            row.error = job.error
            row.incident_id = job.incident_id
            row.required_capabilities = json.dumps(job.required_capabilities)
            row.created_at = job.created_at
            row.updated_at = job.updated_at
            row.dispatched_at = job.dispatched_at
            row.completed_at = job.completed_at
            session.commit()

    def get_by_id(self, job_id: str) -> Optional[Job]:
        with self._session_factory() as session:
            row = session.get(JobRow, job_id)
            if row is None:
                return None
            return self._to_domain(row)

    def list_pending(self, agent_group_id: str) -> list[Job]:
        with self._session_factory() as session:
            rows = (
                session.query(JobRow)
                .filter(
                    JobRow.agent_group_id == agent_group_id,
                    JobRow.status == JobStatus.PENDING.value,
                )
                .all()
            )
            return [self._to_domain(r) for r in rows]

    def list_by_agent(self, agent_id: str) -> list[Job]:
        with self._session_factory() as session:
            rows = (
                session.query(JobRow)
                .filter(JobRow.agent_id == agent_id)
                .all()
            )
            return [self._to_domain(r) for r in rows]

    def list_active(self, agent_group_id: str | None = None) -> list[Job]:
        terminal = [s.value for s in _TERMINAL_STATUSES]
        with self._session_factory() as session:
            q = session.query(JobRow).filter(JobRow.status.notin_(terminal))
            if agent_group_id is not None:
                q = q.filter(JobRow.agent_group_id == agent_group_id)
            return [self._to_domain(r) for r in q.all()]

    @staticmethod
    def _ensure_utc(dt: datetime | None) -> datetime | None:
        if dt is not None and dt.tzinfo is None:
            return dt.replace(tzinfo=timezone.utc)
        return dt

    @staticmethod
    def _to_domain(row: JobRow) -> Job:
        ensure = SQLiteJobRepository._ensure_utc
        return Job(
            id=row.id,
            org_id=row.org_id,
            agent_group_id=row.agent_group_id,
            session_id=row.session_id,
            agent_id=row.agent_id,
            event_id=row.event_id,
            type=JobType(row.type),
            status=JobStatus(row.status),
            payload=row.payload,
            result=row.result,
            error=row.error,
            incident_id=row.incident_id,
            required_capabilities=json.loads(row.required_capabilities or "[]"),
            created_at=ensure(row.created_at),
            updated_at=ensure(row.updated_at),
            dispatched_at=ensure(row.dispatched_at),
            completed_at=ensure(row.completed_at),
        )

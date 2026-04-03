"""Job domain model — a unit of work dispatched to an agent."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from enum import Enum

from pydantic import BaseModel, Field


class JobType(str, Enum):
    TRIAGE = "TRIAGE"
    QUERY = "QUERY"


class JobStatus(str, Enum):
    PENDING = "PENDING"
    DISPATCHED = "DISPATCHED"
    RUNNING = "RUNNING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


class Job(BaseModel):
    """A unit of work to be dispatched to an agent."""

    model_config = {"validate_assignment": True}

    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    org_id: str
    cluster_group_id: str
    agent_id: str | None = None
    type: JobType
    status: JobStatus = JobStatus.PENDING
    payload: str
    result: str | None = None
    error: str | None = None
    incident_id: str | None = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    dispatched_at: datetime | None = None
    completed_at: datetime | None = None

    def dispatch_to(self, agent_id: str) -> None:
        """PENDING -> DISPATCHED, assign to agent."""
        self.status = JobStatus.DISPATCHED
        self.agent_id = agent_id
        now = datetime.now(timezone.utc)
        self.dispatched_at = now
        self.updated_at = now

    def start(self) -> None:
        """DISPATCHED -> RUNNING."""
        self.status = JobStatus.RUNNING
        self.updated_at = datetime.now(timezone.utc)

    def complete(self, result: str) -> None:
        """RUNNING -> COMPLETED with result."""
        self.status = JobStatus.COMPLETED
        self.result = result
        now = datetime.now(timezone.utc)
        self.completed_at = now
        self.updated_at = now

    def fail(self, error: str) -> None:
        """RUNNING -> FAILED with error."""
        self.status = JobStatus.FAILED
        self.error = error
        now = datetime.now(timezone.utc)
        self.completed_at = now
        self.updated_at = now

    def cancel(self) -> None:
        """PENDING/DISPATCHED -> CANCELLED."""
        self.status = JobStatus.CANCELLED
        now = datetime.now(timezone.utc)
        self.completed_at = now
        self.updated_at = now

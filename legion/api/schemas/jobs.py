"""Job response schemas."""

from __future__ import annotations

from datetime import datetime

from legion.api.schemas.base import ResponseBase
from legion.domain.job import JobStatus, JobType


class JobResponse(ResponseBase):
    id: str
    org_id: str
    agent_group_id: str
    session_id: str
    agent_id: str | None
    event_id: str | None
    type: JobType
    status: JobStatus
    payload: str
    result: str | None
    error: str | None
    incident_id: str | None
    required_capabilities: list[str]
    created_at: datetime
    updated_at: datetime
    dispatched_at: datetime | None
    completed_at: datetime | None

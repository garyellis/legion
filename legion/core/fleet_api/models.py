"""API response models for the Legion Fleet API.

These are flat serialization shapes matching the API JSON responses.
No behavior, no state transitions — just data.
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel


class OrgResponse(BaseModel):
    """Organization as returned by the API."""

    id: str
    name: str
    slug: str
    created_at: datetime
    updated_at: datetime


class ProjectResponse(BaseModel):
    """Project as returned by the API."""

    id: str
    org_id: str
    name: str
    slug: str
    created_at: datetime
    updated_at: datetime


class AgentGroupResponse(BaseModel):
    """Agent group as returned by the API."""

    id: str
    org_id: str
    project_id: str
    name: str
    slug: str
    environment: str
    provider: str
    execution_mode: str
    created_at: datetime
    updated_at: datetime


class AgentResponse(BaseModel):
    """Agent as returned by the API."""

    id: str
    agent_group_id: str
    name: str
    status: str
    current_job_id: str | None = None
    capabilities: list[str] = []
    last_heartbeat: datetime | None = None
    created_at: datetime
    updated_at: datetime

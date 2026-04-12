"""AgentGroup request and response schemas."""

from __future__ import annotations

from datetime import datetime
from typing import ClassVar

from pydantic import BaseModel

from legion.api.schemas.base import ResponseBase
from legion.domain.agent_group import ExecutionMode


class AgentGroupCreate(BaseModel):
    org_id: str
    project_id: str
    name: str
    slug: str
    environment: str
    provider: str


class AgentGroupUpdate(BaseModel):
    name: str | None = None
    slug: str | None = None
    environment: str | None = None
    provider: str | None = None


class AgentGroupTokenResponse(BaseModel):
    agent_group_id: str
    registration_token: str
    registration_token_rotated_at: datetime


class AgentGroupResponse(ResponseBase):
    _excluded_domain_fields: ClassVar[frozenset[str]] = frozenset(
        {"registration_token_hash", "registration_token_rotated_at"}
    )

    id: str
    org_id: str
    project_id: str
    name: str
    slug: str
    environment: str
    provider: str
    execution_mode: ExecutionMode
    created_at: datetime
    updated_at: datetime

"""Agent request and response schemas."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field

from legion.api.schemas.base import ResponseBase
from legion.domain.agent import AgentStatus


class AgentRegister(BaseModel):
    registration_token: str
    name: str
    capabilities: list[str] = Field(default_factory=list)


class AgentConnectionConfig(BaseModel):
    heartbeat_interval_seconds: int
    websocket_path: str


class AgentResponse(ResponseBase):
    id: str
    agent_group_id: str
    name: str
    status: AgentStatus
    current_job_id: str | None
    capabilities: list[str]
    last_heartbeat: datetime | None
    created_at: datetime
    updated_at: datetime


class AgentRegistrationResponse(BaseModel):
    agent: AgentResponse
    session_token: str
    session_token_expires_at: datetime
    config: AgentConnectionConfig

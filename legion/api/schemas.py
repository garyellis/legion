"""Request schemas for the API surface.

Domain models serve as response models directly (already Pydantic BaseModels).
These thin *Create / *Upsert schemas handle POST/PUT request bodies.
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Literal

from pydantic import BaseModel, Field

from legion.domain.agent import Agent
from legion.domain.channel_mapping import ChannelMode
from legion.domain.filter_rule import FilterAction


class OrganizationCreate(BaseModel):
    name: str
    slug: str


class OrganizationUpdate(BaseModel):
    name: str | None = None
    slug: str | None = None


class ProjectCreate(BaseModel):
    org_id: str
    name: str
    slug: str


class ProjectUpdate(BaseModel):
    name: str | None = None
    slug: str | None = None


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


class AgentRegister(BaseModel):
    registration_token: str
    name: str
    capabilities: list[str] = Field(default_factory=list)


class AgentConnectionConfig(BaseModel):
    heartbeat_interval_seconds: int
    websocket_path: str


class AgentRegistrationResponse(BaseModel):
    agent: Agent
    session_token: str
    session_token_expires_at: datetime
    config: AgentConnectionConfig


class AgentHeartbeatMessage(BaseModel):
    type: Literal["heartbeat"]


class AgentJobStartedMessage(BaseModel):
    type: Literal["job_started"]
    job_id: str


class AgentJobResultMessage(BaseModel):
    type: Literal["job_result"]
    job_id: str
    result: str


class AgentJobFailedMessage(BaseModel):
    type: Literal["job_failed"]
    job_id: str
    error: str = ""


AgentWebSocketMessage = Annotated[
    AgentHeartbeatMessage | AgentJobStartedMessage | AgentJobResultMessage | AgentJobFailedMessage,
    Field(discriminator="type"),
]


class ChannelMappingCreate(BaseModel):
    org_id: str
    channel_id: str
    agent_group_id: str
    mode: ChannelMode = ChannelMode.ALERT


class FilterRuleCreate(BaseModel):
    channel_mapping_id: str
    pattern: str
    action: FilterAction = FilterAction.TRIAGE
    priority: int = 0


class PromptConfigUpsert(BaseModel):
    system_prompt: str = ""
    stack_manifest: str = ""
    persona: str = ""


class SessionCreate(BaseModel):
    org_id: str
    agent_group_id: str


class SessionMessage(BaseModel):
    payload: str

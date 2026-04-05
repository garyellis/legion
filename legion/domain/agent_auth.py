"""Agent authentication data models."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from pydantic import BaseModel, Field

from legion.domain.agent import Agent
from legion.domain.agent_group import AgentGroup


class AgentSessionToken(BaseModel):
    """Persisted short-lived session token used for agent WebSocket auth."""

    model_config = {"validate_assignment": True}

    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    agent_id: str
    token_hash: str
    expires_at: datetime
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    def is_expired(self, now: datetime | None = None) -> bool:
        reference = now or datetime.now(timezone.utc)
        return self.expires_at <= reference


class AgentRegistrationResult(BaseModel):
    """Outcome of a successful agent registration."""

    agent: Agent
    session_token: str
    session_token_expires_at: datetime


class AgentGroupTokenRotationResult(BaseModel):
    """Outcome of issuing or rotating an agent-group registration token."""

    agent_group: AgentGroup
    registration_token: str

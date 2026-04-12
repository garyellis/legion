"""Session domain model — conversational context pinned to an agent."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from enum import Enum

from pydantic import BaseModel, Field


class SessionStatus(str, Enum):
    ACTIVE = "ACTIVE"
    CLOSED = "CLOSED"


class Session(BaseModel):
    """A conversational context between a user and an agent."""

    model_config = {"validate_assignment": True}

    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    org_id: str
    agent_group_id: str
    agent_id: str | None = None
    status: SessionStatus = SessionStatus.ACTIVE
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    last_activity: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    def pin_agent(self, agent_id: str) -> None:
        """Pin this session to a specific agent."""
        self.agent_id = agent_id
        self.last_activity = datetime.now(timezone.utc)

    def touch(self) -> None:
        """Update last_activity timestamp."""
        self.last_activity = datetime.now(timezone.utc)

    def close(self) -> None:
        """Transition ACTIVE → CLOSED."""
        self.status = SessionStatus.CLOSED
        self.last_activity = datetime.now(timezone.utc)

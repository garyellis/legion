"""Agent domain model — an SRE agent instance within a cluster group."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from enum import Enum

from pydantic import BaseModel, Field


class AgentStatus(str, Enum):
    IDLE = "IDLE"
    BUSY = "BUSY"
    OFFLINE = "OFFLINE"


class Agent(BaseModel):
    """An SRE agent registered to a cluster group."""

    model_config = {"validate_assignment": True}

    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    cluster_group_id: str
    name: str
    status: AgentStatus = AgentStatus.OFFLINE
    current_job_id: str | None = None
    capabilities: list[str] = Field(default_factory=list)
    last_heartbeat: datetime | None = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    def go_idle(self) -> None:
        """Transition to IDLE from BUSY or OFFLINE, clearing current job."""
        self.status = AgentStatus.IDLE
        self.current_job_id = None
        self.updated_at = datetime.now(timezone.utc)

    def go_busy(self, job_id: str) -> None:
        """Transition to BUSY from IDLE, setting current job."""
        self.status = AgentStatus.BUSY
        self.current_job_id = job_id
        self.updated_at = datetime.now(timezone.utc)

    def go_offline(self) -> None:
        """Transition to OFFLINE from any state, clearing current job."""
        self.status = AgentStatus.OFFLINE
        self.current_job_id = None
        self.updated_at = datetime.now(timezone.utc)

    def heartbeat(self) -> None:
        """Record a heartbeat timestamp."""
        now = datetime.now(timezone.utc)
        self.last_heartbeat = now
        self.updated_at = now

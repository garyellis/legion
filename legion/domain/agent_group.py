"""AgentGroup domain model — a logical grouping of agents within an org."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from enum import Enum

from pydantic import BaseModel, Field


class ExecutionMode(str, Enum):
    READ_ONLY = "READ_ONLY"
    PROPOSE = "PROPOSE"
    REQUIRE_APPROVAL = "REQUIRE_APPROVAL"
    AUTO_EXECUTE = "AUTO_EXECUTE"


class AgentGroup(BaseModel):
    """A logical grouping of infrastructure agents belonging to an organization."""

    model_config = {"validate_assignment": True}

    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    org_id: str
    name: str
    slug: str
    environment: str  # dev, staging, prod
    provider: str  # aks, eks, gke, on-prem
    execution_mode: ExecutionMode = ExecutionMode.READ_ONLY
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

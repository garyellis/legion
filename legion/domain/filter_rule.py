"""FilterRule domain model — per-channel regex rules for alert triage."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from enum import Enum

from pydantic import BaseModel, Field


class FilterAction(str, Enum):
    TRIAGE = "TRIAGE"
    IGNORE = "IGNORE"


class FilterRule(BaseModel):
    """A regex rule that decides whether an alert message triggers a triage job."""

    model_config = {"validate_assignment": True}

    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    channel_mapping_id: str
    pattern: str
    action: FilterAction = FilterAction.TRIAGE
    priority: int = 0  # Higher = evaluated first
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

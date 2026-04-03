"""ChannelMapping domain model — links a Slack channel to an agent group."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from enum import Enum

from pydantic import BaseModel, Field


class ChannelMode(str, Enum):
    ALERT = "ALERT"  # Filter rules evaluate messages → triage jobs
    CHAT = "CHAT"  # Every message → query job via session


class ChannelMapping(BaseModel):
    """Maps a Slack channel to an agent group with a processing mode."""

    model_config = {"validate_assignment": True}

    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    org_id: str
    channel_id: str
    agent_group_id: str
    mode: ChannelMode = ChannelMode.ALERT
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

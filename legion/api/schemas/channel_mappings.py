"""ChannelMapping request and response schemas."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel

from legion.api.schemas.base import ResponseBase
from legion.domain.channel_mapping import ChannelMode


class ChannelMappingCreate(BaseModel):
    org_id: str
    channel_id: str
    agent_group_id: str
    mode: ChannelMode = ChannelMode.ALERT


class ChannelMappingResponse(ResponseBase):
    id: str
    org_id: str
    channel_id: str
    agent_group_id: str
    mode: ChannelMode
    created_at: datetime
    updated_at: datetime

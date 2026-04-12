"""Session request and response schemas."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel

from legion.api.schemas.base import ResponseBase
from legion.domain.session import SessionStatus


class SessionCreate(BaseModel):
    org_id: str
    agent_group_id: str


class SessionMessage(BaseModel):
    payload: str


class SessionResponse(ResponseBase):
    id: str
    org_id: str
    agent_group_id: str
    agent_id: str | None
    status: SessionStatus
    created_at: datetime
    last_activity: datetime

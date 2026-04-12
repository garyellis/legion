"""FilterRule request and response schemas."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel

from legion.api.schemas.base import ResponseBase
from legion.domain.filter_rule import FilterAction


class FilterRuleCreate(BaseModel):
    channel_mapping_id: str
    pattern: str
    action: FilterAction = FilterAction.TRIAGE
    priority: int = 0


class FilterRuleResponse(ResponseBase):
    id: str
    channel_mapping_id: str
    pattern: str
    action: FilterAction
    priority: int
    created_at: datetime
    updated_at: datetime

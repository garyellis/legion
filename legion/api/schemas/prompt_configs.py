"""PromptConfig request and response schemas."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel

from legion.api.schemas.base import ResponseBase


class PromptConfigUpsert(BaseModel):
    system_prompt: str = ""
    stack_manifest: str = ""
    persona: str = ""


class PromptConfigResponse(ResponseBase):
    id: str
    agent_group_id: str
    system_prompt: str
    stack_manifest: str
    persona: str
    created_at: datetime
    updated_at: datetime

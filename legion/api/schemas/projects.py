"""Project request and response schemas."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel

from legion.api.schemas.base import ResponseBase


class ProjectCreate(BaseModel):
    org_id: str
    name: str
    slug: str


class ProjectUpdate(BaseModel):
    name: str | None = None
    slug: str | None = None


class ProjectResponse(ResponseBase):
    id: str
    org_id: str
    name: str
    slug: str
    created_at: datetime
    updated_at: datetime

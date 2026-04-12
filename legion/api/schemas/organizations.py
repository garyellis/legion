"""Organization request and response schemas."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel

from legion.api.schemas.base import ResponseBase


class OrganizationCreate(BaseModel):
    name: str
    slug: str


class OrganizationUpdate(BaseModel):
    name: str | None = None
    slug: str | None = None


class OrganizationResponse(ResponseBase):
    id: str
    name: str
    slug: str
    created_at: datetime
    updated_at: datetime

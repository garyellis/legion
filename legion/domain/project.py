"""Project domain model — isolation scope within an organization."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from pydantic import BaseModel, Field


class Project(BaseModel):
    """A project groups agent-groups within an organization for isolation."""

    model_config = {"validate_assignment": True}

    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    org_id: str
    name: str
    slug: str
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

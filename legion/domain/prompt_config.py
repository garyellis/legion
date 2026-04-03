"""PromptConfig domain model — per-cluster-group agent configuration."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from pydantic import BaseModel, Field


class PromptConfig(BaseModel):
    """System prompt, stack manifest, and persona for a cluster group's agents."""

    model_config = {"validate_assignment": True}

    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    cluster_group_id: str
    system_prompt: str = ""
    stack_manifest: str = ""  # "Payment-API → Redis → Postgres"
    persona: str = ""  # "PostgreSQL Expert"
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

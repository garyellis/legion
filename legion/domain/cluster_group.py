"""ClusterGroup domain model — a logical grouping of clusters within an org."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from pydantic import BaseModel, Field


class ClusterGroup(BaseModel):
    """A logical grouping of infrastructure clusters belonging to an organization."""

    model_config = {"validate_assignment": True}

    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    org_id: str
    name: str
    slug: str
    environment: str  # dev, staging, prod
    provider: str  # aks, eks, gke, on-prem
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

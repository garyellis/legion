"""Incident domain model — pure business entity, no surface state.

Adapted from references/incident-commander-bot/models/domain.py.
Per CONTRIBUTING.md: NO channel_id, NO dashboard_message_ts on domain models.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Optional

from pydantic import BaseModel, Field


class IncidentSeverity(str, Enum):
    SEV1 = "SEV1"
    SEV2 = "SEV2"
    SEV3 = "SEV3"
    SEV4 = "SEV4"


class IncidentStatus(str, Enum):
    OPEN = "OPEN"
    INVESTIGATING = "INVESTIGATING"
    MITIGATED = "MITIGATED"
    RESOLVED = "RESOLVED"
    CLOSED = "CLOSED"


class Incident(BaseModel):
    """Core domain entity for an incident.

    Contains business fields only — Slack-specific state (channel_id,
    dashboard_message_ts) lives in ``slack/incident/models.py``.
    """

    model_config = {"validate_assignment": True}

    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    title: str
    description: str
    severity: IncidentSeverity
    status: IncidentStatus = IncidentStatus.OPEN
    commander_id: Optional[str] = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    resolved_at: Optional[datetime] = None
    duration_seconds: Optional[int] = None
    check_in_interval: int = 30
    metadata: dict[str, Any] = Field(default_factory=dict)

    def transition_to(
        self, new_status: IncidentStatus, *, end_time: datetime | None = None
    ) -> None:
        """Transition to *new_status*, stopping the clock on RESOLVED."""
        self.status = new_status
        self.updated_at = datetime.now(timezone.utc)

        if new_status == IncidentStatus.RESOLVED and self.resolved_at is None:
            self.resolved_at = end_time or datetime.now(timezone.utc)
            self.duration_seconds = int(
                (self.resolved_at - self.created_at).total_seconds()
            )

    def assign_commander(self, user_id: str) -> None:
        self.commander_id = user_id
        self.updated_at = datetime.now(timezone.utc)


class IncidentBuilder:
    """Fluent builder for ``Incident``."""

    def __init__(self) -> None:
        self._title: str | None = None
        self._description: str | None = None
        self._severity: IncidentSeverity = IncidentSeverity.SEV3
        self._commander_id: str | None = None
        self._check_in_interval: int = 30
        self._metadata: dict[str, Any] = {}

    def with_title(self, title: str) -> IncidentBuilder:
        self._title = title
        return self

    def with_description(self, description: str) -> IncidentBuilder:
        self._description = description
        return self

    def with_severity(self, severity: IncidentSeverity) -> IncidentBuilder:
        self._severity = severity
        return self

    def assigned_to(self, user_id: str) -> IncidentBuilder:
        self._commander_id = user_id
        return self

    def with_check_in_interval(self, minutes: int) -> IncidentBuilder:
        self._check_in_interval = minutes
        return self

    def with_metadata(self, key: str, value: Any) -> IncidentBuilder:
        self._metadata[key] = value
        return self

    def build(self) -> Incident:
        if not self._title:
            raise ValueError("Incident title is required")
        if not self._description:
            raise ValueError("Incident description is required")

        return Incident(
            title=self._title,
            description=self._description,
            severity=self._severity,
            commander_id=self._commander_id,
            check_in_interval=self._check_in_interval,
            metadata=self._metadata,
        )

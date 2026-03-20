"""Incident lifecycle service — pure business logic, no surface dependencies.

Adapted from references/incident-commander-bot/services/incident_service.py.
Communicates events through injected callbacks instead of importing Slack/AI.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Callable, Optional

from legion.domain.incident import (
    Incident,
    IncidentBuilder,
    IncidentSeverity,
    IncidentStatus,
)
from legion.services.repository import IncidentRepository

logger = logging.getLogger(__name__)

# Callback type aliases
OnStaleIncident = Callable[[Incident], None]
OnIncidentResolved = Callable[[Incident, str], None]


class IncidentService:
    """Coordinates incident lifecycle.

    Surface-agnostic: signals events through optional callbacks so that
    Slack posting, AI summaries, etc. can be wired at the surface layer.
    """

    def __init__(
        self,
        repository: IncidentRepository,
        *,
        on_stale_incident: OnStaleIncident | None = None,
        on_incident_resolved: OnIncidentResolved | None = None,
    ) -> None:
        self.repository = repository
        self._on_stale = on_stale_incident
        self._on_resolved = on_incident_resolved

    def create_incident(
        self,
        title: str,
        description: str,
        severity: IncidentSeverity,
        commander_id: str,
        check_in_interval: int = 30,
    ) -> Incident:
        incident = (
            IncidentBuilder()
            .with_title(title)
            .with_description(description)
            .with_severity(severity)
            .assigned_to(commander_id)
            .with_check_in_interval(check_in_interval)
            .build()
        )
        self.repository.save(incident)
        logger.info("Incident created: %s (%s)", incident.id, incident.title)
        return incident

    def get_incident(self, incident_id: str) -> Optional[Incident]:
        return self.repository.get_by_id(incident_id)

    def get_active_incidents(self) -> list[Incident]:
        return self.repository.list_active()

    def resolve_incident(
        self,
        incident_id: str,
        user_id: str,
        summary: str,
        *,
        resolved_at: datetime | None = None,
    ) -> Incident:
        incident = self.repository.get_by_id(incident_id)
        if not incident:
            raise ValueError(f"Incident {incident_id} not found")

        incident.transition_to(IncidentStatus.RESOLVED, end_time=resolved_at)
        self.repository.save(incident)
        logger.info("Incident resolved: %s by %s", incident_id, user_id)

        if self._on_resolved:
            self._on_resolved(incident, summary)

        return incident

    def close_incident(self, incident_id: str) -> Incident:
        incident = self.repository.get_by_id(incident_id)
        if not incident:
            raise ValueError(f"Incident {incident_id} not found")
        incident.transition_to(IncidentStatus.CLOSED)
        self.repository.save(incident)
        return incident

    def update_severity(
        self, incident_id: str, severity: IncidentSeverity
    ) -> Incident:
        incident = self.repository.get_by_id(incident_id)
        if not incident:
            raise ValueError(f"Incident {incident_id} not found")
        incident.severity = severity
        self.repository.save(incident)
        return incident

    def check_stale_incidents(self) -> None:
        """Called periodically by the scheduler."""
        active = self.get_active_incidents()
        now = datetime.now(timezone.utc)

        for incident in active:
            threshold = timedelta(minutes=incident.check_in_interval)
            if (now - incident.updated_at) > threshold:
                logger.info("Incident %s is stale.", incident.id)
                if self._on_stale:
                    self._on_stale(incident)
                # Reset the timer
                incident.updated_at = now
                self.repository.save(incident)

"""End-to-end integration test for the incident lifecycle (no external deps)."""

import pytest

from legion.domain.incident import IncidentSeverity, IncidentStatus
from legion.plumbing.database import create_all, create_engine
from legion.services.incident_service import IncidentService
from legion.services.repository import SQLiteIncidentRepository
from legion.slack.incident.models import InMemorySlackIncidentIndex, SlackIncidentState


class TestIncidentIntegration:
    """Full lifecycle: create → track Slack state → stale check → resolve → close."""

    def test_full_lifecycle(self):
        # --- Setup ---
        stale_events = []
        resolve_events = []

        engine = create_engine("sqlite:///:memory:")
        create_all(engine)
        repo = SQLiteIncidentRepository(engine)
        service = IncidentService(
            repo,
            on_stale_incident=lambda inc: stale_events.append(inc.id),
            on_incident_resolved=lambda inc, summary: resolve_events.append(
                (inc.id, summary)
            ),
        )
        slack_index = InMemorySlackIncidentIndex()

        # --- Create incident ---
        incident = service.create_incident(
            title="Database outage",
            description="Primary DB unreachable",
            severity=IncidentSeverity.SEV1,
            commander_id="U001",
            check_in_interval=15,
        )
        assert incident.status == IncidentStatus.OPEN

        # --- Simulate Slack channel creation ---
        state = SlackIncidentState(incident.id, "C-INC-001", "1234.5678")
        slack_index.register(state)

        found_by_channel = slack_index.get_by_channel("C-INC-001")
        assert found_by_channel is not None
        assert found_by_channel.incident_id == state.incident_id
        assert found_by_channel.channel_id == state.channel_id

        found_by_incident = slack_index.get_by_incident(incident.id)
        assert found_by_incident is not None
        assert found_by_incident.incident_id == state.incident_id

        # --- Force stale ---
        from datetime import datetime, timedelta, timezone

        incident.updated_at = datetime.now(timezone.utc) - timedelta(hours=1)
        repo.save(incident)
        service.check_stale_incidents()
        assert incident.id in stale_events

        # --- Resolve ---
        resolved = service.resolve_incident(incident.id, "U001", "Failover complete")
        assert resolved.status == IncidentStatus.RESOLVED
        assert resolved.duration_seconds is not None
        assert len(resolve_events) == 1
        assert resolve_events[0][1] == "Failover complete"

        # --- Close ---
        closed = service.close_incident(incident.id)
        assert closed.status == IncidentStatus.CLOSED

        # --- No more active incidents ---
        assert len(service.get_active_incidents()) == 0

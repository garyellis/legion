"""Tests for legion.domain.incident."""

from datetime import datetime, timezone

import pytest

from legion.domain.incident import (
    Incident,
    IncidentBuilder,
    IncidentSeverity,
    IncidentStatus,
)


class TestIncident:
    def test_creation_defaults(self):
        inc = Incident(title="outage", description="db down", severity=IncidentSeverity.SEV1)
        assert inc.status == IncidentStatus.OPEN
        assert inc.commander_id is None
        assert inc.resolved_at is None
        assert inc.duration_seconds is None
        assert inc.id  # non-empty UUID

    def test_transition_to_investigating(self):
        inc = Incident(title="t", description="d", severity=IncidentSeverity.SEV2)
        inc.transition_to(IncidentStatus.INVESTIGATING)
        assert inc.status == IncidentStatus.INVESTIGATING
        assert inc.resolved_at is None

    def test_transition_to_resolved_stops_clock(self):
        created = datetime(2026, 3, 14, 10, 0, 0, tzinfo=timezone.utc)
        inc = Incident(
            title="t", description="d", severity=IncidentSeverity.SEV3,
            created_at=created, updated_at=created,
        )
        end = datetime(2026, 3, 14, 12, 0, 0, tzinfo=timezone.utc)
        inc.transition_to(IncidentStatus.RESOLVED, end_time=end)
        assert inc.status == IncidentStatus.RESOLVED
        assert inc.resolved_at == end
        assert inc.duration_seconds == 7200  # 2 hours

    def test_assign_commander(self):
        inc = Incident(title="t", description="d", severity=IncidentSeverity.SEV1)
        inc.assign_commander("U123")
        assert inc.commander_id == "U123"

    def test_no_slack_fields(self):
        """Domain model must NOT have Slack-specific fields."""
        fields = set(Incident.model_fields.keys())
        assert "channel_id" not in fields
        assert "dashboard_message_ts" not in fields


class TestIncidentBuilder:
    def test_build_success(self):
        inc = (
            IncidentBuilder()
            .with_title("fire")
            .with_description("everything is on fire")
            .with_severity(IncidentSeverity.SEV1)
            .assigned_to("U999")
            .with_check_in_interval(15)
            .build()
        )
        assert inc.title == "fire"
        assert inc.severity == IncidentSeverity.SEV1
        assert inc.commander_id == "U999"
        assert inc.check_in_interval == 15

    def test_build_missing_title_raises(self):
        with pytest.raises(ValueError, match="title"):
            IncidentBuilder().with_description("d").build()

    def test_build_missing_description_raises(self):
        with pytest.raises(ValueError, match="description"):
            IncidentBuilder().with_title("t").build()

    def test_with_metadata(self):
        inc = (
            IncidentBuilder()
            .with_title("t")
            .with_description("d")
            .with_metadata("jira", "PROJ-123")
            .build()
        )
        assert inc.metadata["jira"] == "PROJ-123"

"""Tests for legion.services.incident_service with SQLite repo."""

import pytest

from legion.domain.incident import IncidentSeverity, IncidentStatus
from legion.plumbing.database import create_all, create_engine
from legion.services.incident_service import IncidentService
from legion.services.repository import SQLiteIncidentRepository


@pytest.fixture()
def _engine():
    engine = create_engine("sqlite:///:memory:")
    create_all(engine)
    return engine


@pytest.fixture()
def service(_engine):
    return IncidentService(SQLiteIncidentRepository(_engine))


class TestIncidentService:
    def test_create_and_get(self, service):
        inc = service.create_incident("outage", "db down", IncidentSeverity.SEV1, "U1")
        assert inc.title == "outage"
        assert service.get_incident(inc.id) is not None

    def test_get_nonexistent_returns_none(self, service):
        assert service.get_incident("nope") is None

    def test_active_incidents(self, service):
        service.create_incident("a", "d", IncidentSeverity.SEV2, "U1")
        service.create_incident("b", "d", IncidentSeverity.SEV3, "U2")
        assert len(service.get_active_incidents()) == 2

    def test_resolve_incident(self, service):
        inc = service.create_incident("a", "d", IncidentSeverity.SEV2, "U1")
        resolved = service.resolve_incident(inc.id, "U1", "fixed it")
        assert resolved.status == IncidentStatus.RESOLVED
        assert resolved.duration_seconds is not None

    def test_resolve_nonexistent_raises(self, service):
        with pytest.raises(ValueError):
            service.resolve_incident("nope", "U1", "summary")

    def test_close_incident(self, service):
        inc = service.create_incident("a", "d", IncidentSeverity.SEV2, "U1")
        service.resolve_incident(inc.id, "U1", "done")
        closed = service.close_incident(inc.id)
        assert closed.status == IncidentStatus.CLOSED

    def test_update_severity(self, service):
        inc = service.create_incident("a", "d", IncidentSeverity.SEV3, "U1")
        updated = service.update_severity(inc.id, IncidentSeverity.SEV1)
        assert updated.severity == IncidentSeverity.SEV1

    def test_resolved_callback_fires(self, _engine):
        calls = []
        svc = IncidentService(
            SQLiteIncidentRepository(_engine),
            on_incident_resolved=lambda inc, summary: calls.append((inc.id, summary)),
        )
        inc = svc.create_incident("a", "d", IncidentSeverity.SEV2, "U1")
        svc.resolve_incident(inc.id, "U1", "fix")
        assert len(calls) == 1
        assert calls[0][1] == "fix"

    def test_stale_callback_fires(self, _engine):
        calls = []
        svc = IncidentService(
            SQLiteIncidentRepository(_engine),
            on_stale_incident=lambda inc: calls.append(inc.id),
        )
        inc = svc.create_incident("a", "d", IncidentSeverity.SEV2, "U1", check_in_interval=0)
        # Force stale by setting updated_at far in the past
        from datetime import datetime, timedelta, timezone
        inc.updated_at = datetime.now(timezone.utc) - timedelta(hours=1)
        svc.repository.save(inc)
        svc.check_stale_incidents()
        assert inc.id in calls

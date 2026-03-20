"""Tests for SQLiteIncidentRepository using in-memory SQLite."""

import pytest

from legion.domain.incident import Incident, IncidentSeverity, IncidentStatus
from legion.plumbing.database import create_all, create_engine
from legion.services.repository import (
    InMemoryIncidentRepository,
    SQLiteIncidentRepository,
)


@pytest.fixture(params=["memory", "sqlite"])
def repo(request):
    if request.param == "memory":
        return InMemoryIncidentRepository()
    engine = create_engine("sqlite:///:memory:")
    create_all(engine)
    return SQLiteIncidentRepository(engine)


class TestRepositoryContract:
    """Both repo implementations must pass identical tests."""

    def test_save_and_get(self, repo):
        inc = Incident(title="t", description="d", severity=IncidentSeverity.SEV1)
        repo.save(inc)
        loaded = repo.get_by_id(inc.id)
        assert loaded is not None
        assert loaded.title == "t"
        assert loaded.severity == IncidentSeverity.SEV1

    def test_get_nonexistent(self, repo):
        assert repo.get_by_id("nope") is None

    def test_list_active_excludes_resolved(self, repo):
        inc1 = Incident(title="a", description="d", severity=IncidentSeverity.SEV2)
        inc2 = Incident(title="b", description="d", severity=IncidentSeverity.SEV3)
        repo.save(inc1)
        repo.save(inc2)
        assert len(repo.list_active()) == 2

        inc1.transition_to(IncidentStatus.RESOLVED)
        repo.save(inc1)
        active = repo.list_active()
        assert len(active) == 1
        assert active[0].id == inc2.id

    def test_list_active_excludes_closed(self, repo):
        inc = Incident(title="c", description="d", severity=IncidentSeverity.SEV4)
        repo.save(inc)
        inc.transition_to(IncidentStatus.CLOSED)
        repo.save(inc)
        assert len(repo.list_active()) == 0

    def test_update_existing(self, repo):
        inc = Incident(title="t", description="d", severity=IncidentSeverity.SEV2)
        repo.save(inc)
        inc.assign_commander("U42")
        repo.save(inc)
        loaded = repo.get_by_id(inc.id)
        assert loaded is not None
        assert loaded.commander_id == "U42"

    def test_resolve_after_reload(self, repo):
        """Resolving a reloaded incident must not raise due to tz mismatch."""
        inc = Incident(title="t", description="d", severity=IncidentSeverity.SEV1)
        repo.save(inc)
        loaded = repo.get_by_id(inc.id)
        assert loaded is not None
        loaded.transition_to(IncidentStatus.RESOLVED)
        assert loaded.duration_seconds is not None

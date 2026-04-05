"""Tests for JobRepository contract (SQLite)."""

from __future__ import annotations

import pytest

from legion.domain.job import Job, JobType
from legion.plumbing.database import create_all, create_engine
from legion.services.job_repository import SQLiteJobRepository


@pytest.fixture()
def repo():
    engine = create_engine("sqlite:///:memory:")
    create_all(engine)
    return SQLiteJobRepository(engine)


class TestJobRepositoryContract:
    def test_save_and_get(self, repo):
        job = Job(
            org_id="org-1", agent_group_id="ag-1", session_id="session-1",
            type=JobType.TRIAGE, payload="alert fired",
        )
        repo.save(job)
        loaded = repo.get_by_id(job.id)
        assert loaded is not None
        assert loaded.payload == "alert fired"
        assert loaded.type == JobType.TRIAGE
        assert loaded.session_id == "session-1"

    def test_get_nonexistent(self, repo):
        assert repo.get_by_id("nope") is None

    def test_list_pending(self, repo):
        j1 = Job(
            org_id="org-1", agent_group_id="ag-1", session_id="session-1",
            type=JobType.TRIAGE, payload="a",
        )
        j2 = Job(
            org_id="org-1", agent_group_id="ag-1", session_id="session-2",
            type=JobType.QUERY, payload="b",
        )
        j3 = Job(
            org_id="org-1", agent_group_id="ag-2", session_id="session-3",
            type=JobType.TRIAGE, payload="c",
        )
        repo.save(j1)
        repo.save(j2)
        repo.save(j3)
        pending = repo.list_pending("ag-1")
        assert len(pending) == 2

        # Dispatched jobs should not appear in pending
        j1.dispatch_to("agent-1")
        repo.save(j1)
        pending = repo.list_pending("ag-1")
        assert len(pending) == 1

    def test_list_by_agent(self, repo):
        j1 = Job(
            org_id="org-1", agent_group_id="ag-1", session_id="session-1",
            type=JobType.TRIAGE, payload="a",
        )
        j1.dispatch_to("agent-1")
        j2 = Job(
            org_id="org-1", agent_group_id="ag-1", session_id="session-2",
            type=JobType.QUERY, payload="b",
        )
        j2.dispatch_to("agent-2")
        repo.save(j1)
        repo.save(j2)
        result = repo.list_by_agent("agent-1")
        assert len(result) == 1
        assert result[0].id == j1.id

    def test_list_active_excludes_terminal(self, repo):
        j1 = Job(
            org_id="org-1", agent_group_id="ag-1", session_id="session-1",
            type=JobType.TRIAGE, payload="a",
        )
        j2 = Job(
            org_id="org-1", agent_group_id="ag-1", session_id="session-2",
            type=JobType.QUERY, payload="b",
        )
        repo.save(j1)
        repo.save(j2)
        assert len(repo.list_active("ag-1")) == 2

        j1.dispatch_to("agent-1")
        j1.start()
        j1.complete("done")
        repo.save(j1)
        active = repo.list_active("ag-1")
        assert len(active) == 1
        assert active[0].id == j2.id

    def test_list_active_no_filter(self, repo):
        j1 = Job(
            org_id="org-1", agent_group_id="ag-1", session_id="session-1",
            type=JobType.TRIAGE, payload="a",
        )
        j2 = Job(
            org_id="org-1", agent_group_id="ag-2", session_id="session-2",
            type=JobType.QUERY, payload="b",
        )
        repo.save(j1)
        repo.save(j2)
        assert len(repo.list_active()) == 2

    def test_lifecycle_after_reload(self, repo):
        """Dispatching a reloaded job must not raise due to tz mismatch."""
        job = Job(
            org_id="org-1", agent_group_id="ag-1", session_id="session-1",
            type=JobType.TRIAGE, payload="alert",
        )
        repo.save(job)
        loaded = repo.get_by_id(job.id)
        assert loaded is not None
        loaded.dispatch_to("agent-1")
        assert loaded.dispatched_at is not None
        assert loaded.dispatched_at.tzinfo is not None

    def test_round_trips_event_and_required_capabilities(self, repo):
        job = Job(
            org_id="org-1",
            agent_group_id="ag-1",
            session_id="session-1",
            event_id="event-1",
            required_capabilities=["kubernetes", "postgresql"],
            type=JobType.INVESTIGATE,
            payload="investigate alert",
        )
        repo.save(job)
        loaded = repo.get_by_id(job.id)
        assert loaded is not None
        assert loaded.event_id == "event-1"
        assert loaded.required_capabilities == ["kubernetes", "postgresql"]

"""Tests for SessionRepository contract (SQLite)."""

import pytest

from legion.domain.session import Session, SessionStatus
from legion.plumbing.database import create_all, create_engine
from legion.services.session_repository import SQLiteSessionRepository


@pytest.fixture()
def repo():
    engine = create_engine("sqlite:///:memory:")
    create_all(engine)
    return SQLiteSessionRepository(engine)


class TestSessionRepositoryContract:
    def test_save_and_get(self, repo):
        s = Session(
            org_id="org-1", agent_group_id="ag-1",
        )
        repo.save(s)
        loaded = repo.get_by_id(s.id)
        assert loaded is not None
        assert loaded.org_id == "org-1"

    def test_get_nonexistent(self, repo):
        assert repo.get_by_id("nope") is None

    def test_list_active(self, repo):
        s1 = Session(org_id="org-1", agent_group_id="ag-1")
        s2 = Session(org_id="org-1", agent_group_id="ag-1")
        s3 = Session(org_id="org-1", agent_group_id="ag-2")
        repo.save(s1)
        repo.save(s2)
        repo.save(s3)
        assert len(repo.list_active("ag-1")) == 2
        assert len(repo.list_active()) == 3

    def test_list_active_excludes_closed(self, repo):
        s = Session(org_id="org-1", agent_group_id="ag-1")
        repo.save(s)
        s.close()
        repo.save(s)
        assert len(repo.list_active("ag-1")) == 0

    def test_lifecycle_after_reload(self, repo):
        """Closing a reloaded session must not raise due to tz mismatch."""
        s = Session(org_id="org-1", agent_group_id="ag-1")
        repo.save(s)
        loaded = repo.get_by_id(s.id)
        assert loaded is not None
        loaded.close()
        assert loaded.status == SessionStatus.CLOSED
        assert loaded.last_activity.tzinfo is not None

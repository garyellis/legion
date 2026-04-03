"""Tests for SessionRepository contract (InMemory + SQLite)."""

import pytest

from legion.domain.session import Session, SessionStatus
from legion.plumbing.database import create_all, create_engine
from legion.services.session_repository import (
    InMemorySessionRepository,
    SQLiteSessionRepository,
)


@pytest.fixture(params=["memory", "sqlite"])
def repo(request):
    if request.param == "memory":
        return InMemorySessionRepository()
    engine = create_engine("sqlite:///:memory:")
    create_all(engine)
    return SQLiteSessionRepository(engine)


class TestSessionRepositoryContract:
    def test_save_and_get(self, repo):
        s = Session(
            org_id="org-1", cluster_group_id="cg-1",
            slack_channel_id="C123", slack_thread_ts="1234.5678",
        )
        repo.save(s)
        loaded = repo.get_by_id(s.id)
        assert loaded is not None
        assert loaded.org_id == "org-1"
        assert loaded.slack_channel_id == "C123"

    def test_get_nonexistent(self, repo):
        assert repo.get_by_id("nope") is None

    def test_get_active_by_thread(self, repo):
        s = Session(
            org_id="org-1", cluster_group_id="cg-1",
            slack_channel_id="C123", slack_thread_ts="1234.5678",
        )
        repo.save(s)
        found = repo.get_active_by_thread("C123", "1234.5678")
        assert found is not None
        assert found.id == s.id

    def test_get_active_by_thread_returns_none_for_closed(self, repo):
        s = Session(
            org_id="org-1", cluster_group_id="cg-1",
            slack_channel_id="C123", slack_thread_ts="1234.5678",
        )
        s.close()
        repo.save(s)
        assert repo.get_active_by_thread("C123", "1234.5678") is None

    def test_get_active_by_thread_no_match(self, repo):
        assert repo.get_active_by_thread("C999", "0000.0000") is None

    def test_list_active(self, repo):
        s1 = Session(org_id="org-1", cluster_group_id="cg-1")
        s2 = Session(org_id="org-1", cluster_group_id="cg-1")
        s3 = Session(org_id="org-1", cluster_group_id="cg-2")
        repo.save(s1)
        repo.save(s2)
        repo.save(s3)
        assert len(repo.list_active("cg-1")) == 2
        assert len(repo.list_active()) == 3

    def test_list_active_excludes_closed(self, repo):
        s = Session(org_id="org-1", cluster_group_id="cg-1")
        repo.save(s)
        s.close()
        repo.save(s)
        assert len(repo.list_active("cg-1")) == 0

    def test_lifecycle_after_reload(self, repo):
        """Closing a reloaded session must not raise due to tz mismatch."""
        s = Session(org_id="org-1", cluster_group_id="cg-1")
        repo.save(s)
        loaded = repo.get_by_id(s.id)
        assert loaded is not None
        loaded.close()
        assert loaded.status == SessionStatus.CLOSED
        assert loaded.last_activity.tzinfo is not None

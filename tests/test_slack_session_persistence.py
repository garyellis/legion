"""Contract tests for Slack session link persistence."""

from __future__ import annotations

import pytest

from legion.plumbing.database import create_all, create_engine
from legion.slack.session.models import SlackSessionLink
from legion.slack.session.persistence import SQLiteSlackSessionLinkRepository


@pytest.fixture()
def repo():
    engine = create_engine("sqlite:///:memory:")
    create_all(engine)
    return SQLiteSlackSessionLinkRepository(engine)


class TestSlackSessionLinkPersistence:
    def test_save_and_lookup_by_thread(self, repo):
        repo.save(SlackSessionLink(channel_id="C123", thread_ts="1234.5678", session_id="session-1"))

        assert repo.get_session_id("C123", "1234.5678") == "session-1"
        found = repo.get_by_session_id("session-1")
        assert found is not None
        assert found.channel_id == "C123"
        assert found.thread_ts == "1234.5678"

    def test_save_relinks_existing_thread(self, repo):
        repo.save(SlackSessionLink(channel_id="C123", thread_ts="1234.5678", session_id="session-1"))
        repo.save(SlackSessionLink(channel_id="C123", thread_ts="1234.5678", session_id="session-2"))

        assert repo.get_session_id("C123", "1234.5678") == "session-2"
        assert repo.get_by_session_id("session-1") is None
        assert repo.get_by_session_id("session-2") is not None

    def test_delete_by_session_id(self, repo):
        repo.save(SlackSessionLink(channel_id="C123", thread_ts="1234.5678", session_id="session-1"))
        repo.delete_by_session_id("session-1")

        assert repo.get_session_id("C123", "1234.5678") is None
        assert repo.get_by_session_id("session-1") is None


"""Tests for MessageRepository contract (SQLite)."""

from __future__ import annotations

import pytest

from legion.domain.message import AuthorType, Message, MessageType
from legion.plumbing.database import create_all, create_engine
from legion.services.message_repository import SQLiteMessageRepository


@pytest.fixture()
def repo():
    engine = create_engine("sqlite:///:memory:")
    create_all(engine)
    return SQLiteMessageRepository(engine)


class TestMessageRepositoryContract:
    def test_save_and_get(self, repo):
        message = Message(
            org_id="org-1",
            session_id="session-1",
            author_id="user-1",
            author_type=AuthorType.HUMAN,
            message_type=MessageType.HUMAN_MESSAGE,
            content="hello",
        )
        repo.save(message)
        loaded = repo.get_by_id(message.id)
        assert loaded is not None
        assert loaded.content == "hello"
        assert loaded.session_id == "session-1"

    def test_list_by_session(self, repo):
        message_one = Message(
            org_id="org-1",
            session_id="session-1",
            author_id="user-1",
            author_type=AuthorType.HUMAN,
            message_type=MessageType.HUMAN_MESSAGE,
            content="first",
        )
        message_two = Message(
            org_id="org-1",
            session_id="session-1",
            author_id="agent-1",
            author_type=AuthorType.AGENT,
            message_type=MessageType.AGENT_FINDING,
            content="second",
        )
        repo.save(message_one)
        repo.save(message_two)
        messages = repo.list_by_session("session-1")
        assert [message.content for message in messages] == ["first", "second"]

    def test_list_by_job(self, repo):
        message = Message(
            org_id="org-1",
            session_id="session-1",
            job_id="job-1",
            author_id="system",
            author_type=AuthorType.SYSTEM,
            message_type=MessageType.STATUS_UPDATE,
            content="job started",
        )
        repo.save(message)
        messages = repo.list_by_job("job-1")
        assert len(messages) == 1
        assert messages[0].id == message.id

    def test_metadata_round_trips_json(self, repo):
        message = Message(
            org_id="org-1",
            session_id="session-1",
            author_id="agent-1",
            author_type=AuthorType.AGENT,
            message_type=MessageType.TOOL_SUMMARY,
            content="tool finished",
            metadata={
                "tool": "kubectl",
                "success": True,
                "count": 2,
                "details": {"namespace": "prod"},
                "items": ["pod-a", "pod-b"],
            },
        )
        repo.save(message)
        loaded = repo.get_by_id(message.id)
        assert loaded is not None
        assert loaded.metadata == {
            "tool": "kubectl",
            "success": True,
            "count": 2,
            "details": {"namespace": "prod"},
            "items": ["pod-a", "pod-b"],
        }

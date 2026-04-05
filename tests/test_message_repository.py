"""Tests for MessageRepository contract (SQLite)."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

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

    def test_list_by_session_paginated(self, repo):
        base_time = datetime(2026, 1, 1, tzinfo=timezone.utc)
        for i in range(5):
            msg = Message(
                org_id="org-1",
                session_id="session-p",
                author_id="user-1",
                author_type=AuthorType.HUMAN,
                message_type=MessageType.HUMAN_MESSAGE,
                content=f"msg-{i}",
                created_at=base_time + timedelta(seconds=i),
            )
            repo.save(msg)

        # First page
        page1 = repo.list_by_session_paginated("session-p", page_size=2)
        assert len(page1.items) == 2
        assert page1.has_more is True
        assert page1.next_cursor is not None
        assert [m.content for m in page1.items] == ["msg-0", "msg-1"]

        # Second page
        page2 = repo.list_by_session_paginated(
            "session-p", cursor=page1.next_cursor, page_size=2
        )
        assert len(page2.items) == 2
        assert page2.has_more is True
        assert [m.content for m in page2.items] == ["msg-2", "msg-3"]

        # Third page — last item, no more
        page3 = repo.list_by_session_paginated(
            "session-p", cursor=page2.next_cursor, page_size=2
        )
        assert len(page3.items) == 1
        assert page3.has_more is False
        assert page3.next_cursor is None
        assert [m.content for m in page3.items] == ["msg-4"]

    def test_list_by_job_paginated(self, repo):
        base_time = datetime(2026, 2, 1, tzinfo=timezone.utc)
        for i in range(3):
            msg = Message(
                org_id="org-1",
                session_id="session-1",
                job_id="job-p",
                author_id="agent-1",
                author_type=AuthorType.AGENT,
                message_type=MessageType.AGENT_FINDING,
                content=f"finding-{i}",
                created_at=base_time + timedelta(seconds=i),
            )
            repo.save(msg)

        page1 = repo.list_by_job_paginated("job-p", page_size=2)
        assert len(page1.items) == 2
        assert page1.has_more is True
        assert [m.content for m in page1.items] == ["finding-0", "finding-1"]

        page2 = repo.list_by_job_paginated(
            "job-p", cursor=page1.next_cursor, page_size=2
        )
        assert len(page2.items) == 1
        assert page2.has_more is False

    def test_list_by_job_paginated_malformed_cursor(self, repo):
        with pytest.raises(ValueError, match="Invalid pagination cursor"):
            repo.list_by_job_paginated("job-1", cursor="not-a-valid-cursor")

    def test_purge_before(self, repo):
        now = datetime.now(timezone.utc)
        old_msg = Message(
            org_id="org-1",
            session_id="session-1",
            author_id="system",
            author_type=AuthorType.SYSTEM,
            message_type=MessageType.SYSTEM_EVENT,
            content="old event",
            created_at=now - timedelta(days=30),
        )
        recent_msg = Message(
            org_id="org-1",
            session_id="session-1",
            author_id="system",
            author_type=AuthorType.SYSTEM,
            message_type=MessageType.SYSTEM_EVENT,
            content="recent event",
            created_at=now,
        )
        repo.save(old_msg)
        repo.save(recent_msg)

        cutoff = now - timedelta(days=7)
        deleted = repo.purge_before(cutoff)
        assert deleted == 1

        # Old message gone, recent message remains
        assert repo.get_by_id(old_msg.id) is None
        assert repo.get_by_id(recent_msg.id) is not None

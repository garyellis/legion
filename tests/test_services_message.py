"""Tests for MessageService."""

from __future__ import annotations

import pytest

from legion.domain.message import AuthorType, Message, MessageType
from legion.plumbing.database import create_all, create_engine
from legion.services.message_repository import SQLiteMessageRepository
from legion.services.message_service import MessageService


@pytest.fixture()
def _engine():
    engine = create_engine("sqlite:///:memory:")
    create_all(engine)
    return engine


@pytest.fixture()
def repo(_engine):
    return SQLiteMessageRepository(_engine)


@pytest.fixture()
def service(repo):
    return MessageService(repo)


def _make_message(**overrides) -> Message:
    defaults = dict(
        org_id="org-1",
        session_id="session-1",
        author_id="user-1",
        author_type=AuthorType.HUMAN,
        message_type=MessageType.HUMAN_MESSAGE,
        content="hello world",
    )
    defaults.update(overrides)
    return Message(**defaults)


class TestMessageServiceEmit:
    def test_emit_persists_message(self, service, repo):
        message = _make_message()
        service.emit(message)

        loaded = repo.get_by_id(message.id)
        assert loaded is not None
        assert loaded.content == "hello world"
        assert loaded.session_id == "session-1"

    def test_emit_fires_on_message_created_callback(self, repo):
        received = []
        svc = MessageService(repo, on_message_created=lambda m: received.append(m))

        message = _make_message()
        svc.emit(message)

        assert len(received) == 1
        assert received[0].id == message.id

    def test_emit_works_without_callback(self, repo):
        svc = MessageService(repo, on_message_created=None)
        message = _make_message()

        # Should not raise
        result = svc.emit(message)
        assert result.id == message.id

    def test_emit_suppresses_callback_exception(self, repo):
        """Callback failure must not propagate — message is already persisted."""
        def exploding_callback(msg):
            raise RuntimeError("Slack API timeout")

        svc = MessageService(repo, on_message_created=exploding_callback)
        message = _make_message()

        # Should NOT raise
        result = svc.emit(message)

        # Message was still persisted
        assert result.id == message.id
        loaded = repo.get_by_id(message.id)
        assert loaded is not None

    def test_emit_returns_the_message(self, service):
        message = _make_message(content="return me")
        result = service.emit(message)

        assert result is message
        assert result.content == "return me"


class TestMessageServiceListBySession:
    def test_list_by_session_delegates_to_repository(self, service):
        msg_a = _make_message(session_id="sess-1", content="first")
        msg_b = _make_message(session_id="sess-1", content="second")
        msg_other = _make_message(session_id="sess-2", content="other")

        service.emit(msg_a)
        service.emit(msg_b)
        service.emit(msg_other)

        messages = service.list_by_session("sess-1")
        assert len(messages) == 2
        assert [m.content for m in messages] == ["first", "second"]


class TestMessageServiceListByJob:
    def test_list_by_job_delegates_to_repository(self, service):
        msg_a = _make_message(job_id="job-1", content="job msg")
        msg_b = _make_message(job_id="job-2", content="other job")

        service.emit(msg_a)
        service.emit(msg_b)

        messages = service.list_by_job("job-1")
        assert len(messages) == 1
        assert messages[0].content == "job msg"
        assert messages[0].job_id == "job-1"

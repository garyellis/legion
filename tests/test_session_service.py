"""Tests for SessionService."""

import pytest

from legion.domain.session import SessionStatus
from legion.plumbing.database import create_all, create_engine
from legion.services.exceptions import SessionError
from legion.services.fleet_repository import SQLiteFleetRepository
from legion.services.session_repository import SQLiteSessionRepository
from legion.services.session_service import SessionService


@pytest.fixture()
def _engine():
    engine = create_engine("sqlite:///:memory:")
    create_all(engine)
    return engine


@pytest.fixture()
def session_repo(_engine):
    return SQLiteSessionRepository(_engine)


@pytest.fixture()
def fleet_repo(_engine):
    return SQLiteFleetRepository(_engine)


class InMemorySessionLinkRepository:
    def __init__(self) -> None:
        self._links: dict[tuple[str, str], str] = {}

    def get_session_id(self, channel_id: str, thread_ts: str) -> str | None:
        return self._links.get((channel_id, thread_ts))

    def save_link(self, session_id: str, channel_id: str, thread_ts: str) -> None:
        self._links[(channel_id, thread_ts)] = session_id


@pytest.fixture()
def session_link_repo():
    return InMemorySessionLinkRepository()


@pytest.fixture()
def service(session_repo, fleet_repo, session_link_repo):
    return SessionService(session_repo, fleet_repo, session_link_repo)


class TestSessionService:
    def test_get_or_create_new(self, service, session_link_repo):
        session, created = service.get_or_create(
            "org-1", "ag-1", "C123", "1234.5678",
        )
        assert created is True
        assert session.org_id == "org-1"
        assert session.agent_group_id == "ag-1"
        assert session.status == SessionStatus.ACTIVE
        assert session_link_repo.get_session_id("C123", "1234.5678") == session.id

    def test_get_or_create_returns_existing(self, service):
        s1, created1 = service.get_or_create("org-1", "ag-1", "C123", "1234.5678")
        s2, created2 = service.get_or_create("org-1", "ag-1", "C123", "1234.5678")
        assert created1 is True
        assert created2 is False
        assert s1.id == s2.id

    def test_get_or_create_new_after_close(self, service, session_link_repo):
        s1, _ = service.get_or_create("org-1", "ag-1", "C123", "1234.5678")
        service.close_session(s1.id)
        s2, created = service.get_or_create("org-1", "ag-1", "C123", "1234.5678")
        assert created is True
        assert s2.id != s1.id
        assert session_link_repo.get_session_id("C123", "1234.5678") == s2.id

    def test_pin_agent(self, service):
        session, _ = service.get_or_create("org-1", "ag-1", "C123", "1234.5678")
        updated = service.pin_agent(session.id, "agent-1")
        assert updated.agent_id == "agent-1"

    def test_pin_agent_nonexistent_raises(self, service):
        with pytest.raises(SessionError):
            service.pin_agent("nope", "agent-1")

    def test_close_session(self, service):
        session, _ = service.get_or_create("org-1", "ag-1", "C123", "1234.5678")
        closed = service.close_session(session.id)
        assert closed.status == SessionStatus.CLOSED

    def test_close_nonexistent_raises(self, service):
        with pytest.raises(SessionError):
            service.close_session("nope")

    def test_touch(self, service):
        session, _ = service.get_or_create("org-1", "ag-1", "C123", "1234.5678")
        original = session.last_activity
        updated = service.touch(session.id)
        assert updated.last_activity >= original

    def test_touch_nonexistent_raises(self, service):
        with pytest.raises(SessionError):
            service.touch("nope")

    def test_on_session_created_callback(self, session_repo, fleet_repo, session_link_repo):
        created_sessions = []
        svc = SessionService(
            session_repo, fleet_repo, session_link_repo,
            on_session_created=lambda s: created_sessions.append(s.id),
        )
        session, _ = svc.get_or_create("org-1", "ag-1", "C123", "1234.5678")
        assert session.id in created_sessions

    def test_callback_not_fired_on_existing(self, session_repo, fleet_repo, session_link_repo):
        created_sessions = []
        svc = SessionService(
            session_repo, fleet_repo, session_link_repo,
            on_session_created=lambda s: created_sessions.append(s.id),
        )
        svc.get_or_create("org-1", "ag-1", "C123", "1234.5678")
        svc.get_or_create("org-1", "ag-1", "C123", "1234.5678")
        assert len(created_sessions) == 1

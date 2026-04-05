"""Tests for MaintenanceService — retention-based purging of audit events and messages."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from legion.domain.audit_event import AuditAction, AuditEvent
from legion.domain.message import AuthorType, Message, MessageType
from legion.plumbing.database import create_all, create_engine
from legion.services.audit_event_repository import SQLiteAuditEventRepository
from legion.services.maintenance_service import MaintenanceService
from legion.services.message_repository import SQLiteMessageRepository


def _make_event(**overrides) -> AuditEvent:
    defaults = {
        "job_id": "job-1",
        "agent_id": "agent-1",
        "session_id": "session-1",
        "org_id": "org-1",
        "action": AuditAction.TOOL_CALL,
    }
    defaults.update(overrides)
    return AuditEvent(**defaults)


def _make_message(**overrides) -> Message:
    defaults = {
        "org_id": "org-1",
        "session_id": "session-1",
        "author_id": "user-1",
        "author_type": AuthorType.HUMAN,
        "message_type": MessageType.HUMAN_MESSAGE,
        "content": "test message",
    }
    defaults.update(overrides)
    return Message(**defaults)


@pytest.fixture()
def engine():
    eng = create_engine("sqlite:///:memory:")
    create_all(eng)
    return eng


@pytest.fixture()
def audit_repo(engine):
    return SQLiteAuditEventRepository(engine)


@pytest.fixture()
def message_repo(engine):
    return SQLiteMessageRepository(engine)


@pytest.fixture()
def service(audit_repo, message_repo):
    return MaintenanceService(
        audit_repo,
        message_repo,
        audit_retention_days=90,
        message_retention_days=180,
    )


class TestMaintenanceService:
    def test_audit_purge_deletes_old_events(self, audit_repo, service):
        now = datetime.now(timezone.utc)
        old_event = _make_event(
            id="old-audit",
            created_at=now - timedelta(days=120),
        )
        recent_event = _make_event(
            id="recent-audit",
            created_at=now - timedelta(days=30),
        )
        audit_repo.save(old_event)
        audit_repo.save(recent_event)

        deleted = service.run_audit_purge()

        assert deleted == 1
        remaining = audit_repo.list_by_job("job-1")
        assert len(remaining) == 1
        assert remaining[0].id == "recent-audit"

    def test_message_purge_deletes_old_messages(self, message_repo, service):
        now = datetime.now(timezone.utc)
        old_msg = _make_message(
            id="old-msg",
            created_at=now - timedelta(days=200),
        )
        recent_msg = _make_message(
            id="recent-msg",
            created_at=now - timedelta(days=30),
        )
        message_repo.save(old_msg)
        message_repo.save(recent_msg)

        deleted = service.run_message_purge()

        assert deleted == 1
        remaining = message_repo.list_by_session("session-1")
        assert len(remaining) == 1
        assert remaining[0].id == "recent-msg"

    def test_run_all_returns_counts(self, audit_repo, message_repo, service):
        now = datetime.now(timezone.utc)
        # Two old audit events
        for i in range(2):
            audit_repo.save(_make_event(
                id=f"old-audit-{i}",
                created_at=now - timedelta(days=120),
            ))
        # One old message
        message_repo.save(_make_message(
            id="old-msg",
            created_at=now - timedelta(days=200),
        ))

        result = service.run_all()

        assert result == {
            "audit_events_purged": 2,
            "messages_purged": 1,
        }

    def test_audit_retention_below_minimum_raises(self, audit_repo, message_repo):
        with pytest.raises(ValueError, match="audit_retention_days must be >= 30"):
            MaintenanceService(
                audit_repo,
                message_repo,
                audit_retention_days=10,
            )

    def test_message_retention_below_minimum_raises(self, audit_repo, message_repo):
        with pytest.raises(ValueError, match="message_retention_days must be >= 30"):
            MaintenanceService(
                audit_repo,
                message_repo,
                message_retention_days=10,
            )

    def test_purge_with_nothing_to_delete(self, service):
        result = service.run_all()

        assert result == {
            "audit_events_purged": 0,
            "messages_purged": 0,
        }

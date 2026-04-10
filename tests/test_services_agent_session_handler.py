"""Unit tests for AgentSessionHandler — the extracted protocol/business logic layer."""

from __future__ import annotations

import logging
from typing import Any
from unittest.mock import MagicMock

import pytest

from legion.domain.audit_event import AuditAction, AuditEvent
from legion.domain.job import Job, JobStatus, JobType
from legion.domain.message import AuthorType, Message, MessageType
from legion.domain.protocol import (
    AuditEventMessage,
    HeartbeatMessage,
    JobFailedMessage,
    JobProgressMessage,
    JobResultMessage,
    JobStartedMessage,
    MessageEmitMessage,
)
from legion.services.agent_session_handler import (
    AgentSessionHandler,
    HandleResult,
)
from legion.services.exceptions import DispatchError


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

JOB_ID = "job-001"
AGENT_ID = "agent-001"
OTHER_AGENT_ID = "agent-other"
SESSION_ID = "session-001"
ORG_ID = "org-001"
GROUP_ID = "ag-001"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_job(**overrides: Any) -> Job:
    defaults: dict[str, Any] = dict(
        id=JOB_ID,
        org_id=ORG_ID,
        agent_group_id=GROUP_ID,
        session_id=SESSION_ID,
        agent_id=AGENT_ID,
        type=JobType.QUERY,
        status=JobStatus.RUNNING,
        payload="check pods",
    )
    defaults.update(overrides)
    return Job(**defaults)


def _make_handler(
    *,
    job: Job | None = None,
    message_service: Any | None = None,
    audit_service: Any | None = None,
    dispatch_service: Any | None = None,
    job_repo: Any | None = None,
) -> AgentSessionHandler:
    """Build an AgentSessionHandler with mock dependencies."""
    if dispatch_service is None:
        dispatch_service = MagicMock()
    if job_repo is None:
        job_repo = MagicMock()
        job_repo.get_by_id.return_value = job
    return AgentSessionHandler(
        dispatch_service=dispatch_service,
        job_repo=job_repo,
        message_service=message_service,
        audit_service=audit_service,
    )


# ---------------------------------------------------------------------------
# Heartbeat
# ---------------------------------------------------------------------------


class TestHeartbeat:
    def test_heartbeat_calls_dispatch_service(self) -> None:
        dispatch = MagicMock()
        handler = _make_handler(dispatch_service=dispatch)

        result = handler.handle(HeartbeatMessage(), AGENT_ID, GROUP_ID)

        dispatch.heartbeat.assert_called_once_with(AGENT_ID)
        assert result == HandleResult()
        assert result.dispatch_pending_for_group is None
        assert result.ignored is False


# ---------------------------------------------------------------------------
# JobStarted
# ---------------------------------------------------------------------------


class TestJobStarted:
    def test_job_started_transitions_and_saves(self) -> None:
        job = _make_job(status=JobStatus.DISPATCHED)
        job_repo = MagicMock()
        job_repo.get_by_id.return_value = job
        handler = _make_handler(job_repo=job_repo)

        msg = JobStartedMessage(job_id=JOB_ID)
        result = handler.handle(msg, AGENT_ID, GROUP_ID)

        assert job.status == JobStatus.RUNNING
        job_repo.save.assert_called_once_with(job)
        assert not result.ignored
        assert result.dispatch_pending_for_group is None

    def test_job_started_ignored_when_job_not_found(self) -> None:
        handler = _make_handler(job=None)

        msg = JobStartedMessage(job_id=JOB_ID)
        result = handler.handle(msg, AGENT_ID, GROUP_ID)

        assert result.ignored

    def test_job_started_ignored_when_owned_by_other(self) -> None:
        job = _make_job(agent_id=OTHER_AGENT_ID)
        handler = _make_handler(job=job)

        msg = JobStartedMessage(job_id=JOB_ID)
        result = handler.handle(msg, AGENT_ID, GROUP_ID)

        assert result.ignored


# ---------------------------------------------------------------------------
# JobResult
# ---------------------------------------------------------------------------


class TestJobResult:
    def test_job_result_completes_and_requests_dispatch(self) -> None:
        dispatch = MagicMock()
        handler = _make_handler(dispatch_service=dispatch)

        msg = JobResultMessage(job_id=JOB_ID, result="all pods healthy")
        result = handler.handle(msg, AGENT_ID, GROUP_ID)

        dispatch.complete_job.assert_called_once_with(
            JOB_ID, "all pods healthy", agent_id=AGENT_ID,
        )
        assert result.dispatch_pending_for_group == GROUP_ID
        assert not result.ignored

    def test_job_result_ignored_on_dispatch_error(self) -> None:
        dispatch = MagicMock()
        dispatch.complete_job.side_effect = DispatchError("not found")
        handler = _make_handler(dispatch_service=dispatch)

        msg = JobResultMessage(job_id=JOB_ID, result="result")
        result = handler.handle(msg, AGENT_ID, GROUP_ID)

        assert result.ignored
        assert result.dispatch_pending_for_group is None


# ---------------------------------------------------------------------------
# JobFailed
# ---------------------------------------------------------------------------


class TestJobFailed:
    def test_job_failed_marks_failed_and_requests_dispatch(self) -> None:
        dispatch = MagicMock()
        handler = _make_handler(dispatch_service=dispatch)

        msg = JobFailedMessage(job_id=JOB_ID, error="timeout")
        result = handler.handle(msg, AGENT_ID, GROUP_ID)

        dispatch.fail_job.assert_called_once_with(
            JOB_ID, "timeout", agent_id=AGENT_ID,
        )
        assert result.dispatch_pending_for_group == GROUP_ID
        assert not result.ignored

    def test_job_failed_ignored_on_dispatch_error(self) -> None:
        dispatch = MagicMock()
        dispatch.fail_job.side_effect = DispatchError("not found")
        handler = _make_handler(dispatch_service=dispatch)

        msg = JobFailedMessage(job_id=JOB_ID, error="timeout")
        result = handler.handle(msg, AGENT_ID, GROUP_ID)

        assert result.ignored
        assert result.dispatch_pending_for_group is None


# ---------------------------------------------------------------------------
# JobProgress
# ---------------------------------------------------------------------------


class TestJobProgress:
    def test_job_progress_logs_info(self, caplog: pytest.LogCaptureFixture) -> None:
        job = _make_job()
        handler = _make_handler(job=job)

        msg = JobProgressMessage(
            job_id=JOB_ID, step="fetching_pods", detail="namespace=default", sequence=1,
        )
        with caplog.at_level(logging.INFO, logger="legion.services.agent_session_handler"):
            result = handler.handle(msg, AGENT_ID, GROUP_ID)

        assert not result.ignored
        progress_records = [r for r in caplog.records if "job_progress" in r.message]
        assert len(progress_records) >= 1
        assert "fetching_pods" in progress_records[0].message
        assert JOB_ID in progress_records[0].message

    def test_job_progress_ignored_when_job_not_found(self) -> None:
        handler = _make_handler(job=None)

        msg = JobProgressMessage(job_id=JOB_ID, step="s", detail="d", sequence=1)
        result = handler.handle(msg, AGENT_ID, GROUP_ID)

        assert result.ignored

    def test_job_progress_ignored_when_owned_by_other(self) -> None:
        job = _make_job(agent_id=OTHER_AGENT_ID)
        handler = _make_handler(job=job)

        msg = JobProgressMessage(job_id=JOB_ID, step="s", detail="d", sequence=1)
        result = handler.handle(msg, AGENT_ID, GROUP_ID)

        assert result.ignored


# ---------------------------------------------------------------------------
# MessageEmit
# ---------------------------------------------------------------------------


class TestMessageEmit:
    def test_message_emit_persists_via_service(self) -> None:
        job = _make_job()
        message_service = MagicMock()
        handler = _make_handler(job=job, message_service=message_service)

        msg = MessageEmitMessage(
            job_id=JOB_ID,
            message_type="AGENT_FINDING",
            content="Found 3 unhealthy pods",
            metadata={"cluster": "prod"},
        )
        result = handler.handle(msg, AGENT_ID, GROUP_ID)

        assert not result.ignored
        message_service.emit.assert_called_once()
        emitted: Message = message_service.emit.call_args[0][0]

        assert isinstance(emitted, Message)
        assert emitted.author_type == AuthorType.AGENT
        assert emitted.author_id == AGENT_ID
        assert emitted.org_id == ORG_ID
        assert emitted.session_id == SESSION_ID
        assert emitted.job_id == JOB_ID
        assert emitted.message_type == MessageType.AGENT_FINDING
        assert emitted.content == "Found 3 unhealthy pods"
        assert emitted.metadata == {"cluster": "prod"}

    def test_message_emit_empty_metadata_default(self) -> None:
        job = _make_job()
        message_service = MagicMock()
        handler = _make_handler(job=job, message_service=message_service)

        msg = MessageEmitMessage(
            job_id=JOB_ID, message_type="STATUS_UPDATE", content="status",
        )
        handler.handle(msg, AGENT_ID, GROUP_ID)

        emitted: Message = message_service.emit.call_args[0][0]
        assert emitted.metadata == {}

    def test_message_emit_uses_job_agent_id_over_caller_agent_id(self) -> None:
        """When job.agent_id is set, it's preferred over the caller's agent_id."""
        job = _make_job(agent_id=AGENT_ID)
        message_service = MagicMock()
        handler = _make_handler(job=job, message_service=message_service)

        msg = MessageEmitMessage(
            job_id=JOB_ID, message_type="AGENT_FINDING", content="c",
        )
        handler.handle(msg, AGENT_ID, GROUP_ID)

        emitted: Message = message_service.emit.call_args[0][0]
        assert emitted.author_id == AGENT_ID

    def test_message_emit_without_service_skips_gracefully(
        self, caplog: pytest.LogCaptureFixture,
    ) -> None:
        job = _make_job()
        handler = _make_handler(job=job, message_service=None)

        msg = MessageEmitMessage(
            job_id=JOB_ID, message_type="AGENT_FINDING", content="some content",
        )
        with caplog.at_level(logging.DEBUG, logger="legion.services.agent_session_handler"):
            result = handler.handle(msg, AGENT_ID, GROUP_ID)

        assert not result.ignored
        assert any("message_service not available" in r.message for r in caplog.records)
        debug_records = [
            r for r in caplog.records if "message_service not available" in r.message
        ]
        assert all(r.levelno == logging.DEBUG for r in debug_records)

    def test_message_emit_skipped_when_job_owned_by_other(self) -> None:
        job = _make_job(agent_id=OTHER_AGENT_ID)
        message_service = MagicMock()
        handler = _make_handler(job=job, message_service=message_service)

        msg = MessageEmitMessage(
            job_id=JOB_ID, message_type="AGENT_FINDING", content="should not persist",
        )
        result = handler.handle(msg, AGENT_ID, GROUP_ID)

        assert result.ignored
        message_service.emit.assert_not_called()

    def test_message_emit_skipped_when_job_not_found(self) -> None:
        message_service = MagicMock()
        handler = _make_handler(job=None, message_service=message_service)

        msg = MessageEmitMessage(
            job_id=JOB_ID, message_type="AGENT_FINDING", content="should not persist",
        )
        result = handler.handle(msg, AGENT_ID, GROUP_ID)

        assert result.ignored
        message_service.emit.assert_not_called()

    def test_message_emit_exception_is_caught_and_logged(
        self, caplog: pytest.LogCaptureFixture,
    ) -> None:
        job = _make_job()
        message_service = MagicMock()
        message_service.emit.side_effect = RuntimeError("db error")
        handler = _make_handler(job=job, message_service=message_service)

        msg = MessageEmitMessage(
            job_id=JOB_ID, message_type="AGENT_FINDING", content="c",
        )
        with caplog.at_level(logging.WARNING, logger="legion.services.agent_session_handler"):
            result = handler.handle(msg, AGENT_ID, GROUP_ID)

        assert not result.ignored  # still returns OK — failure is logged, not raised
        assert any("Failed to persist message_emit" in r.message for r in caplog.records)


# ---------------------------------------------------------------------------
# AuditEvent
# ---------------------------------------------------------------------------


class TestAuditEvent:
    def test_audit_event_persists_via_service(self) -> None:
        job = _make_job()
        audit_service = MagicMock()
        handler = _make_handler(job=job, audit_service=audit_service)

        msg = AuditEventMessage(
            job_id=JOB_ID,
            tool_name="kubectl_get_pods",
            tool_input="--namespace default",
            tool_output="NAME  READY  STATUS\npod-1  1/1  Running",
            duration_ms=150,
            sequence=1,
        )
        result = handler.handle(msg, AGENT_ID, GROUP_ID)

        assert not result.ignored
        audit_service.emit.assert_called_once()
        emitted: AuditEvent = audit_service.emit.call_args[0][0]

        assert isinstance(emitted, AuditEvent)
        assert emitted.action == AuditAction.TOOL_CALL
        assert emitted.agent_id == AGENT_ID
        assert emitted.job_id == JOB_ID
        assert emitted.session_id == SESSION_ID
        assert emitted.org_id == ORG_ID
        assert emitted.tool_name == "kubectl_get_pods"
        assert emitted.input == {"raw": "--namespace default"}
        assert emitted.output == {"raw": "NAME  READY  STATUS\npod-1  1/1  Running"}
        assert emitted.duration_ms == 150

    def test_audit_event_maps_known_action(self) -> None:
        job = _make_job()
        audit_service = MagicMock()
        handler = _make_handler(job=job, audit_service=audit_service)

        msg = AuditEventMessage(
            job_id=JOB_ID,
            tool_name="llm_router",
            tool_input="prompt",
            tool_output="decision",
            duration_ms=50,
            sequence=1,
            action="LLM_DECISION",
        )
        handler.handle(msg, AGENT_ID, GROUP_ID)

        emitted: AuditEvent = audit_service.emit.call_args[0][0]
        assert emitted.action == AuditAction.LLM_DECISION

    def test_audit_event_maps_error_to_output(self) -> None:
        job = _make_job()
        audit_service = MagicMock()
        handler = _make_handler(job=job, audit_service=audit_service)

        msg = AuditEventMessage(
            job_id=JOB_ID,
            tool_name="kubectl_get_pods",
            tool_input="--namespace default",
            tool_output="partial output",
            duration_ms=200,
            sequence=1,
            error="connection refused",
        )
        handler.handle(msg, AGENT_ID, GROUP_ID)

        emitted: AuditEvent = audit_service.emit.call_args[0][0]
        assert emitted.output == {"raw": "partial output", "error": "connection refused"}

    def test_audit_event_output_with_only_error(self) -> None:
        """When tool_output is present but error is also set, both appear in output."""
        job = _make_job()
        audit_service = MagicMock()
        handler = _make_handler(job=job, audit_service=audit_service)

        msg = AuditEventMessage(
            job_id=JOB_ID,
            tool_name="tool",
            tool_input="in",
            tool_output="out",
            duration_ms=10,
            sequence=1,
            error="err",
        )
        handler.handle(msg, AGENT_ID, GROUP_ID)

        emitted: AuditEvent = audit_service.emit.call_args[0][0]
        assert emitted.output == {"raw": "out", "error": "err"}

    def test_audit_event_output_without_error(self) -> None:
        """When error is None, output dict has only 'raw'."""
        job = _make_job()
        audit_service = MagicMock()
        handler = _make_handler(job=job, audit_service=audit_service)

        msg = AuditEventMessage(
            job_id=JOB_ID,
            tool_name="tool",
            tool_input="in",
            tool_output="out",
            duration_ms=10,
            sequence=1,
            error=None,
        )
        handler.handle(msg, AGENT_ID, GROUP_ID)

        emitted: AuditEvent = audit_service.emit.call_args[0][0]
        assert emitted.output == {"raw": "out"}

    def test_audit_event_unknown_action_defaults_to_tool_call(
        self, caplog: pytest.LogCaptureFixture,
    ) -> None:
        job = _make_job()
        audit_service = MagicMock()
        handler = _make_handler(job=job, audit_service=audit_service)

        msg = AuditEventMessage(
            job_id=JOB_ID,
            tool_name="some_tool",
            tool_input="in",
            tool_output="out",
            duration_ms=10,
            sequence=1,
            action="UNKNOWN_ACTION",
        )
        with caplog.at_level(logging.WARNING, logger="legion.services.agent_session_handler"):
            handler.handle(msg, AGENT_ID, GROUP_ID)

        emitted: AuditEvent = audit_service.emit.call_args[0][0]
        assert emitted.action == AuditAction.TOOL_CALL
        assert any("Unknown audit action" in r.message for r in caplog.records)

    def test_audit_event_without_service_skips_gracefully(
        self, caplog: pytest.LogCaptureFixture,
    ) -> None:
        job = _make_job()
        handler = _make_handler(job=job, audit_service=None)

        msg = AuditEventMessage(
            job_id=JOB_ID,
            tool_name="kubectl_get_pods",
            tool_input="input",
            tool_output="output",
            duration_ms=10,
            sequence=1,
        )
        with caplog.at_level(logging.DEBUG, logger="legion.services.agent_session_handler"):
            result = handler.handle(msg, AGENT_ID, GROUP_ID)

        assert not result.ignored
        assert any("audit_service not available" in r.message for r in caplog.records)
        debug_records = [
            r for r in caplog.records if "audit_service not available" in r.message
        ]
        assert all(r.levelno == logging.DEBUG for r in debug_records)

    def test_audit_event_populates_fields_from_job(self) -> None:
        """Verify session_id and org_id are sourced from the job, not the message."""
        job = _make_job(session_id="sess-custom", org_id="org-custom")
        audit_service = MagicMock()
        handler = _make_handler(job=job, audit_service=audit_service)

        msg = AuditEventMessage(
            job_id=JOB_ID,
            tool_name="tool",
            tool_input="in",
            tool_output="out",
            duration_ms=5,
            sequence=1,
        )
        handler.handle(msg, AGENT_ID, GROUP_ID)

        emitted: AuditEvent = audit_service.emit.call_args[0][0]
        assert emitted.session_id == "sess-custom"
        assert emitted.org_id == "org-custom"

    def test_audit_event_skipped_when_job_owned_by_other(self) -> None:
        job = _make_job(agent_id=OTHER_AGENT_ID)
        audit_service = MagicMock()
        handler = _make_handler(job=job, audit_service=audit_service)

        msg = AuditEventMessage(
            job_id=JOB_ID,
            tool_name="tool",
            tool_input="in",
            tool_output="out",
            duration_ms=5,
            sequence=1,
        )
        result = handler.handle(msg, AGENT_ID, GROUP_ID)

        assert result.ignored
        audit_service.emit.assert_not_called()

    def test_audit_event_skipped_when_job_not_found(self) -> None:
        audit_service = MagicMock()
        handler = _make_handler(job=None, audit_service=audit_service)

        msg = AuditEventMessage(
            job_id=JOB_ID,
            tool_name="tool",
            tool_input="in",
            tool_output="out",
            duration_ms=5,
            sequence=1,
        )
        result = handler.handle(msg, AGENT_ID, GROUP_ID)

        assert result.ignored
        audit_service.emit.assert_not_called()

    def test_audit_event_exception_is_caught_and_logged(
        self, caplog: pytest.LogCaptureFixture,
    ) -> None:
        job = _make_job()
        audit_service = MagicMock()
        audit_service.emit.side_effect = RuntimeError("db error")
        handler = _make_handler(job=job, audit_service=audit_service)

        msg = AuditEventMessage(
            job_id=JOB_ID,
            tool_name="tool",
            tool_input="in",
            tool_output="out",
            duration_ms=10,
            sequence=1,
        )
        with caplog.at_level(logging.WARNING, logger="legion.services.agent_session_handler"):
            result = handler.handle(msg, AGENT_ID, GROUP_ID)

        assert not result.ignored
        assert any("Failed to persist audit_event" in r.message for r in caplog.records)

    def test_audit_event_all_known_actions(self) -> None:
        """Every AuditAction enum value is accepted without fallback."""
        for action in AuditAction:
            job = _make_job()
            audit_service = MagicMock()
            handler = _make_handler(job=job, audit_service=audit_service)

            msg = AuditEventMessage(
                job_id=JOB_ID,
                tool_name="t",
                tool_input="i",
                tool_output="o",
                duration_ms=1,
                sequence=1,
                action=action.value,
            )
            handler.handle(msg, AGENT_ID, GROUP_ID)

            emitted: AuditEvent = audit_service.emit.call_args[0][0]
            assert emitted.action == action


# ---------------------------------------------------------------------------
# Job ownership verification (cross-cutting)
# ---------------------------------------------------------------------------


class TestJobOwnershipVerification:
    def test_ownership_passes_when_agent_matches(self) -> None:
        job = _make_job(agent_id=AGENT_ID)
        result = AgentSessionHandler._verify_job_ownership(job, AGENT_ID, "test")
        assert result is job

    def test_ownership_fails_when_agent_differs(
        self, caplog: pytest.LogCaptureFixture,
    ) -> None:
        job = _make_job(agent_id=OTHER_AGENT_ID)
        with caplog.at_level(logging.WARNING, logger="legion.services.agent_session_handler"):
            result = AgentSessionHandler._verify_job_ownership(job, AGENT_ID, "test_msg")

        assert result is None
        assert any("ownership_violation" in r.message for r in caplog.records)
        violation_record = next(r for r in caplog.records if "ownership_violation" in r.message)
        assert AGENT_ID in violation_record.message
        assert OTHER_AGENT_ID in violation_record.message
        assert "test_msg" in violation_record.message

    def test_ownership_returns_none_when_job_is_none(self) -> None:
        result = AgentSessionHandler._verify_job_ownership(None, AGENT_ID, "test")
        assert result is None


# ---------------------------------------------------------------------------
# HandleResult dataclass
# ---------------------------------------------------------------------------


class TestHandleResult:
    def test_defaults(self) -> None:
        r = HandleResult()
        assert r.dispatch_pending_for_group is None
        assert r.ignored is False

    def test_dispatch_pending(self) -> None:
        r = HandleResult(dispatch_pending_for_group="ag-1")
        assert r.dispatch_pending_for_group == "ag-1"
        assert r.ignored is False

    def test_ignored(self) -> None:
        r = HandleResult(ignored=True)
        assert r.dispatch_pending_for_group is None
        assert r.ignored is True

    def test_frozen(self) -> None:
        r = HandleResult()
        with pytest.raises(AttributeError):
            r.ignored = True  # type: ignore[misc]

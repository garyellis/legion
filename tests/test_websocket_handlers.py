"""Unit tests for WebSocket message handler paths (message_emit, audit_event, job_progress)."""

from __future__ import annotations

import asyncio
import logging
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from legion.api.websocket import agent_websocket
from legion.domain.audit_event import AuditAction, AuditEvent
from legion.domain.job import Job, JobStatus, JobType
from legion.domain.message import AuthorType, Message, MessageType
from legion.domain.protocol import (
    AuditEventMessage,
    JobProgressMessage,
    MessageEmitMessage,
)


JOB_ID = "job-001"
AGENT_ID = "agent-001"
SESSION_ID = "session-001"
ORG_ID = "org-001"
GROUP_ID = "ag-001"


def _make_job(**overrides: object) -> Job:
    defaults = dict(
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


def _make_app_state(
    *,
    job: Job | None = None,
    message_service: object | None = None,
    audit_service: object | None = None,
) -> SimpleNamespace:
    """Build a minimal app.state namespace with the services the handler reads."""
    fleet_repo = MagicMock()
    job_repo = MagicMock()
    job_repo.get_by_id.return_value = job

    dispatch_service = MagicMock()
    dispatch_service.authenticate_agent_session.return_value = MagicMock(
        id=AGENT_ID,
        agent_group_id=GROUP_ID,
        go_idle=MagicMock(),
    )
    dispatch_service.disconnect_agent = MagicMock()

    connection_manager = MagicMock()
    connection_manager.connect = AsyncMock()
    connection_manager.remove = MagicMock()

    agent_delivery_service = MagicMock()
    agent_delivery_service.dispatch_pending_for_group = AsyncMock()

    state = SimpleNamespace(
        fleet_repo=fleet_repo,
        job_repo=job_repo,
        dispatch_service=dispatch_service,
        connection_manager=connection_manager,
        agent_delivery_service=agent_delivery_service,
        db_executor=None,  # run_in_executor(None, ...) uses default executor
    )

    if message_service is not None:
        state.message_service = message_service
    if audit_service is not None:
        state.audit_service = audit_service

    return state


def _make_websocket(app_state: SimpleNamespace, messages: list[str]) -> AsyncMock:
    """Create a mock WebSocket that yields *messages* then raises WebSocketDisconnect."""
    from fastapi import WebSocketDisconnect

    ws = AsyncMock()
    ws.headers = {"authorization": "Bearer valid-token"}

    app = SimpleNamespace(state=app_state)
    ws.app = app

    call_count = 0

    async def _receive_text() -> str:
        nonlocal call_count
        if call_count < len(messages):
            msg = messages[call_count]
            call_count += 1
            return msg
        raise WebSocketDisconnect()

    ws.receive_text = _receive_text
    return ws


class TestMessageEmitHandler:
    """Tests for the MessageEmitMessage handler path."""

    def test_message_emit_with_service_available(self) -> None:
        """When message_service is present, a Message is constructed and emitted."""
        job = _make_job()
        message_service = MagicMock()

        state = _make_app_state(job=job, message_service=message_service)

        msg = MessageEmitMessage(
            job_id=JOB_ID,
            message_type="AGENT_FINDING",
            content="Found 3 unhealthy pods",
            metadata={"cluster": "prod"},
        )
        raw = msg.model_dump_json()
        ws = _make_websocket(state, [raw])

        asyncio.run(agent_websocket(ws, AGENT_ID))

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

    def test_message_emit_without_service_skips_gracefully(self, caplog: pytest.LogCaptureFixture) -> None:
        """When message_service is absent, no error is raised and a debug log is emitted."""
        job = _make_job()
        # No message_service on state
        state = _make_app_state(job=job)

        msg = MessageEmitMessage(
            job_id=JOB_ID,
            message_type="AGENT_FINDING",
            content="some content",
        )
        raw = msg.model_dump_json()
        ws = _make_websocket(state, [raw])

        with caplog.at_level(logging.DEBUG, logger="legion.api.websocket"):
            asyncio.run(agent_websocket(ws, AGENT_ID))

        assert any("message_service not available" in record.message for record in caplog.records)
        # Confirm it's a debug-level message
        debug_records = [
            r for r in caplog.records
            if "message_service not available" in r.message
        ]
        assert all(r.levelno == logging.DEBUG for r in debug_records)

    def test_message_emit_empty_metadata_default(self) -> None:
        """When metadata is omitted, it defaults to an empty dict."""
        job = _make_job()
        message_service = MagicMock()
        state = _make_app_state(job=job, message_service=message_service)

        msg = MessageEmitMessage(
            job_id=JOB_ID,
            message_type="STATUS_UPDATE",
            content="status",
        )
        ws = _make_websocket(state, [msg.model_dump_json()])

        asyncio.run(agent_websocket(ws, AGENT_ID))

        emitted: Message = message_service.emit.call_args[0][0]
        assert emitted.metadata == {}


class TestAuditEventHandler:
    """Tests for the AuditEventMessage handler path."""

    def test_audit_event_with_service_available(self) -> None:
        """When audit_service is present, an AuditEvent is constructed and emitted."""
        job = _make_job()
        audit_service = MagicMock()
        state = _make_app_state(job=job, audit_service=audit_service)

        msg = AuditEventMessage(
            job_id=JOB_ID,
            tool_name="kubectl_get_pods",
            tool_input="--namespace default",
            tool_output="NAME  READY  STATUS\npod-1  1/1  Running",
            duration_ms=150,
            sequence=1,
        )
        ws = _make_websocket(state, [msg.model_dump_json()])

        asyncio.run(agent_websocket(ws, AGENT_ID))

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

    def test_audit_event_maps_action_from_protocol(self) -> None:
        """When the protocol message carries a non-default action, the AuditEvent uses it."""
        job = _make_job()
        audit_service = MagicMock()
        state = _make_app_state(job=job, audit_service=audit_service)

        msg = AuditEventMessage(
            job_id=JOB_ID,
            tool_name="llm_router",
            tool_input="prompt",
            tool_output="decision",
            duration_ms=50,
            sequence=1,
            action="LLM_DECISION",
        )
        ws = _make_websocket(state, [msg.model_dump_json()])

        asyncio.run(agent_websocket(ws, AGENT_ID))

        audit_service.emit.assert_called_once()
        emitted: AuditEvent = audit_service.emit.call_args[0][0]
        assert emitted.action == AuditAction.LLM_DECISION

    def test_audit_event_maps_error_to_output(self) -> None:
        """When the protocol message carries an error, the output dict includes it."""
        job = _make_job()
        audit_service = MagicMock()
        state = _make_app_state(job=job, audit_service=audit_service)

        msg = AuditEventMessage(
            job_id=JOB_ID,
            tool_name="kubectl_get_pods",
            tool_input="--namespace default",
            tool_output="partial output",
            duration_ms=200,
            sequence=1,
            error="connection refused",
        )
        ws = _make_websocket(state, [msg.model_dump_json()])

        asyncio.run(agent_websocket(ws, AGENT_ID))

        audit_service.emit.assert_called_once()
        emitted: AuditEvent = audit_service.emit.call_args[0][0]
        assert emitted.output == {"raw": "partial output", "error": "connection refused"}

    def test_audit_event_unknown_action_defaults_to_tool_call(self, caplog: pytest.LogCaptureFixture) -> None:
        """When the protocol message has an unrecognized action, it falls back to TOOL_CALL."""
        job = _make_job()
        audit_service = MagicMock()
        state = _make_app_state(job=job, audit_service=audit_service)

        msg = AuditEventMessage(
            job_id=JOB_ID,
            tool_name="some_tool",
            tool_input="in",
            tool_output="out",
            duration_ms=10,
            sequence=1,
            action="UNKNOWN_ACTION",
        )
        ws = _make_websocket(state, [msg.model_dump_json()])

        with caplog.at_level(logging.WARNING, logger="legion.api.websocket"):
            asyncio.run(agent_websocket(ws, AGENT_ID))

        audit_service.emit.assert_called_once()
        emitted: AuditEvent = audit_service.emit.call_args[0][0]
        assert emitted.action == AuditAction.TOOL_CALL
        assert any("Unknown audit action" in r.message for r in caplog.records)

    def test_audit_event_without_service_skips_gracefully(self, caplog: pytest.LogCaptureFixture) -> None:
        """When audit_service is absent, no error is raised and a debug log is emitted."""
        job = _make_job()
        state = _make_app_state(job=job)

        msg = AuditEventMessage(
            job_id=JOB_ID,
            tool_name="kubectl_get_pods",
            tool_input="input",
            tool_output="output",
            duration_ms=10,
            sequence=1,
        )
        ws = _make_websocket(state, [msg.model_dump_json()])

        with caplog.at_level(logging.DEBUG, logger="legion.api.websocket"):
            asyncio.run(agent_websocket(ws, AGENT_ID))

        assert any("audit_service not available" in record.message for record in caplog.records)
        debug_records = [
            r for r in caplog.records
            if "audit_service not available" in r.message
        ]
        assert all(r.levelno == logging.DEBUG for r in debug_records)

    def test_audit_event_populates_all_job_fields(self) -> None:
        """Verify session_id and org_id are sourced from the job, not the message."""
        job = _make_job(session_id="sess-custom", org_id="org-custom")
        audit_service = MagicMock()
        state = _make_app_state(job=job, audit_service=audit_service)

        msg = AuditEventMessage(
            job_id=JOB_ID,
            tool_name="tool",
            tool_input="in",
            tool_output="out",
            duration_ms=5,
            sequence=1,
        )
        ws = _make_websocket(state, [msg.model_dump_json()])

        asyncio.run(agent_websocket(ws, AGENT_ID))

        emitted: AuditEvent = audit_service.emit.call_args[0][0]
        assert emitted.session_id == "sess-custom"
        assert emitted.org_id == "org-custom"


class TestJobProgressHandler:
    """Tests for the JobProgressMessage handler path."""

    def test_job_progress_logs_info(self, caplog: pytest.LogCaptureFixture) -> None:
        """A valid job_progress message is logged at INFO level."""
        job = _make_job()
        state = _make_app_state(job=job)

        msg = JobProgressMessage(
            job_id=JOB_ID,
            step="fetching_pods",
            detail="namespace=default",
            sequence=1,
        )
        ws = _make_websocket(state, [msg.model_dump_json()])

        with caplog.at_level(logging.INFO, logger="legion.api.websocket"):
            asyncio.run(agent_websocket(ws, AGENT_ID))

        progress_records = [r for r in caplog.records if "job_progress" in r.message]
        assert len(progress_records) >= 1
        record = progress_records[0]
        assert "fetching_pods" in record.message
        assert JOB_ID in record.message


class TestJobOwnershipVerification:
    """Tests that handlers skip messages for jobs not owned by the agent."""

    def test_message_emit_skipped_when_job_owned_by_other_agent(self) -> None:
        """message_emit is ignored when the job belongs to a different agent."""
        job = _make_job(agent_id="other-agent")
        message_service = MagicMock()
        state = _make_app_state(job=job, message_service=message_service)

        msg = MessageEmitMessage(
            job_id=JOB_ID,
            message_type="AGENT_FINDING",
            content="should not persist",
        )
        ws = _make_websocket(state, [msg.model_dump_json()])

        asyncio.run(agent_websocket(ws, AGENT_ID))

        message_service.emit.assert_not_called()

    def test_audit_event_skipped_when_job_owned_by_other_agent(self) -> None:
        """audit_event is ignored when the job belongs to a different agent."""
        job = _make_job(agent_id="other-agent")
        audit_service = MagicMock()
        state = _make_app_state(job=job, audit_service=audit_service)

        msg = AuditEventMessage(
            job_id=JOB_ID,
            tool_name="tool",
            tool_input="in",
            tool_output="out",
            duration_ms=5,
            sequence=1,
        )
        ws = _make_websocket(state, [msg.model_dump_json()])

        asyncio.run(agent_websocket(ws, AGENT_ID))

        audit_service.emit.assert_not_called()

    def test_message_emit_skipped_when_job_not_found(self) -> None:
        """message_emit is ignored when job_repo returns None."""
        message_service = MagicMock()
        state = _make_app_state(job=None, message_service=message_service)

        msg = MessageEmitMessage(
            job_id=JOB_ID,
            message_type="AGENT_FINDING",
            content="should not persist",
        )
        ws = _make_websocket(state, [msg.model_dump_json()])

        asyncio.run(agent_websocket(ws, AGENT_ID))

        message_service.emit.assert_not_called()

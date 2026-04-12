"""Unit tests for WebSocket transport adapter (HandleResult → transport effect translation)."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from typing import Any, cast
from unittest.mock import AsyncMock, MagicMock

import pytest

from legion.api.websocket import agent_websocket
from legion.domain.job import Job, JobStatus, JobType
from legion.domain.protocol import JobResultMessage
from legion.services.agent_session_handler import (
    AgentSessionHandler,
    HandleResult,
    RedispatchPendingForGroup,
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
    agent_session_handler: object | None = None,
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

    if agent_session_handler is None:
        agent_session_handler = AgentSessionHandler(
            dispatch_service,
            job_repo,
        )

    state = SimpleNamespace(
        fleet_repo=fleet_repo,
        job_repo=job_repo,
        dispatch_service=dispatch_service,
        connection_manager=connection_manager,
        agent_delivery_service=agent_delivery_service,
        agent_session_handler=agent_session_handler,
        db_executor=None,  # run_in_executor(None, ...) uses default executor
    )

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


class TestHandleResultTranslation:
    """Tests that websocket adapter translates typed service results into transport work."""

    def test_job_result_effect_triggers_pending_redispatch(self) -> None:
        """A RedispatchPendingForGroup effect calls the delivery service for that group."""
        job = _make_job()
        agent_session_handler = MagicMock()
        agent_session_handler.handle.return_value = HandleResult(
            effects=(RedispatchPendingForGroup("redispatch-group"),),
        )
        state = _make_app_state(job=job, agent_session_handler=agent_session_handler)

        msg = JobResultMessage(job_id=JOB_ID, result="all pods healthy")
        ws = _make_websocket(state, [msg.model_dump_json()])

        asyncio.run(agent_websocket(ws, AGENT_ID))

        state.agent_delivery_service.dispatch_pending_for_group.assert_any_call(
            GROUP_ID,
            state.connection_manager.send_job_to_agent,
        )
        state.agent_delivery_service.dispatch_pending_for_group.assert_any_call(
            "redispatch-group",
            state.connection_manager.send_job_to_agent,
        )
        assert agent_session_handler.handle.call_count == 1

    def test_unknown_effect_raises_type_error(self) -> None:
        """Unknown service effects fail loudly instead of being ignored."""

        class UnknownEffect:
            pass

        job = _make_job()
        agent_session_handler = MagicMock()
        agent_session_handler.handle.return_value = HandleResult(
            effects=(cast(Any, UnknownEffect()),),
        )
        state = _make_app_state(job=job, agent_session_handler=agent_session_handler)

        msg = JobResultMessage(job_id=JOB_ID, result="all pods healthy")
        ws = _make_websocket(state, [msg.model_dump_json()])

        with pytest.raises(TypeError, match="Unsupported HandleResult effect: UnknownEffect"):
            asyncio.run(agent_websocket(ws, AGENT_ID))

        state.dispatch_service.disconnect_agent.assert_called_once_with(AGENT_ID)

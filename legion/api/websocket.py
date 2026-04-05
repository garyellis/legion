"""WebSocket connection manager and agent endpoint."""

from __future__ import annotations

import asyncio
import logging
from functools import partial

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from pydantic import TypeAdapter, ValidationError

from legion.domain.protocol import (
    AgentToServerMessage,
    AuditEventMessage,
    HeartbeatMessage,
    JobFailedMessage,
    JobProgressMessage,
    JobResultMessage,
    JobStartedMessage,
    MessageEmitMessage,
)
from legion.domain.agent import Agent
from legion.domain.job import Job
from legion.domain.prompt_config import PromptConfig
from legion.services.agent_delivery_service import AgentDeliveryService
from legion.services.dispatch_service import DispatchService
from legion.services.exceptions import (
    AgentNotFoundError,
    DispatchError,
    InvalidSessionTokenError,
    SessionTokenMismatchError,
)
from legion.services.fleet_repository import FleetRepository
from legion.services.job_repository import JobRepository

logger = logging.getLogger(__name__)
_AGENT_MESSAGE_ADAPTER: TypeAdapter[AgentToServerMessage] = TypeAdapter(AgentToServerMessage)

router = APIRouter()


class ConnectionManager:
    """Tracks active agent WebSocket connections."""

    def __init__(self) -> None:
        self._connections: dict[str, WebSocket] = {}

    async def connect(self, agent_id: str, websocket: WebSocket) -> None:
        await websocket.accept()
        self._connections[agent_id] = websocket

    async def disconnect(self, agent_id: str) -> None:
        self._connections.pop(agent_id, None)

    async def disconnect_all(self) -> None:
        for ws in self._connections.values():
            try:
                await ws.close()
            except Exception:
                pass
        self._connections.clear()

    async def send_job_to_agent(self, job: Job, agent: Agent, prompt_config: PromptConfig | None = None) -> None:
        ws = self._connections.get(agent.id)
        if ws is not None:
            system_prompt = prompt_config.system_prompt if prompt_config else ""
            await ws.send_json({
                "type": "job_dispatch",
                "job_id": job.id,
                "job_type": job.type.value,
                "payload": job.payload,
                "system_prompt": system_prompt,
                "max_job_tokens": 32_768,
            })

    def is_connected(self, agent_id: str) -> bool:
        return agent_id in self._connections


def _extract_bearer_token(websocket: WebSocket) -> str | None:
    authorization = websocket.headers.get("authorization", "")
    prefix = "bearer "
    if not authorization.lower().startswith(prefix):
        return None
    token = authorization[len(prefix):].strip()
    return token or None


def _parse_agent_message(raw_message: str) -> AgentToServerMessage | None:
    try:
        return _AGENT_MESSAGE_ADAPTER.validate_json(raw_message)
    except ValidationError:
        logger.warning("Ignoring malformed agent websocket message: %s", raw_message)
        return None


def _verify_job_ownership(job: Job | None, agent_id: str, message_type: str) -> Job | None:
    """Return the job if it exists and belongs to the agent, else None."""
    if job is None:
        return None
    if job.agent_id != agent_id:
        logger.warning(
            "ownership_violation agent=%s sent %s for job %s owned by %s",
            agent_id, message_type, job.id, job.agent_id,
        )
        return None
    return job


@router.websocket("/ws/agents/{agent_id}")
async def agent_websocket(websocket: WebSocket, agent_id: str) -> None:
    fleet_repo: FleetRepository = websocket.app.state.fleet_repo
    job_repo: JobRepository = websocket.app.state.job_repo
    dispatch_service: DispatchService = websocket.app.state.dispatch_service
    connection_manager: ConnectionManager = websocket.app.state.connection_manager
    agent_delivery_service: AgentDeliveryService = websocket.app.state.agent_delivery_service
    db_executor = websocket.app.state.db_executor
    loop = asyncio.get_running_loop()

    session_token = _extract_bearer_token(websocket)
    if session_token is None:
        await websocket.close(code=4001)
        return

    try:
        agent = await loop.run_in_executor(
            db_executor, dispatch_service.authenticate_agent_session, agent_id, session_token,
        )
    except SessionTokenMismatchError:
        await websocket.close(code=4003)
        return
    except (InvalidSessionTokenError, AgentNotFoundError):
        await websocket.close(code=4001)
        return

    await connection_manager.connect(agent_id, websocket)

    try:
        agent.go_idle()
        await loop.run_in_executor(db_executor, fleet_repo.save_agent, agent)

        logger.info("Agent connected: %s", agent_id)
        await agent_delivery_service.dispatch_pending_for_group(
            agent.agent_group_id,
            connection_manager.send_job_to_agent,
        )

        while True:
            raw = await websocket.receive_text()
            message = _parse_agent_message(raw)
            if message is None:
                continue

            if isinstance(message, HeartbeatMessage):
                await loop.run_in_executor(db_executor, dispatch_service.heartbeat, agent_id)

            elif isinstance(message, JobStartedMessage):
                job = _verify_job_ownership(
                    await loop.run_in_executor(db_executor, job_repo.get_by_id, message.job_id),
                    agent_id,
                    "job_started",
                )
                if job is not None:
                    job.start()
                    await loop.run_in_executor(db_executor, job_repo.save, job)

            elif isinstance(message, JobResultMessage):
                try:
                    await loop.run_in_executor(
                        db_executor,
                        partial(dispatch_service.complete_job, message.job_id, message.result, agent_id=agent_id),
                    )
                except DispatchError:
                    logger.warning(
                        "Ignoring job_result for unknown job %s from agent %s",
                        message.job_id,
                        agent_id,
                    )
                    continue
                await agent_delivery_service.dispatch_pending_for_group(
                    agent.agent_group_id,
                    connection_manager.send_job_to_agent,
                )

            elif isinstance(message, JobFailedMessage):
                try:
                    await loop.run_in_executor(
                        db_executor,
                        partial(dispatch_service.fail_job, message.job_id, message.error, agent_id=agent_id),
                    )
                except DispatchError:
                    logger.warning(
                        "Ignoring job_failed for unknown job %s from agent %s",
                        message.job_id,
                        agent_id,
                    )
                    continue
                await agent_delivery_service.dispatch_pending_for_group(
                    agent.agent_group_id,
                    connection_manager.send_job_to_agent,
                )

            elif isinstance(message, JobProgressMessage):
                job = _verify_job_ownership(
                    await loop.run_in_executor(db_executor, job_repo.get_by_id, message.job_id),
                    agent_id,
                    "job_progress",
                )
                if job is not None:
                    logger.info(
                        "job_progress job=%s step=%s detail=%s seq=%d",
                        message.job_id, message.step, message.detail, message.sequence,
                    )

            elif isinstance(message, MessageEmitMessage):
                job = _verify_job_ownership(
                    await loop.run_in_executor(db_executor, job_repo.get_by_id, message.job_id),
                    agent_id,
                    "message_emit",
                )
                if job is not None:
                    message_service = getattr(websocket.app.state, "message_service", None)
                    if message_service is not None:
                        try:
                            from legion.domain.message import AuthorType, Message, MessageType
                            domain_message = Message(
                                org_id=job.org_id,
                                session_id=job.session_id,
                                author_id=job.agent_id or agent_id,
                                author_type=AuthorType.AGENT,
                                message_type=MessageType(message.message_type),
                                content=message.content,
                                job_id=message.job_id,
                                metadata=message.metadata,
                            )
                            await loop.run_in_executor(db_executor, message_service.emit, domain_message)
                        except Exception:
                            logger.warning(
                                "Failed to persist message_emit for job %s from agent %s",
                                message.job_id, agent_id, exc_info=True,
                            )
                    else:
                        logger.debug("message_service not available, skipping message_emit for job %s", message.job_id)

            elif isinstance(message, AuditEventMessage):
                job = _verify_job_ownership(
                    await loop.run_in_executor(db_executor, job_repo.get_by_id, message.job_id),
                    agent_id,
                    "audit_event",
                )
                if job is not None:
                    audit_service = getattr(websocket.app.state, "audit_service", None)
                    if audit_service is not None:
                        try:
                            from legion.domain.audit_event import AuditAction, AuditEvent
                            audit_event = AuditEvent(
                                job_id=message.job_id,
                                agent_id=job.agent_id or agent_id,
                                session_id=job.session_id,
                                org_id=job.org_id,
                                action=AuditAction.TOOL_CALL,
                                tool_name=message.tool_name,
                                input={"raw": message.tool_input},
                                output={"raw": message.tool_output},
                                duration_ms=message.duration_ms,
                            )
                            await loop.run_in_executor(db_executor, audit_service.emit, audit_event)
                        except Exception:
                            logger.warning(
                                "Failed to persist audit_event for job %s from agent %s",
                                message.job_id, agent_id, exc_info=True,
                            )
                    else:
                        logger.debug("audit_service not available, skipping audit_event for job %s", message.job_id)

    except (WebSocketDisconnect, asyncio.CancelledError):
        pass
    finally:
        connection_manager._connections.pop(agent_id, None)
        # Run disconnect synchronously in the finally block. Using
        # run_in_executor here is unreliable because the event loop may
        # cancel the task during teardown (e.g. in test environments),
        # preventing the await from ever completing.  The brief block is
        # acceptable since this runs once per agent disconnect.
        dispatch_service.disconnect_agent(agent_id)

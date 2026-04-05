"""WebSocket connection manager and agent endpoint."""

from __future__ import annotations

import logging

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from pydantic import TypeAdapter, ValidationError

from legion.api.schemas import (
    AgentHeartbeatMessage,
    AgentJobFailedMessage,
    AgentJobResultMessage,
    AgentJobStartedMessage,
    AgentWebSocketMessage,
)
from legion.domain.agent import Agent
from legion.domain.job import Job
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
_AGENT_MESSAGE_ADAPTER: TypeAdapter[AgentWebSocketMessage] = TypeAdapter(AgentWebSocketMessage)

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

    async def send_job_to_agent(self, job: Job, agent: Agent) -> None:
        ws = self._connections.get(agent.id)
        if ws is not None:
            await ws.send_json({
                "type": "job_dispatch",
                "job_id": job.id,
                "job_type": job.type.value,
                "payload": job.payload,
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


def _parse_agent_message(raw_message: str) -> AgentWebSocketMessage | None:
    try:
        return _AGENT_MESSAGE_ADAPTER.validate_json(raw_message)
    except ValidationError:
        logger.warning("Ignoring malformed agent websocket message: %s", raw_message)
        return None


@router.websocket("/ws/agents/{agent_id}")
async def agent_websocket(websocket: WebSocket, agent_id: str) -> None:
    fleet_repo: FleetRepository = websocket.app.state.fleet_repo
    job_repo: JobRepository = websocket.app.state.job_repo
    dispatch_service: DispatchService = websocket.app.state.dispatch_service
    connection_manager: ConnectionManager = websocket.app.state.connection_manager
    agent_delivery_service: AgentDeliveryService = websocket.app.state.agent_delivery_service

    session_token = _extract_bearer_token(websocket)
    if session_token is None:
        await websocket.close(code=4001)
        return

    try:
        agent = dispatch_service.authenticate_agent_session(agent_id, session_token)
    except SessionTokenMismatchError:
        await websocket.close(code=4003)
        return
    except (InvalidSessionTokenError, AgentNotFoundError):
        await websocket.close(code=4001)
        return

    await connection_manager.connect(agent_id, websocket)

    agent.go_idle()
    fleet_repo.save_agent(agent)

    logger.info("Agent connected: %s", agent_id)
    await agent_delivery_service.dispatch_pending_for_group(
        agent.agent_group_id,
        connection_manager.send_job_to_agent,
    )

    try:
        while True:
            raw = await websocket.receive_text()
            message = _parse_agent_message(raw)
            if message is None:
                continue

            if isinstance(message, AgentHeartbeatMessage):
                dispatch_service.heartbeat(agent_id)

            elif isinstance(message, AgentJobStartedMessage):
                job = job_repo.get_by_id(message.job_id)
                if job is not None:
                    job.start()
                    job_repo.save(job)

            elif isinstance(message, AgentJobResultMessage):
                try:
                    dispatch_service.complete_job(message.job_id, message.result)
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

            elif isinstance(message, AgentJobFailedMessage):
                try:
                    dispatch_service.fail_job(message.job_id, message.error)
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

    except WebSocketDisconnect:
        pass
    finally:
        await connection_manager.disconnect(agent_id)
        dispatch_service.disconnect_agent(agent_id)

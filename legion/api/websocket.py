"""WebSocket connection manager and agent endpoint."""

from __future__ import annotations

import asyncio
import logging

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from pydantic import TypeAdapter, ValidationError

from legion.domain.protocol import AgentToServerMessage
from legion.domain.agent import Agent
from legion.domain.job import Job
from legion.domain.prompt_config import PromptConfig
from legion.services.agent_delivery_service import AgentDeliveryService
from legion.services.agent_session_handler import AgentSessionHandler
from legion.services.dispatch_service import DispatchService
from legion.services.exceptions import (
    AgentNotFoundError,
    InvalidSessionTokenError,
    SessionTokenMismatchError,
)
from legion.services.fleet_repository import FleetRepository

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

    def remove(self, agent_id: str) -> None:
        """Remove a connection synchronously. For use in finally blocks."""
        self._connections.pop(agent_id, None)

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


@router.websocket("/ws/agents/{agent_id}")
async def agent_websocket(websocket: WebSocket, agent_id: str) -> None:
    fleet_repo: FleetRepository = websocket.app.state.fleet_repo
    dispatch_service: DispatchService = websocket.app.state.dispatch_service
    connection_manager: ConnectionManager = websocket.app.state.connection_manager
    agent_delivery_service: AgentDeliveryService = websocket.app.state.agent_delivery_service
    agent_session_handler: AgentSessionHandler = websocket.app.state.agent_session_handler
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

            result = await loop.run_in_executor(
                db_executor,
                agent_session_handler.handle,
                message,
                agent_id,
                agent.agent_group_id,
            )

            if result.dispatch_pending_for_group:
                await agent_delivery_service.dispatch_pending_for_group(
                    result.dispatch_pending_for_group,
                    connection_manager.send_job_to_agent,
                )

    except (WebSocketDisconnect, asyncio.CancelledError):
        pass
    finally:
        connection_manager.remove(agent_id)
        # Synchronous call is intentional: dispatch_service.disconnect_agent()
        # performs only CPU-bound SQLAlchemy operations (agent state transition
        # + job re-queue). Using run_in_executor in a finally block is
        # unreliable — the event loop may cancel the task during teardown,
        # leaving the agent in a stale state.
        dispatch_service.disconnect_agent(agent_id)

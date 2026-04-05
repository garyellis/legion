"""WebSocket connection manager and agent endpoint."""

from __future__ import annotations

import json
import logging

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from legion.domain.agent import Agent
from legion.domain.job import Job
from legion.services.dispatch_service import DispatchService
from legion.services.exceptions import AgentNotFoundError, InvalidSessionTokenError, SessionTokenMismatchError
from legion.services.fleet_repository import FleetRepository
from legion.services.job_repository import JobRepository

logger = logging.getLogger(__name__)

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


@router.websocket("/ws/agents/{agent_id}")
async def agent_websocket(websocket: WebSocket, agent_id: str) -> None:
    fleet_repo: FleetRepository = websocket.app.state.fleet_repo
    job_repo: JobRepository = websocket.app.state.job_repo
    dispatch_service: DispatchService = websocket.app.state.dispatch_service
    connection_manager: ConnectionManager = websocket.app.state.connection_manager

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

    try:
        while True:
            raw = await websocket.receive_text()
            data = json.loads(raw)
            msg_type = data.get("type")

            if msg_type == "heartbeat":
                dispatch_service.heartbeat(agent_id)

            elif msg_type == "job_started":
                job = job_repo.get_by_id(data["job_id"])
                if job is not None:
                    job.start()
                    job_repo.save(job)

            elif msg_type == "job_result":
                dispatch_service.complete_job(data["job_id"], data["result"])
                # Check for pending jobs
                connected_agent = fleet_repo.get_agent(agent_id)
                if connected_agent is not None:
                    dispatched = dispatch_service.dispatch_pending(
                        connected_agent.agent_group_id,
                    )
                    for d_job, d_agent in dispatched:
                        await connection_manager.send_job_to_agent(d_job, d_agent)

            elif msg_type == "job_failed":
                dispatch_service.fail_job(data["job_id"], data.get("error", ""))
                # Check for pending jobs
                connected_agent = fleet_repo.get_agent(agent_id)
                if connected_agent is not None:
                    dispatched = dispatch_service.dispatch_pending(
                        connected_agent.agent_group_id,
                    )
                    for d_job, d_agent in dispatched:
                        await connection_manager.send_job_to_agent(d_job, d_agent)

    except WebSocketDisconnect:
        pass
    finally:
        await connection_manager.disconnect(agent_id)
        disconnected_agent = fleet_repo.get_agent(agent_id)
        if disconnected_agent is not None:
            disconnected_agent.go_offline()
            fleet_repo.save_agent(disconnected_agent)
        dispatch_service.reassign_disconnected(agent_id)
        logger.info("Agent disconnected: %s", agent_id)

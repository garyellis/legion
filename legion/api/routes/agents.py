"""Agent routes for lookup and explicit registration."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request, status

from legion.api.deps import get_dispatch_service, get_fleet_repo, get_pagination
from legion.api.schemas.agents import (
    AgentConnectionConfig,
    AgentRegister,
    AgentRegistrationResponse,
    AgentResponse,
)
from legion.api.schemas.pagination import PaginatedResponse, PaginationParams
from legion.services.dispatch_service import DispatchService
from legion.services.fleet_repository import FleetRepository

router = APIRouter(prefix="/agents", tags=["agents"])


def _websocket_path(agent_id: str) -> str:
    return f"/ws/agents/{agent_id}"


@router.get("/")
def list_agents(
    agent_group_id: str,
    fleet_repo: FleetRepository = Depends(get_fleet_repo),
    pagination: PaginationParams = Depends(get_pagination),
) -> PaginatedResponse[AgentResponse]:
    agents = fleet_repo.list_agents(agent_group_id)
    items = [AgentResponse.from_domain(a) for a in agents[pagination.offset:pagination.offset + pagination.limit]]
    return PaginatedResponse(items=items, total=len(agents), limit=pagination.limit, offset=pagination.offset)


@router.get("/{agent_id}")
def get_agent(
    agent_id: str,
    fleet_repo: FleetRepository = Depends(get_fleet_repo),
) -> AgentResponse:
    agent = fleet_repo.get_agent(agent_id)
    if agent is None:
        raise HTTPException(status_code=404, detail="Agent not found")
    return AgentResponse.from_domain(agent)


@router.post("/register", status_code=status.HTTP_201_CREATED)
def register_agent(
    body: AgentRegister,
    request: Request,
    dispatch_service: DispatchService = Depends(get_dispatch_service),
) -> AgentRegistrationResponse:
    api_config = request.app.state.api_config
    result = dispatch_service.register_agent_with_token(
        body.registration_token,
        body.name,
        body.capabilities,
    )
    return AgentRegistrationResponse(
        agent=AgentResponse.from_domain(result.agent),
        session_token=result.session_token,
        session_token_expires_at=result.session_token_expires_at,
        config=AgentConnectionConfig(
            heartbeat_interval_seconds=api_config.agent_heartbeat_interval_seconds,
            websocket_path=_websocket_path(result.agent.id),
        ),
    )

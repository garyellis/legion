"""AgentGroup CRUD routes."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status

from legion.api.deps import get_fleet_repo
from legion.api.schemas import AgentGroupCreate
from legion.domain.agent_group import AgentGroup
from legion.services.fleet_repository import FleetRepository

router = APIRouter(prefix="/agent-groups", tags=["agent-groups"])


@router.post("/", status_code=status.HTTP_201_CREATED)
def create_agent_group(
    body: AgentGroupCreate,
    fleet_repo: FleetRepository = Depends(get_fleet_repo),
) -> AgentGroup:
    ag = AgentGroup(
        org_id=body.org_id,
        name=body.name,
        slug=body.slug,
        environment=body.environment,
        provider=body.provider,
    )
    fleet_repo.save_agent_group(ag)
    return ag


@router.get("/")
def list_agent_groups(
    org_id: str,
    fleet_repo: FleetRepository = Depends(get_fleet_repo),
) -> list[AgentGroup]:
    return fleet_repo.list_agent_groups(org_id)


@router.get("/{ag_id}")
def get_agent_group(
    ag_id: str,
    fleet_repo: FleetRepository = Depends(get_fleet_repo),
) -> AgentGroup:
    ag = fleet_repo.get_agent_group(ag_id)
    if ag is None:
        raise HTTPException(status_code=404, detail="AgentGroup not found")
    return ag

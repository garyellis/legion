"""AgentGroup CRUD routes."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status

from legion.api.deps import get_fleet_repo
from legion.api.schemas import AgentGroupCreate, AgentGroupUpdate
from legion.domain.agent_group import AgentGroup
from legion.services.fleet_repository import FleetRepository

router = APIRouter(prefix="/agent-groups", tags=["agent-groups"])


@router.post("/", status_code=status.HTTP_201_CREATED)
def create_agent_group(
    body: AgentGroupCreate,
    fleet_repo: FleetRepository = Depends(get_fleet_repo),
) -> AgentGroup:
    if fleet_repo.get_org(body.org_id) is None:
        raise HTTPException(status_code=404, detail=f"Organization {body.org_id} not found")
    if fleet_repo.get_project(body.project_id) is None:
        raise HTTPException(status_code=404, detail=f"Project {body.project_id} not found")
    ag = AgentGroup(
        org_id=body.org_id,
        project_id=body.project_id,
        name=body.name,
        slug=body.slug,
        environment=body.environment,
        provider=body.provider,
    )
    fleet_repo.save_agent_group(ag)
    return ag


@router.get("/")
def list_agent_groups(
    org_id: str | None = None,
    project_id: str | None = None,
    fleet_repo: FleetRepository = Depends(get_fleet_repo),
) -> list[AgentGroup]:
    if project_id is not None:
        return fleet_repo.list_agent_groups_by_project(project_id)
    if org_id is not None:
        return fleet_repo.list_agent_groups(org_id)
    raise HTTPException(status_code=400, detail="Provide org_id or project_id")


@router.get("/{ag_id}")
def get_agent_group(
    ag_id: str,
    fleet_repo: FleetRepository = Depends(get_fleet_repo),
) -> AgentGroup:
    ag = fleet_repo.get_agent_group(ag_id)
    if ag is None:
        raise HTTPException(status_code=404, detail="AgentGroup not found")
    return ag


@router.put("/{ag_id}")
def update_agent_group(
    ag_id: str,
    body: AgentGroupUpdate,
    fleet_repo: FleetRepository = Depends(get_fleet_repo),
) -> AgentGroup:
    ag = fleet_repo.get_agent_group(ag_id)
    if ag is None:
        raise HTTPException(status_code=404, detail="AgentGroup not found")
    if body.name is not None:
        ag.name = body.name
    if body.slug is not None:
        ag.slug = body.slug
    if body.environment is not None:
        ag.environment = body.environment
    if body.provider is not None:
        ag.provider = body.provider
    fleet_repo.save_agent_group(ag)
    return ag


@router.delete("/{ag_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_agent_group(
    ag_id: str,
    fleet_repo: FleetRepository = Depends(get_fleet_repo),
) -> None:
    if not fleet_repo.delete_agent_group(ag_id):
        raise HTTPException(status_code=404, detail="AgentGroup not found")

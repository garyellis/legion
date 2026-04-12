"""AgentGroup CRUD routes."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status

from legion.api.deps import get_dispatch_service, get_fleet_repo, get_pagination
from legion.api.routes._helpers import apply_partial_update
from legion.api.schemas.agent_groups import (
    AgentGroupCreate,
    AgentGroupResponse,
    AgentGroupTokenResponse,
    AgentGroupUpdate,
)
from legion.api.schemas.pagination import PaginatedResponse, PaginationParams
from legion.domain.agent_group import AgentGroup
from legion.services.dispatch_service import DispatchService
from legion.services.fleet_repository import FleetRepository

router = APIRouter(prefix="/agent-groups", tags=["agent-groups"])


@router.post("/", status_code=status.HTTP_201_CREATED)
def create_agent_group(
    body: AgentGroupCreate,
    fleet_repo: FleetRepository = Depends(get_fleet_repo),
) -> AgentGroupResponse:
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
    return AgentGroupResponse.from_domain(ag)


@router.get("/")
def list_agent_groups(
    org_id: str | None = None,
    project_id: str | None = None,
    fleet_repo: FleetRepository = Depends(get_fleet_repo),
    pagination: PaginationParams = Depends(get_pagination),
) -> PaginatedResponse[AgentGroupResponse]:
    if project_id is not None:
        groups = fleet_repo.list_agent_groups_by_project(project_id)
    elif org_id is not None:
        groups = fleet_repo.list_agent_groups(org_id)
    else:
        raise HTTPException(status_code=400, detail="Provide org_id or project_id")
    items = [AgentGroupResponse.from_domain(g) for g in groups[pagination.offset:pagination.offset + pagination.limit]]
    return PaginatedResponse(items=items, total=len(groups), limit=pagination.limit, offset=pagination.offset)


@router.get("/{ag_id}")
def get_agent_group(
    ag_id: str,
    fleet_repo: FleetRepository = Depends(get_fleet_repo),
) -> AgentGroupResponse:
    ag = fleet_repo.get_agent_group(ag_id)
    if ag is None:
        raise HTTPException(status_code=404, detail="AgentGroup not found")
    return AgentGroupResponse.from_domain(ag)


@router.put("/{ag_id}")
def update_agent_group(
    ag_id: str,
    body: AgentGroupUpdate,
    fleet_repo: FleetRepository = Depends(get_fleet_repo),
) -> AgentGroupResponse:
    ag = fleet_repo.get_agent_group(ag_id)
    if ag is None:
        raise HTTPException(status_code=404, detail="AgentGroup not found")
    apply_partial_update(ag, body)
    fleet_repo.save_agent_group(ag)
    return AgentGroupResponse.from_domain(ag)


@router.delete("/{ag_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_agent_group(
    ag_id: str,
    fleet_repo: FleetRepository = Depends(get_fleet_repo),
) -> None:
    if not fleet_repo.delete_agent_group(ag_id):
        raise HTTPException(status_code=404, detail="AgentGroup not found")


@router.post("/{ag_id}/token", status_code=status.HTTP_201_CREATED)
def rotate_agent_group_token(
    ag_id: str,
    dispatch_service: DispatchService = Depends(get_dispatch_service),
) -> AgentGroupTokenResponse:
    result = dispatch_service.rotate_agent_group_registration_token(ag_id)
    rotated_at = result.agent_group.registration_token_rotated_at
    if rotated_at is None:
        raise HTTPException(
            status_code=500,
            detail="Token rotation succeeded but rotated_at timestamp is missing",
        )
    return AgentGroupTokenResponse(
        agent_group_id=result.agent_group.id,
        registration_token=result.registration_token,
        registration_token_rotated_at=rotated_at,
    )

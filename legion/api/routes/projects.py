"""Project CRUD routes."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status

from legion.api.deps import get_fleet_repo, get_pagination
from legion.api.routes._helpers import apply_partial_update
from legion.api.schemas.pagination import PaginatedResponse, PaginationParams
from legion.api.schemas.projects import ProjectCreate, ProjectResponse, ProjectUpdate
from legion.domain.project import Project
from legion.services.fleet_repository import FleetRepository

router = APIRouter(prefix="/projects", tags=["projects"])


@router.post("/", status_code=status.HTTP_201_CREATED)
def create_project(
    body: ProjectCreate,
    fleet_repo: FleetRepository = Depends(get_fleet_repo),
) -> ProjectResponse:
    if fleet_repo.get_org(body.org_id) is None:
        raise HTTPException(status_code=404, detail=f"Organization {body.org_id} not found")
    project = Project(org_id=body.org_id, name=body.name, slug=body.slug)
    fleet_repo.save_project(project)
    return ProjectResponse.from_domain(project)


@router.get("/")
def list_projects(
    org_id: str,
    fleet_repo: FleetRepository = Depends(get_fleet_repo),
    pagination: PaginationParams = Depends(get_pagination),
) -> PaginatedResponse[ProjectResponse]:
    projects = fleet_repo.list_projects(org_id)
    items = [ProjectResponse.from_domain(p) for p in projects[pagination.offset:pagination.offset + pagination.limit]]
    return PaginatedResponse(items=items, total=len(projects), limit=pagination.limit, offset=pagination.offset)


@router.get("/{project_id}")
def get_project(
    project_id: str,
    fleet_repo: FleetRepository = Depends(get_fleet_repo),
) -> ProjectResponse:
    project = fleet_repo.get_project(project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found")
    return ProjectResponse.from_domain(project)


@router.put("/{project_id}")
def update_project(
    project_id: str,
    body: ProjectUpdate,
    fleet_repo: FleetRepository = Depends(get_fleet_repo),
) -> ProjectResponse:
    project = fleet_repo.get_project(project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found")
    apply_partial_update(project, body)
    fleet_repo.save_project(project)
    return ProjectResponse.from_domain(project)


@router.delete("/{project_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_project(
    project_id: str,
    fleet_repo: FleetRepository = Depends(get_fleet_repo),
) -> None:
    if not fleet_repo.delete_project(project_id):
        raise HTTPException(status_code=404, detail="Project not found")

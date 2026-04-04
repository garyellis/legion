"""Project CRUD routes."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status

from legion.api.deps import get_fleet_repo
from legion.api.schemas import ProjectCreate, ProjectUpdate
from legion.domain.project import Project
from legion.services.fleet_repository import FleetRepository

router = APIRouter(prefix="/projects", tags=["projects"])


@router.post("/", status_code=status.HTTP_201_CREATED)
def create_project(
    body: ProjectCreate,
    fleet_repo: FleetRepository = Depends(get_fleet_repo),
) -> Project:
    if fleet_repo.get_org(body.org_id) is None:
        raise HTTPException(status_code=404, detail=f"Organization {body.org_id} not found")
    project = Project(org_id=body.org_id, name=body.name, slug=body.slug)
    fleet_repo.save_project(project)
    return project


@router.get("/")
def list_projects(
    org_id: str,
    fleet_repo: FleetRepository = Depends(get_fleet_repo),
) -> list[Project]:
    return fleet_repo.list_projects(org_id)


@router.get("/{project_id}")
def get_project(
    project_id: str,
    fleet_repo: FleetRepository = Depends(get_fleet_repo),
) -> Project:
    project = fleet_repo.get_project(project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found")
    return project


@router.put("/{project_id}")
def update_project(
    project_id: str,
    body: ProjectUpdate,
    fleet_repo: FleetRepository = Depends(get_fleet_repo),
) -> Project:
    project = fleet_repo.get_project(project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found")
    if body.name is not None:
        project.name = body.name
    if body.slug is not None:
        project.slug = body.slug
    fleet_repo.save_project(project)
    return project


@router.delete("/{project_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_project(
    project_id: str,
    fleet_repo: FleetRepository = Depends(get_fleet_repo),
) -> None:
    if not fleet_repo.delete_project(project_id):
        raise HTTPException(status_code=404, detail="Project not found")

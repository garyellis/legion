"""ClusterGroup CRUD routes."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status

from legion.api.deps import get_fleet_repo
from legion.api.schemas import ClusterGroupCreate
from legion.domain.cluster_group import ClusterGroup
from legion.services.fleet_repository import FleetRepository

router = APIRouter(prefix="/cluster-groups", tags=["cluster-groups"])


@router.post("/", status_code=status.HTTP_201_CREATED)
def create_cluster_group(
    body: ClusterGroupCreate,
    fleet_repo: FleetRepository = Depends(get_fleet_repo),
) -> ClusterGroup:
    cg = ClusterGroup(
        org_id=body.org_id,
        name=body.name,
        slug=body.slug,
        environment=body.environment,
        provider=body.provider,
    )
    fleet_repo.save_cluster_group(cg)
    return cg


@router.get("/")
def list_cluster_groups(
    org_id: str,
    fleet_repo: FleetRepository = Depends(get_fleet_repo),
) -> list[ClusterGroup]:
    return fleet_repo.list_cluster_groups(org_id)


@router.get("/{cg_id}")
def get_cluster_group(
    cg_id: str,
    fleet_repo: FleetRepository = Depends(get_fleet_repo),
) -> ClusterGroup:
    cg = fleet_repo.get_cluster_group(cg_id)
    if cg is None:
        raise HTTPException(status_code=404, detail="ClusterGroup not found")
    return cg

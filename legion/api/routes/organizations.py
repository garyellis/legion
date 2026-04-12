"""Organization CRUD routes."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status

from legion.api.deps import get_fleet_repo, get_pagination
from legion.api.routes._helpers import apply_partial_update
from legion.api.schemas.organizations import (
    OrganizationCreate,
    OrganizationResponse,
    OrganizationUpdate,
)
from legion.api.schemas.pagination import PaginatedResponse, PaginationParams
from legion.domain.organization import Organization
from legion.services.fleet_repository import FleetRepository

router = APIRouter(prefix="/organizations", tags=["organizations"])


@router.post("/", status_code=status.HTTP_201_CREATED)
def create_organization(
    body: OrganizationCreate,
    fleet_repo: FleetRepository = Depends(get_fleet_repo),
) -> OrganizationResponse:
    org = Organization(name=body.name, slug=body.slug)
    fleet_repo.save_org(org)
    return OrganizationResponse.from_domain(org)


@router.get("/")
def list_organizations(
    fleet_repo: FleetRepository = Depends(get_fleet_repo),
    pagination: PaginationParams = Depends(get_pagination),
) -> PaginatedResponse[OrganizationResponse]:
    orgs = fleet_repo.list_orgs()
    items = [OrganizationResponse.from_domain(o) for o in orgs[pagination.offset:pagination.offset + pagination.limit]]
    return PaginatedResponse(items=items, total=len(orgs), limit=pagination.limit, offset=pagination.offset)


@router.get("/{org_id}")
def get_organization(
    org_id: str,
    fleet_repo: FleetRepository = Depends(get_fleet_repo),
) -> OrganizationResponse:
    org = fleet_repo.get_org(org_id)
    if org is None:
        raise HTTPException(status_code=404, detail="Organization not found")
    return OrganizationResponse.from_domain(org)


@router.put("/{org_id}")
def update_organization(
    org_id: str,
    body: OrganizationUpdate,
    fleet_repo: FleetRepository = Depends(get_fleet_repo),
) -> OrganizationResponse:
    org = fleet_repo.get_org(org_id)
    if org is None:
        raise HTTPException(status_code=404, detail="Organization not found")
    apply_partial_update(org, body)
    fleet_repo.save_org(org)
    return OrganizationResponse.from_domain(org)


@router.delete("/{org_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_organization(
    org_id: str,
    fleet_repo: FleetRepository = Depends(get_fleet_repo),
) -> None:
    if not fleet_repo.delete_org(org_id):
        raise HTTPException(status_code=404, detail="Organization not found")

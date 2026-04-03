"""Organization CRUD routes."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status

from legion.api.deps import get_fleet_repo
from legion.api.schemas import OrganizationCreate
from legion.domain.organization import Organization
from legion.services.fleet_repository import FleetRepository

router = APIRouter(prefix="/organizations", tags=["organizations"])


@router.post("/", status_code=status.HTTP_201_CREATED)
def create_organization(
    body: OrganizationCreate,
    fleet_repo: FleetRepository = Depends(get_fleet_repo),
) -> Organization:
    org = Organization(name=body.name, slug=body.slug)
    fleet_repo.save_org(org)
    return org


@router.get("/")
def list_organizations(
    fleet_repo: FleetRepository = Depends(get_fleet_repo),
) -> list[Organization]:
    return fleet_repo.list_orgs()


@router.get("/{org_id}")
def get_organization(
    org_id: str,
    fleet_repo: FleetRepository = Depends(get_fleet_repo),
) -> Organization:
    org = fleet_repo.get_org(org_id)
    if org is None:
        raise HTTPException(status_code=404, detail="Organization not found")
    return org

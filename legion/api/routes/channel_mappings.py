"""ChannelMapping CRUD routes."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Response, status

from legion.api.deps import get_fleet_repo, get_pagination
from legion.api.schemas.channel_mappings import ChannelMappingCreate, ChannelMappingResponse
from legion.api.schemas.pagination import PaginatedResponse, PaginationParams
from legion.domain.channel_mapping import ChannelMapping
from legion.services.fleet_repository import FleetRepository

router = APIRouter(prefix="/channel-mappings", tags=["channel-mappings"])


@router.post("/", status_code=status.HTTP_201_CREATED)
def create_channel_mapping(
    body: ChannelMappingCreate,
    fleet_repo: FleetRepository = Depends(get_fleet_repo),
) -> ChannelMappingResponse:
    if fleet_repo.get_org(body.org_id) is None:
        raise HTTPException(status_code=404, detail=f"Organization {body.org_id} not found")
    if fleet_repo.get_agent_group(body.agent_group_id) is None:
        raise HTTPException(status_code=404, detail=f"AgentGroup {body.agent_group_id} not found")
    mapping = ChannelMapping(
        org_id=body.org_id,
        channel_id=body.channel_id,
        agent_group_id=body.agent_group_id,
        mode=body.mode,
    )
    fleet_repo.save_channel_mapping(mapping)
    return ChannelMappingResponse.from_domain(mapping)


@router.get("/")
def list_channel_mappings(
    org_id: str,
    fleet_repo: FleetRepository = Depends(get_fleet_repo),
    pagination: PaginationParams = Depends(get_pagination),
) -> PaginatedResponse[ChannelMappingResponse]:
    mappings = fleet_repo.list_channel_mappings(org_id)
    items = [ChannelMappingResponse.from_domain(m) for m in mappings[pagination.offset:pagination.offset + pagination.limit]]
    return PaginatedResponse(items=items, total=len(mappings), limit=pagination.limit, offset=pagination.offset)


@router.get("/{mapping_id}")
def get_channel_mapping(
    mapping_id: str,
    fleet_repo: FleetRepository = Depends(get_fleet_repo),
) -> ChannelMappingResponse:
    mapping = fleet_repo.get_channel_mapping(mapping_id)
    if mapping is None:
        raise HTTPException(status_code=404, detail="ChannelMapping not found")
    return ChannelMappingResponse.from_domain(mapping)


@router.delete("/{mapping_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_channel_mapping(
    mapping_id: str,
    fleet_repo: FleetRepository = Depends(get_fleet_repo),
) -> Response:
    if not fleet_repo.delete_channel_mapping(mapping_id):
        raise HTTPException(status_code=404, detail="ChannelMapping not found")
    return Response(status_code=status.HTTP_204_NO_CONTENT)

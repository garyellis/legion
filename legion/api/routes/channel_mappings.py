"""ChannelMapping CRUD routes."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Response, status

from legion.api.deps import get_fleet_repo
from legion.api.schemas import ChannelMappingCreate
from legion.domain.channel_mapping import ChannelMapping
from legion.services.fleet_repository import FleetRepository

router = APIRouter(prefix="/channel-mappings", tags=["channel-mappings"])


@router.post("/", status_code=status.HTTP_201_CREATED)
def create_channel_mapping(
    body: ChannelMappingCreate,
    fleet_repo: FleetRepository = Depends(get_fleet_repo),
) -> ChannelMapping:
    mapping = ChannelMapping(
        org_id=body.org_id,
        channel_id=body.channel_id,
        cluster_group_id=body.cluster_group_id,
        mode=body.mode,
    )
    fleet_repo.save_channel_mapping(mapping)
    return mapping


@router.get("/")
def list_channel_mappings(
    org_id: str,
    fleet_repo: FleetRepository = Depends(get_fleet_repo),
) -> list[ChannelMapping]:
    return fleet_repo.list_channel_mappings(org_id)


@router.get("/{mapping_id}")
def get_channel_mapping(
    mapping_id: str,
    fleet_repo: FleetRepository = Depends(get_fleet_repo),
) -> ChannelMapping:
    mapping = fleet_repo.get_channel_mapping(mapping_id)
    if mapping is None:
        raise HTTPException(status_code=404, detail="ChannelMapping not found")
    return mapping


@router.delete("/{mapping_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_channel_mapping(
    mapping_id: str,
    fleet_repo: FleetRepository = Depends(get_fleet_repo),
) -> Response:
    if not fleet_repo.delete_channel_mapping(mapping_id):
        raise HTTPException(status_code=404, detail="ChannelMapping not found")
    return Response(status_code=status.HTTP_204_NO_CONTENT)

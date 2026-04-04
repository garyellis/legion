"""FilterRule CRUD routes."""

from __future__ import annotations

import re

from fastapi import APIRouter, Depends, HTTPException, Response, status

from legion.api.deps import get_fleet_repo
from legion.api.schemas import FilterRuleCreate
from legion.domain.filter_rule import FilterRule
from legion.services.fleet_repository import FleetRepository

router = APIRouter(prefix="/filter-rules", tags=["filter-rules"])


@router.post("/", status_code=status.HTTP_201_CREATED)
def create_filter_rule(
    body: FilterRuleCreate,
    fleet_repo: FleetRepository = Depends(get_fleet_repo),
) -> FilterRule:
    try:
        re.compile(body.pattern)
    except re.error as exc:
        raise HTTPException(
            status_code=422, detail=f"Invalid regex pattern: {exc}"
        ) from exc
    if fleet_repo.get_channel_mapping(body.channel_mapping_id) is None:
        raise HTTPException(
            status_code=404, detail=f"ChannelMapping {body.channel_mapping_id} not found"
        )
    rule = FilterRule(
        channel_mapping_id=body.channel_mapping_id,
        pattern=body.pattern,
        action=body.action,
        priority=body.priority,
    )
    fleet_repo.save_filter_rule(rule)
    return rule


@router.get("/")
def list_filter_rules(
    channel_mapping_id: str,
    fleet_repo: FleetRepository = Depends(get_fleet_repo),
) -> list[FilterRule]:
    return fleet_repo.list_filter_rules(channel_mapping_id)


@router.get("/{rule_id}")
def get_filter_rule(
    rule_id: str,
    fleet_repo: FleetRepository = Depends(get_fleet_repo),
) -> FilterRule:
    rule = fleet_repo.get_filter_rule(rule_id)
    if rule is None:
        raise HTTPException(status_code=404, detail="FilterRule not found")
    return rule


@router.delete("/{rule_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_filter_rule(
    rule_id: str,
    fleet_repo: FleetRepository = Depends(get_fleet_repo),
) -> Response:
    if not fleet_repo.delete_filter_rule(rule_id):
        raise HTTPException(status_code=404, detail="FilterRule not found")
    return Response(status_code=status.HTTP_204_NO_CONTENT)

"""Agent read-only routes (agents register via WebSocket)."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from legion.api.deps import get_fleet_repo
from legion.domain.agent import Agent
from legion.services.fleet_repository import FleetRepository

router = APIRouter(prefix="/agents", tags=["agents"])


@router.get("/")
def list_agents(
    cluster_group_id: str,
    fleet_repo: FleetRepository = Depends(get_fleet_repo),
) -> list[Agent]:
    return fleet_repo.list_agents(cluster_group_id)


@router.get("/{agent_id}")
def get_agent(
    agent_id: str,
    fleet_repo: FleetRepository = Depends(get_fleet_repo),
) -> Agent:
    agent = fleet_repo.get_agent(agent_id)
    if agent is None:
        raise HTTPException(status_code=404, detail="Agent not found")
    return agent

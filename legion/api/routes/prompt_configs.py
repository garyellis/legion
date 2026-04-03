"""PromptConfig upsert/get routes."""

from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException

from legion.api.deps import get_fleet_repo
from legion.api.schemas import PromptConfigUpsert
from legion.domain.prompt_config import PromptConfig
from legion.services.fleet_repository import FleetRepository

router = APIRouter(prefix="/prompt-configs", tags=["prompt-configs"])


@router.put("/{cluster_group_id}")
def upsert_prompt_config(
    cluster_group_id: str,
    body: PromptConfigUpsert,
    fleet_repo: FleetRepository = Depends(get_fleet_repo),
) -> PromptConfig:
    existing = fleet_repo.get_prompt_config_by_cluster(cluster_group_id)
    if existing is not None:
        existing.system_prompt = body.system_prompt
        existing.stack_manifest = body.stack_manifest
        existing.persona = body.persona
        existing.updated_at = datetime.now(timezone.utc)
        fleet_repo.save_prompt_config(existing)
        return existing

    config = PromptConfig(
        cluster_group_id=cluster_group_id,
        system_prompt=body.system_prompt,
        stack_manifest=body.stack_manifest,
        persona=body.persona,
    )
    fleet_repo.save_prompt_config(config)
    return config


@router.get("/{cluster_group_id}")
def get_prompt_config(
    cluster_group_id: str,
    fleet_repo: FleetRepository = Depends(get_fleet_repo),
) -> PromptConfig:
    config = fleet_repo.get_prompt_config_by_cluster(cluster_group_id)
    if config is None:
        raise HTTPException(status_code=404, detail="PromptConfig not found")
    return config

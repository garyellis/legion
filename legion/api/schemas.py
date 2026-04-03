"""Request schemas for the API surface.

Domain models serve as response models directly (already Pydantic BaseModels).
These thin *Create / *Upsert schemas handle POST/PUT request bodies.
"""

from __future__ import annotations

from pydantic import BaseModel

from legion.domain.channel_mapping import ChannelMode
from legion.domain.filter_rule import FilterAction


class OrganizationCreate(BaseModel):
    name: str
    slug: str


class ClusterGroupCreate(BaseModel):
    org_id: str
    name: str
    slug: str
    environment: str
    provider: str


class ChannelMappingCreate(BaseModel):
    org_id: str
    channel_id: str
    cluster_group_id: str
    mode: ChannelMode = ChannelMode.ALERT


class FilterRuleCreate(BaseModel):
    channel_mapping_id: str
    pattern: str
    action: FilterAction = FilterAction.TRIAGE
    priority: int = 0


class PromptConfigUpsert(BaseModel):
    system_prompt: str = ""
    stack_manifest: str = ""
    persona: str = ""


class SessionCreate(BaseModel):
    org_id: str
    cluster_group_id: str


class SessionMessage(BaseModel):
    payload: str

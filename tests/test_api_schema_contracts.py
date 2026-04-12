"""Contract / drift tests: server-side API schemas <-> domain models <-> client-side models.

Finding #1: Server-side and client-side response models must stay in sync.
Finding #2: Server-side DTOs must be a strict subset of domain model fields,
            with any omissions explicitly listed.
Finding #10: Bidirectional drift detection via exclusion allowlists.
"""

from __future__ import annotations

import pytest

# --- Server-side response DTOs (api/schemas/) ---
from legion.api.schemas.agent_groups import (
    AgentGroupResponse as ServerAgentGroupResponse,
    AgentGroupTokenResponse as ServerAgentGroupTokenResponse,
)
from legion.api.schemas.agents import (
    AgentConnectionConfig as ServerAgentConnectionConfig,
    AgentRegistrationResponse as ServerAgentRegistrationResponse,
    AgentResponse as ServerAgentResponse,
)
from legion.api.schemas.channel_mappings import (
    ChannelMappingResponse as ServerChannelMappingResponse,
)
from legion.api.schemas.filter_rules import FilterRuleResponse as ServerFilterRuleResponse
from legion.api.schemas.jobs import JobResponse as ServerJobResponse
from legion.api.schemas.organizations import (
    OrganizationResponse as ServerOrganizationResponse,
)
from legion.api.schemas.projects import ProjectResponse as ServerProjectResponse
from legion.api.schemas.prompt_configs import (
    PromptConfigResponse as ServerPromptConfigResponse,
)
from legion.api.schemas.sessions import SessionResponse as ServerSessionResponse

# --- Client-side response models (core/fleet_api/models.py) ---
from legion.core.fleet_api.models import (
    AgentConnectionConfig as ClientAgentConnectionConfig,
    AgentGroupResponse as ClientAgentGroupResponse,
    AgentGroupTokenResponse as ClientAgentGroupTokenResponse,
    AgentRegistrationResponse as ClientAgentRegistrationResponse,
    AgentResponse as ClientAgentResponse,
    OrgResponse as ClientOrgResponse,
    ProjectResponse as ClientProjectResponse,
)

# --- Domain models ---
from legion.domain.agent import Agent
from legion.domain.agent_group import AgentGroup
from legion.domain.channel_mapping import ChannelMapping
from legion.domain.filter_rule import FilterRule
from legion.domain.job import Job
from legion.domain.organization import Organization
from legion.domain.project import Project
from legion.domain.prompt_config import PromptConfig
from legion.domain.session import Session


# ---------------------------------------------------------------------------
# Category 1 & 4: Server response DTOs vs domain models (subset + drift)
# ---------------------------------------------------------------------------

RESPONSE_DOMAIN_PAIRS = [
    (ServerOrganizationResponse, Organization, set()),
    (ServerProjectResponse, Project, set()),
    (ServerAgentGroupResponse, AgentGroup, {"registration_token_hash", "registration_token_rotated_at"}),
    (ServerAgentResponse, Agent, set()),
    (ServerJobResponse, Job, set()),
    (ServerSessionResponse, Session, set()),
    (ServerChannelMappingResponse, ChannelMapping, set()),
    (ServerFilterRuleResponse, FilterRule, set()),
    (ServerPromptConfigResponse, PromptConfig, set()),
]


def _pair_id(val: object) -> str:
    return getattr(val, "__name__", str(val))


@pytest.mark.parametrize(
    "response_cls,domain_cls,excluded",
    RESPONSE_DOMAIN_PAIRS,
    ids=lambda x: _pair_id(x),
)
def test_response_fields_subset_of_domain(response_cls, domain_cls, excluded):
    """Every response field must exist on the domain model."""
    response_fields = set(response_cls.model_fields.keys())
    domain_fields = set(domain_cls.model_fields.keys())
    extra = response_fields - domain_fields
    assert not extra, (
        f"{response_cls.__name__} has fields not in {domain_cls.__name__}: {extra}"
    )


@pytest.mark.parametrize(
    "response_cls,domain_cls,excluded",
    RESPONSE_DOMAIN_PAIRS,
    ids=lambda x: _pair_id(x),
)
def test_no_accidental_field_omission(response_cls, domain_cls, excluded):
    """Every domain field must be either in the response or explicitly excluded."""
    response_fields = set(response_cls.model_fields.keys())
    domain_fields = set(domain_cls.model_fields.keys())
    unaccounted = domain_fields - response_fields - excluded
    assert not unaccounted, (
        f"Domain fields on {domain_cls.__name__} missing from "
        f"{response_cls.__name__} and not in exclusion list: {unaccounted}"
    )


# ---------------------------------------------------------------------------
# Category 2: Sensitive fields explicitly excluded
# ---------------------------------------------------------------------------


def test_agent_group_response_excludes_token_hash():
    """registration_token_hash must never appear in API responses."""
    assert "registration_token_hash" not in ServerAgentGroupResponse.model_fields
    assert "registration_token_rotated_at" not in ServerAgentGroupResponse.model_fields


def test_agent_group_response_excluded_fields_annotation():
    """The _excluded_domain_fields ClassVar must match our exclusion set."""
    expected = frozenset({"registration_token_hash", "registration_token_rotated_at"})
    assert ServerAgentGroupResponse._excluded_domain_fields == expected


# ---------------------------------------------------------------------------
# Category 3: Server-side and client-side models in sync (Finding #1)
# ---------------------------------------------------------------------------

SERVER_CLIENT_PAIRS = [
    (ServerOrganizationResponse, ClientOrgResponse),
    (ServerProjectResponse, ClientProjectResponse),
    (ServerAgentGroupResponse, ClientAgentGroupResponse),
    (ServerAgentResponse, ClientAgentResponse),
    (ServerAgentGroupTokenResponse, ClientAgentGroupTokenResponse),
    (ServerAgentConnectionConfig, ClientAgentConnectionConfig),
]


@pytest.mark.parametrize(
    "server_cls,client_cls",
    SERVER_CLIENT_PAIRS,
    ids=lambda x: _pair_id(x),
)
def test_server_client_field_parity(server_cls, client_cls):
    """Server response fields must match client deserialization fields."""
    server_fields = set(server_cls.model_fields.keys())
    client_fields = set(client_cls.model_fields.keys())
    assert server_fields == client_fields, (
        f"Field mismatch between {server_cls.__name__} and {client_cls.__name__} -- "
        f"server-only: {server_fields - client_fields}, "
        f"client-only: {client_fields - server_fields}"
    )


def test_registration_response_field_parity():
    """AgentRegistrationResponse top-level fields must match across server/client."""
    server_fields = set(ServerAgentRegistrationResponse.model_fields.keys())
    client_fields = set(ClientAgentRegistrationResponse.model_fields.keys())
    assert server_fields == client_fields, (
        f"AgentRegistrationResponse field mismatch -- "
        f"server-only: {server_fields - client_fields}, "
        f"client-only: {client_fields - server_fields}"
    )

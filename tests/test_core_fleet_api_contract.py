"""Contract tests: domain model serialization ↔ Fleet API response models.

These tests verify that the core/fleet_api response models can parse the
JSON that FastAPI produces when serializing domain models.  If a field is
renamed or its type changes in the domain layer, these tests break before
production does.
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from legion.core.fleet_api.models import AgentGroupResponse, AgentResponse, OrgResponse
from legion.domain.agent import Agent, AgentStatus
from legion.domain.agent_group import AgentGroup, ExecutionMode
from legion.domain.organization import Organization

NOW = datetime(2026, 1, 1, tzinfo=timezone.utc)


class TestOrganizationContract:
    """Organization domain model → OrgResponse round-trip."""

    def test_org_round_trip(self) -> None:
        org = Organization(id="org-1", name="Acme", slug="acme", created_at=NOW, updated_at=NOW)
        data = org.model_dump(mode="json")
        resp = OrgResponse.model_validate(data)

        assert resp.id == org.id
        assert resp.name == org.name
        assert resp.slug == org.slug
        assert resp.created_at == org.created_at
        assert resp.updated_at == org.updated_at

    def test_org_response_fields_subset_of_domain(self) -> None:
        """Every field in OrgResponse must exist in Organization."""
        response_fields = set(OrgResponse.model_fields)
        domain_fields = set(Organization.model_fields)
        missing = response_fields - domain_fields
        assert not missing, f"OrgResponse has fields not in Organization: {missing}"


class TestAgentGroupContract:
    """AgentGroup domain model → AgentGroupResponse round-trip."""

    def test_agent_group_round_trip(self) -> None:
        ag = AgentGroup(
            id="ag-1", org_id="org-1", project_id="proj-1",
            name="Prod SRE", slug="prod-sre",
            environment="prod", provider="eks",
            execution_mode=ExecutionMode.READ_ONLY,
            created_at=NOW, updated_at=NOW,
        )
        data = ag.model_dump(mode="json")
        resp = AgentGroupResponse.model_validate(data)

        assert resp.id == ag.id
        assert resp.org_id == ag.org_id
        assert resp.name == ag.name
        assert resp.slug == ag.slug
        assert resp.environment == ag.environment
        assert resp.provider == ag.provider
        assert resp.execution_mode == ag.execution_mode.value
        assert resp.created_at == ag.created_at
        assert resp.updated_at == ag.updated_at

    @pytest.mark.parametrize("mode", list(ExecutionMode))
    def test_all_execution_modes_parse(self, mode: ExecutionMode) -> None:
        ag = AgentGroup(
            id="ag-1", org_id="org-1", project_id="proj-1",
            name="Test", slug="test",
            environment="dev", provider="on-prem",
            execution_mode=mode,
            created_at=NOW, updated_at=NOW,
        )
        data = ag.model_dump(mode="json")
        resp = AgentGroupResponse.model_validate(data)
        assert resp.execution_mode == mode.value

    def test_agent_group_response_fields_subset_of_domain(self) -> None:
        response_fields = set(AgentGroupResponse.model_fields)
        domain_fields = set(AgentGroup.model_fields)
        missing = response_fields - domain_fields
        assert not missing, f"AgentGroupResponse has fields not in AgentGroup: {missing}"


class TestAgentContract:
    """Agent domain model → AgentResponse round-trip."""

    def test_agent_round_trip_idle(self) -> None:
        agent = Agent(
            id="a-1", agent_group_id="ag-1", name="sre-1",
            status=AgentStatus.IDLE, capabilities=["k8s", "monitoring"],
            last_heartbeat=NOW, created_at=NOW, updated_at=NOW,
        )
        data = agent.model_dump(mode="json")
        resp = AgentResponse.model_validate(data)

        assert resp.id == agent.id
        assert resp.agent_group_id == agent.agent_group_id
        assert resp.name == agent.name
        assert resp.status == agent.status.value
        assert resp.capabilities == agent.capabilities
        assert resp.last_heartbeat == agent.last_heartbeat
        assert resp.current_job_id is None

    def test_agent_round_trip_busy_with_job(self) -> None:
        agent = Agent(
            id="a-2", agent_group_id="ag-1", name="sre-2",
            status=AgentStatus.BUSY, current_job_id="job-99",
            capabilities=["k8s"],
            last_heartbeat=NOW, created_at=NOW, updated_at=NOW,
        )
        data = agent.model_dump(mode="json")
        resp = AgentResponse.model_validate(data)

        assert resp.status == "BUSY"
        assert resp.current_job_id == "job-99"

    def test_agent_round_trip_offline_no_heartbeat(self) -> None:
        agent = Agent(
            id="a-3", agent_group_id="ag-1", name="sre-3",
            status=AgentStatus.OFFLINE,
            created_at=NOW, updated_at=NOW,
        )
        data = agent.model_dump(mode="json")
        resp = AgentResponse.model_validate(data)

        assert resp.status == "OFFLINE"
        assert resp.last_heartbeat is None
        assert resp.capabilities == []

    @pytest.mark.parametrize("status", list(AgentStatus))
    def test_all_agent_statuses_parse(self, status: AgentStatus) -> None:
        agent = Agent(
            id="a-1", agent_group_id="ag-1", name="test",
            status=status, created_at=NOW, updated_at=NOW,
        )
        data = agent.model_dump(mode="json")
        resp = AgentResponse.model_validate(data)
        assert resp.status == status.value

    def test_agent_response_fields_subset_of_domain(self) -> None:
        response_fields = set(AgentResponse.model_fields)
        domain_fields = set(Agent.model_fields)
        missing = response_fields - domain_fields
        assert not missing, f"AgentResponse has fields not in Agent: {missing}"

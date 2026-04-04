"""Tests for the fleet CLI commands, core client, and views."""

from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import httpx
import pytest
import typer
from typer.testing import CliRunner

from legion.core.fleet_api.client import FleetAPIClient, FleetAPIError
from legion.core.fleet_api.models import AgentGroupResponse, AgentResponse, OrgResponse


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

runner = CliRunner()

NOW = datetime(2026, 1, 1, tzinfo=timezone.utc)

SAMPLE_ORG = OrgResponse(
    id="org-001", name="Acme Corp", slug="acme-corp",
    created_at=NOW, updated_at=NOW,
)

SAMPLE_AGENT_GROUP = AgentGroupResponse(
    id="ag-001", org_id="org-001", name="Production SRE", slug="prod-sre",
    environment="prod", provider="eks", execution_mode="READ_ONLY",
    created_at=NOW, updated_at=NOW,
)

SAMPLE_AGENTS = [
    AgentResponse(
        id="agent-001", agent_group_id="ag-001", name="sre-agent-1",
        status="IDLE", capabilities=["k8s", "monitoring"],
        last_heartbeat=NOW, created_at=NOW, updated_at=NOW,
    ),
    AgentResponse(
        id="agent-002", agent_group_id="ag-001", name="sre-agent-2",
        status="BUSY", capabilities=["k8s"],
        last_heartbeat=NOW, created_at=NOW, updated_at=NOW,
    ),
    AgentResponse(
        id="agent-003", agent_group_id="ag-001", name="sre-agent-3",
        status="OFFLINE", capabilities=[],
        last_heartbeat=None, created_at=NOW, updated_at=NOW,
    ),
]


def _get_app():
    """Build a fresh Typer app with fleet commands registered."""
    from legion.plumbing.registry import get_registry

    import legion.cli.commands.fleet  # noqa: F401

    app = typer.Typer()
    group_apps: dict[str, typer.Typer] = {}

    for group, name, func in get_registry():
        parts = group.split(".")
        for i, part in enumerate(parts):
            key = ".".join(parts[: i + 1])
            if key not in group_apps:
                group_apps[key] = typer.Typer()
                parent_key = ".".join(parts[:i]) if i > 0 else None
                parent = group_apps[parent_key] if parent_key else app
                parent.add_typer(group_apps[key], name=part)
        group_apps[group].command(name)(func)

    return app


# ---------------------------------------------------------------------------
# Core Client Tests
# ---------------------------------------------------------------------------


class TestFleetAPIClient:
    """Test the FleetAPIClient HTTP wrapper."""

    @patch("legion.core.fleet_api.client.httpx.Client")
    def test_list_orgs(self, mock_httpx_cls):
        mock_response = MagicMock()
        mock_response.is_success = True
        mock_response.json.return_value = [SAMPLE_ORG.model_dump(mode="json")]
        mock_httpx_cls.return_value.get.return_value = mock_response

        client = FleetAPIClient(base_url="http://test:8000")
        result = client.list_orgs()

        assert len(result) == 1
        assert isinstance(result[0], OrgResponse)
        assert result[0].name == "Acme Corp"

    @patch("legion.core.fleet_api.client.httpx.Client")
    def test_create_org(self, mock_httpx_cls):
        mock_response = MagicMock()
        mock_response.is_success = True
        mock_response.json.return_value = SAMPLE_ORG.model_dump(mode="json")
        mock_httpx_cls.return_value.post.return_value = mock_response

        client = FleetAPIClient(base_url="http://test:8000")
        result = client.create_org(name="Acme Corp", slug="acme-corp")

        assert isinstance(result, OrgResponse)
        assert result.slug == "acme-corp"
        mock_httpx_cls.return_value.post.assert_called_once_with(
            "/organizations/", json={"name": "Acme Corp", "slug": "acme-corp"},
        )

    @patch("legion.core.fleet_api.client.httpx.Client")
    def test_api_key_header(self, mock_httpx_cls):
        FleetAPIClient(base_url="http://test:8000", api_key="secret-key")
        call_kwargs = mock_httpx_cls.call_args[1]
        assert call_kwargs["headers"]["X-API-Key"] == "secret-key"

    @patch("legion.core.fleet_api.client.httpx.Client")
    def test_no_api_key_header_when_empty(self, mock_httpx_cls):
        FleetAPIClient(base_url="http://test:8000")
        call_kwargs = mock_httpx_cls.call_args[1]
        assert "X-API-Key" not in call_kwargs["headers"]

    @patch("legion.core.fleet_api.client.httpx.Client")
    def test_raises_fleet_api_error(self, mock_httpx_cls):
        mock_response = MagicMock()
        mock_response.is_success = False
        mock_response.status_code = 401
        mock_response.json.return_value = {"detail": "Unauthorized"}
        mock_httpx_cls.return_value.get.return_value = mock_response

        client = FleetAPIClient(base_url="http://test:8000")
        with pytest.raises(FleetAPIError) as exc_info:
            client.list_orgs()

        assert exc_info.value.status_code == 401
        assert "Unauthorized" in exc_info.value.detail

    @patch("legion.core.fleet_api.client.httpx.Client")
    def test_list_agents(self, mock_httpx_cls):
        mock_response = MagicMock()
        mock_response.is_success = True
        mock_response.json.return_value = [a.model_dump(mode="json") for a in SAMPLE_AGENTS]
        mock_httpx_cls.return_value.get.return_value = mock_response

        client = FleetAPIClient(base_url="http://test:8000")
        result = client.list_agents("ag-001")

        assert len(result) == 3
        assert all(isinstance(a, AgentResponse) for a in result)
        mock_httpx_cls.return_value.get.assert_called_once_with(
            "/agents/", params={"agent_group_id": "ag-001"},
        )

    @patch("legion.core.fleet_api.client.httpx.Client")
    def test_create_agent_group(self, mock_httpx_cls):
        mock_response = MagicMock()
        mock_response.is_success = True
        mock_response.json.return_value = SAMPLE_AGENT_GROUP.model_dump(mode="json")
        mock_httpx_cls.return_value.post.return_value = mock_response

        client = FleetAPIClient(base_url="http://test:8000")
        result = client.create_agent_group(
            org_id="org-001", name="Production SRE", slug="prod-sre",
            environment="prod", provider="eks",
        )

        assert isinstance(result, AgentGroupResponse)
        assert result.environment == "prod"

    @patch("legion.core.fleet_api.client.httpx.Client")
    def test_get_org(self, mock_httpx_cls):
        mock_response = MagicMock()
        mock_response.is_success = True
        mock_response.json.return_value = SAMPLE_ORG.model_dump(mode="json")
        mock_httpx_cls.return_value.get.return_value = mock_response

        client = FleetAPIClient(base_url="http://test:8000")
        result = client.get_org("org-001")

        assert isinstance(result, OrgResponse)
        assert result.id == "org-001"
        mock_httpx_cls.return_value.get.assert_called_once_with(
            "/organizations/org-001", params=None,
        )

    @patch("legion.core.fleet_api.client.httpx.Client")
    def test_get_agent_group(self, mock_httpx_cls):
        mock_response = MagicMock()
        mock_response.is_success = True
        mock_response.json.return_value = SAMPLE_AGENT_GROUP.model_dump(mode="json")
        mock_httpx_cls.return_value.get.return_value = mock_response

        client = FleetAPIClient(base_url="http://test:8000")
        result = client.get_agent_group("ag-001")

        assert isinstance(result, AgentGroupResponse)
        mock_httpx_cls.return_value.get.assert_called_once_with(
            "/agent-groups/ag-001", params=None,
        )

    @patch("legion.core.fleet_api.client.httpx.Client")
    def test_get_agent(self, mock_httpx_cls):
        mock_response = MagicMock()
        mock_response.is_success = True
        mock_response.json.return_value = SAMPLE_AGENTS[0].model_dump(mode="json")
        mock_httpx_cls.return_value.get.return_value = mock_response

        client = FleetAPIClient(base_url="http://test:8000")
        result = client.get_agent("agent-001")

        assert isinstance(result, AgentResponse)
        mock_httpx_cls.return_value.get.assert_called_once_with(
            "/agents/agent-001", params=None,
        )

    @pytest.mark.parametrize("status_code,expected_retryable", [
        (400, False),
        (401, False),
        (403, False),
        (404, False),
        (429, True),
        (500, False),
        (502, True),
        (503, True),
        (504, True),
    ])
    def test_retryable_flag(self, status_code, expected_retryable):
        error = FleetAPIError(status_code, "test")
        assert error.retryable is expected_retryable

    def test_context_manager(self):
        with patch("legion.core.fleet_api.client.httpx.Client") as mock_httpx_cls:
            with FleetAPIClient(base_url="http://test:8000") as client:
                assert client is not None
            mock_httpx_cls.return_value.close.assert_called_once()


# ---------------------------------------------------------------------------
# View Tests
# ---------------------------------------------------------------------------


class TestFleetViews:
    """Test Rich view rendering with typed response models."""

    def test_display_created_org(self):
        from legion.cli.views.fleet import display_created_org
        display_created_org(SAMPLE_ORG)

    def test_display_org_list(self):
        from legion.cli.views.fleet import display_org_list
        display_org_list([SAMPLE_ORG])

    def test_display_org_list_empty(self):
        from legion.cli.views.fleet import display_org_list
        display_org_list([])

    def test_display_created_agent_group(self):
        from legion.cli.views.fleet import display_created_agent_group
        display_created_agent_group(SAMPLE_AGENT_GROUP)

    def test_display_agent_group_list(self):
        from legion.cli.views.fleet import display_agent_group_list
        display_agent_group_list([SAMPLE_AGENT_GROUP])

    def test_display_agent_group_list_empty(self):
        from legion.cli.views.fleet import display_agent_group_list
        display_agent_group_list([])

    def test_display_agent_list(self):
        from legion.cli.views.fleet import display_agent_list
        display_agent_list(SAMPLE_AGENTS)

    def test_display_agent_list_empty(self):
        from legion.cli.views.fleet import display_agent_list
        display_agent_list([])

    def test_display_agent_status(self):
        from legion.cli.views.fleet import display_agent_status
        display_agent_status(SAMPLE_AGENTS)

    def test_display_agent_status_empty(self):
        from legion.cli.views.fleet import display_agent_status
        display_agent_status([])


# ---------------------------------------------------------------------------
# Command Integration Tests (mocked client)
# ---------------------------------------------------------------------------


def _mock_client_ctx(mock_client: MagicMock) -> MagicMock:
    """Configure a mock _build_client to return a context-manager-compatible mock."""
    ctx = MagicMock()
    ctx.__enter__ = MagicMock(return_value=mock_client)
    ctx.__exit__ = MagicMock(return_value=False)
    return ctx


class TestOrgCommands:
    """Test org CLI commands with mocked FleetAPIClient."""

    @patch("legion.cli.commands.fleet._build_client")
    def test_org_create(self, mock_build):
        mock_client = MagicMock(spec=FleetAPIClient)
        mock_client.create_org.return_value = SAMPLE_ORG
        mock_build.return_value = _mock_client_ctx(mock_client)

        app = _get_app()
        result = runner.invoke(
            app, ["org", "create", "--name", "Acme Corp", "--slug", "acme-corp"]
        )
        assert result.exit_code == 0
        mock_client.create_org.assert_called_once_with(name="Acme Corp", slug="acme-corp")

    @patch("legion.cli.commands.fleet._build_client")
    def test_org_list(self, mock_build):
        mock_client = MagicMock(spec=FleetAPIClient)
        mock_client.list_orgs.return_value = [SAMPLE_ORG]
        mock_build.return_value = _mock_client_ctx(mock_client)

        app = _get_app()
        result = runner.invoke(app, ["org", "list"])
        assert result.exit_code == 0
        mock_client.list_orgs.assert_called_once()

    @patch("legion.cli.commands.fleet._build_client")
    def test_org_create_api_error(self, mock_build):
        mock_client = MagicMock(spec=FleetAPIClient)
        mock_client.create_org.side_effect = FleetAPIError(409, "Slug already exists")
        mock_build.return_value = _mock_client_ctx(mock_client)

        app = _get_app()
        result = runner.invoke(
            app, ["org", "create", "--name", "Acme", "--slug", "acme"]
        )
        assert result.exit_code == 1


class TestAgentGroupCommands:
    """Test agent-group CLI commands with mocked FleetAPIClient."""

    @patch("legion.cli.commands.fleet._build_client")
    def test_agent_group_create(self, mock_build):
        mock_client = MagicMock(spec=FleetAPIClient)
        mock_client.create_agent_group.return_value = SAMPLE_AGENT_GROUP
        mock_build.return_value = _mock_client_ctx(mock_client)

        app = _get_app()
        result = runner.invoke(
            app,
            [
                "agent-group", "create",
                "--org-id", "org-001",
                "--name", "Production SRE",
                "--slug", "prod-sre",
                "--environment", "prod",
                "--provider", "eks",
            ],
        )
        assert result.exit_code == 0
        mock_client.create_agent_group.assert_called_once_with(
            org_id="org-001", name="Production SRE", slug="prod-sre",
            environment="prod", provider="eks",
        )

    @patch("legion.cli.commands.fleet._build_client")
    def test_agent_group_list(self, mock_build):
        mock_client = MagicMock(spec=FleetAPIClient)
        mock_client.list_agent_groups.return_value = [SAMPLE_AGENT_GROUP]
        mock_build.return_value = _mock_client_ctx(mock_client)

        app = _get_app()
        result = runner.invoke(
            app, ["agent-group", "list", "--org-id", "org-001"]
        )
        assert result.exit_code == 0
        mock_client.list_agent_groups.assert_called_once_with("org-001")


class TestAgentCommands:
    """Test agent CLI commands with mocked FleetAPIClient."""

    @patch("legion.cli.commands.fleet._build_client")
    def test_agent_list(self, mock_build):
        mock_client = MagicMock(spec=FleetAPIClient)
        mock_client.list_agents.return_value = SAMPLE_AGENTS
        mock_build.return_value = _mock_client_ctx(mock_client)

        app = _get_app()
        result = runner.invoke(
            app, ["agent", "list", "--agent-group-id", "ag-001"]
        )
        assert result.exit_code == 0
        mock_client.list_agents.assert_called_once_with("ag-001")

    @patch("legion.cli.commands.fleet._build_client")
    def test_agent_status(self, mock_build):
        mock_client = MagicMock(spec=FleetAPIClient)
        mock_client.list_agents.return_value = SAMPLE_AGENTS
        mock_build.return_value = _mock_client_ctx(mock_client)

        app = _get_app()
        result = runner.invoke(
            app, ["agent", "status", "--agent-group-id", "ag-001"]
        )
        assert result.exit_code == 0
        mock_client.list_agents.assert_called_once_with("ag-001")

    @patch("legion.cli.commands.fleet._build_client")
    def test_agent_list_connection_error(self, mock_build):
        mock_client = MagicMock(spec=FleetAPIClient)
        mock_client.list_agents.side_effect = httpx.ConnectError("Connection refused")
        mock_build.return_value = _mock_client_ctx(mock_client)

        app = _get_app()
        result = runner.invoke(
            app, ["agent", "list", "--agent-group-id", "ag-001"]
        )
        assert result.exit_code == 1

"""Fleet management commands — org, agent-group, agent."""

from __future__ import annotations

from typing import Annotated

import httpx
import typer

from legion.cli.registry import register_command
from legion.cli.views import render_error
from legion.cli.views.fleet import (
    display_agent_group_list,
    display_agent_list,
    display_agent_status,
    display_created_agent_group,
    display_created_org,
    display_org_list,
)
from legion.core.fleet_api.client import FleetAPIClient, FleetAPIError
from legion.core.fleet_api.config import FleetAPIConfig


def _build_client(
    api_url: str | None = None,
    api_key: str | None = None,
) -> FleetAPIClient:
    config = FleetAPIConfig()
    resolved_url = api_url if api_url is not None else config.api_url
    resolved_key = api_key if api_key is not None else config.api_key.get_secret_value()
    return FleetAPIClient(base_url=resolved_url, api_key=resolved_key)


def _handle_error(e: Exception) -> None:
    if isinstance(e, FleetAPIError):
        render_error(f"API error: {e.detail}", hint=f"Status code: {e.status_code}")
    elif isinstance(e, httpx.ConnectError):
        render_error("Connection refused", hint="Is the API server running?")
    else:
        render_error(str(e))


# --- Organization commands ---


@register_command("org", "create")
def org_create(
    name: Annotated[str, typer.Option(help="Organization name")],
    slug: Annotated[str, typer.Option(help="URL-friendly slug")],
    api_url: Annotated[str | None, typer.Option(envvar="LEGION_FLEET_API_URL", help="API base URL")] = None,
    api_key: Annotated[str | None, typer.Option(envvar="LEGION_FLEET_API_KEY", help="API key")] = None,
) -> None:
    """Create a new organization."""
    try:
        with _build_client(api_url, api_key) as client:
            org = client.create_org(name=name, slug=slug)
            display_created_org(org)
    except Exception as e:
        _handle_error(e)
        raise typer.Exit(1)


@register_command("org", "list")
def org_list(
    api_url: Annotated[str | None, typer.Option(envvar="LEGION_FLEET_API_URL", help="API base URL")] = None,
    api_key: Annotated[str | None, typer.Option(envvar="LEGION_FLEET_API_KEY", help="API key")] = None,
) -> None:
    """List all organizations."""
    try:
        with _build_client(api_url, api_key) as client:
            orgs = client.list_orgs()
            display_org_list(orgs)
    except Exception as e:
        _handle_error(e)
        raise typer.Exit(1)


# --- Agent Group commands ---


@register_command("agent-group", "create")
def agent_group_create(
    org_id: Annotated[str, typer.Option(help="Organization ID")],
    name: Annotated[str, typer.Option(help="Agent group name")],
    slug: Annotated[str, typer.Option(help="URL-friendly slug")],
    environment: Annotated[str, typer.Option(help="Environment (dev, staging, prod)")] = "dev",
    provider: Annotated[str, typer.Option(help="Provider (aks, eks, gke, on-prem)")] = "on-prem",
    api_url: Annotated[str | None, typer.Option(envvar="LEGION_FLEET_API_URL", help="API base URL")] = None,
    api_key: Annotated[str | None, typer.Option(envvar="LEGION_FLEET_API_KEY", help="API key")] = None,
) -> None:
    """Create a new agent group."""
    try:
        with _build_client(api_url, api_key) as client:
            ag = client.create_agent_group(
                org_id=org_id, name=name, slug=slug,
                environment=environment, provider=provider,
            )
            display_created_agent_group(ag)
    except Exception as e:
        _handle_error(e)
        raise typer.Exit(1)


@register_command("agent-group", "list")
def agent_group_list(
    org_id: Annotated[str, typer.Option(help="Organization ID")],
    api_url: Annotated[str | None, typer.Option(envvar="LEGION_FLEET_API_URL", help="API base URL")] = None,
    api_key: Annotated[str | None, typer.Option(envvar="LEGION_FLEET_API_KEY", help="API key")] = None,
) -> None:
    """List agent groups for an organization."""
    try:
        with _build_client(api_url, api_key) as client:
            groups = client.list_agent_groups(org_id)
            display_agent_group_list(groups)
    except Exception as e:
        _handle_error(e)
        raise typer.Exit(1)


# --- Agent commands ---


@register_command("agent", "list")
def agent_list(
    agent_group_id: Annotated[str, typer.Option(help="Agent group ID")],
    api_url: Annotated[str | None, typer.Option(envvar="LEGION_FLEET_API_URL", help="API base URL")] = None,
    api_key: Annotated[str | None, typer.Option(envvar="LEGION_FLEET_API_KEY", help="API key")] = None,
) -> None:
    """List agents in an agent group."""
    try:
        with _build_client(api_url, api_key) as client:
            agents = client.list_agents(agent_group_id)
            display_agent_list(agents)
    except Exception as e:
        _handle_error(e)
        raise typer.Exit(1)


@register_command("agent", "status")
def agent_status(
    agent_group_id: Annotated[str, typer.Option(help="Agent group ID")],
    api_url: Annotated[str | None, typer.Option(envvar="LEGION_FLEET_API_URL", help="API base URL")] = None,
    api_key: Annotated[str | None, typer.Option(envvar="LEGION_FLEET_API_KEY", help="API key")] = None,
) -> None:
    """Show agent status summary for an agent group."""
    try:
        with _build_client(api_url, api_key) as client:
            agents = client.list_agents(agent_group_id)
            display_agent_status(agents)
    except Exception as e:
        _handle_error(e)
        raise typer.Exit(1)

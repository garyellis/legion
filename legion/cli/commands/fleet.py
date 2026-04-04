"""Fleet management commands — org, agent-group, agent."""

from __future__ import annotations

from typing import Annotated

import httpx
import typer

from legion.plumbing.registry import register_command
from legion.cli.views import render_error
from legion.cli.views.fleet import (
    display_agent_group_list,
    display_agent_list,
    display_agent_status,
    display_created_agent_group,
    display_created_org,
    display_created_project,
    display_deleted_agent_group,
    display_deleted_org,
    display_deleted_project,
    display_org_list,
    display_project_list,
    display_updated_agent_group,
    display_updated_org,
    display_updated_project,
)
from legion.core.fleet_api.client import FleetAPIClient, FleetAPIError
from legion.core.fleet_api.config import FleetAPIConfig


# --- Common option type aliases ---

_OutputOpt = Annotated[str, typer.Option("--output", "-o", help="Output format: table or json")]
_ApiUrlOpt = Annotated[str | None, typer.Option(envvar="LEGION_FLEET_API_URL", help="API base URL")]
_ApiKeyOpt = Annotated[str | None, typer.Option(envvar="LEGION_FLEET_API_KEY", help="API key")]


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
    output: _OutputOpt = "table",
    api_url: _ApiUrlOpt = None,
    api_key: _ApiKeyOpt = None,
) -> None:
    """Create a new organization."""
    try:
        with _build_client(api_url, api_key) as client:
            org = client.create_org(name=name, slug=slug)
            display_created_org(org, output=output)
    except Exception as e:
        _handle_error(e)
        raise typer.Exit(1)


@register_command("org", "list")
def org_list(
    output: _OutputOpt = "table",
    api_url: _ApiUrlOpt = None,
    api_key: _ApiKeyOpt = None,
) -> None:
    """List all organizations."""
    try:
        with _build_client(api_url, api_key) as client:
            orgs = client.list_orgs()
            display_org_list(orgs, output=output)
    except Exception as e:
        _handle_error(e)
        raise typer.Exit(1)


@register_command("org", "update")
def org_update(
    id: Annotated[str, typer.Option(help="Organization ID")],
    name: Annotated[str | None, typer.Option(help="New name")] = None,
    slug: Annotated[str | None, typer.Option(help="New slug")] = None,
    output: _OutputOpt = "table",
    api_url: _ApiUrlOpt = None,
    api_key: _ApiKeyOpt = None,
) -> None:
    """Update an organization."""
    if name is None and slug is None:
        render_error("Provide at least --name or --slug to update")
        raise typer.Exit(1)
    fields: dict[str, str] = {}
    if name is not None:
        fields["name"] = name
    if slug is not None:
        fields["slug"] = slug
    try:
        with _build_client(api_url, api_key) as client:
            org = client.update_org(id, **fields)
            display_updated_org(org, output=output)
    except Exception as e:
        _handle_error(e)
        raise typer.Exit(1)


@register_command("org", "delete")
def org_delete(
    id: Annotated[str, typer.Option(help="Organization ID")],
    output: _OutputOpt = "table",
    api_url: _ApiUrlOpt = None,
    api_key: _ApiKeyOpt = None,
) -> None:
    """Delete an organization."""
    try:
        with _build_client(api_url, api_key) as client:
            client.delete_org(id)
            display_deleted_org(id, output=output)
    except Exception as e:
        _handle_error(e)
        raise typer.Exit(1)


# --- Project commands ---


@register_command("project", "create")
def project_create(
    org_id: Annotated[str, typer.Option(help="Organization ID")],
    name: Annotated[str, typer.Option(help="Project name")],
    slug: Annotated[str, typer.Option(help="URL-friendly slug")],
    output: _OutputOpt = "table",
    api_url: _ApiUrlOpt = None,
    api_key: _ApiKeyOpt = None,
) -> None:
    """Create a new project."""
    try:
        with _build_client(api_url, api_key) as client:
            project = client.create_project(org_id=org_id, name=name, slug=slug)
            display_created_project(project, output=output)
    except Exception as e:
        _handle_error(e)
        raise typer.Exit(1)


@register_command("project", "list")
def project_list(
    org_id: Annotated[str, typer.Option(help="Organization ID")],
    output: _OutputOpt = "table",
    api_url: _ApiUrlOpt = None,
    api_key: _ApiKeyOpt = None,
) -> None:
    """List projects for an organization."""
    try:
        with _build_client(api_url, api_key) as client:
            projects = client.list_projects(org_id)
            display_project_list(projects, output=output)
    except Exception as e:
        _handle_error(e)
        raise typer.Exit(1)


@register_command("project", "update")
def project_update(
    id: Annotated[str, typer.Option(help="Project ID")],
    name: Annotated[str | None, typer.Option(help="New name")] = None,
    slug: Annotated[str | None, typer.Option(help="New slug")] = None,
    output: _OutputOpt = "table",
    api_url: _ApiUrlOpt = None,
    api_key: _ApiKeyOpt = None,
) -> None:
    """Update a project."""
    if name is None and slug is None:
        render_error("Provide at least --name or --slug to update")
        raise typer.Exit(1)
    fields: dict[str, str] = {}
    if name is not None:
        fields["name"] = name
    if slug is not None:
        fields["slug"] = slug
    try:
        with _build_client(api_url, api_key) as client:
            project = client.update_project(id, **fields)
            display_updated_project(project, output=output)
    except Exception as e:
        _handle_error(e)
        raise typer.Exit(1)


@register_command("project", "delete")
def project_delete(
    id: Annotated[str, typer.Option(help="Project ID")],
    output: _OutputOpt = "table",
    api_url: _ApiUrlOpt = None,
    api_key: _ApiKeyOpt = None,
) -> None:
    """Delete a project."""
    try:
        with _build_client(api_url, api_key) as client:
            client.delete_project(id)
            display_deleted_project(id, output=output)
    except Exception as e:
        _handle_error(e)
        raise typer.Exit(1)


# --- Agent Group commands ---


@register_command("agent-group", "create")
def agent_group_create(
    org_id: Annotated[str, typer.Option(help="Organization ID")],
    project_id: Annotated[str, typer.Option(help="Project ID")],
    name: Annotated[str, typer.Option(help="Agent group name")],
    slug: Annotated[str, typer.Option(help="URL-friendly slug")],
    environment: Annotated[str, typer.Option(help="Environment (dev, staging, prod)")] = "dev",
    provider: Annotated[str, typer.Option(help="Provider (aks, eks, gke, on-prem)")] = "on-prem",
    output: _OutputOpt = "table",
    api_url: _ApiUrlOpt = None,
    api_key: _ApiKeyOpt = None,
) -> None:
    """Create a new agent group."""
    try:
        with _build_client(api_url, api_key) as client:
            ag = client.create_agent_group(
                org_id=org_id, project_id=project_id, name=name, slug=slug,
                environment=environment, provider=provider,
            )
            display_created_agent_group(ag, output=output)
    except Exception as e:
        _handle_error(e)
        raise typer.Exit(1)


@register_command("agent-group", "list")
def agent_group_list(
    org_id: Annotated[str, typer.Option(help="Organization ID")],
    output: _OutputOpt = "table",
    api_url: _ApiUrlOpt = None,
    api_key: _ApiKeyOpt = None,
) -> None:
    """List agent groups for an organization."""
    try:
        with _build_client(api_url, api_key) as client:
            groups = client.list_agent_groups(org_id)
            display_agent_group_list(groups, output=output)
    except Exception as e:
        _handle_error(e)
        raise typer.Exit(1)


@register_command("agent-group", "update")
def agent_group_update(
    id: Annotated[str, typer.Option(help="Agent group ID")],
    name: Annotated[str | None, typer.Option(help="New name")] = None,
    slug: Annotated[str | None, typer.Option(help="New slug")] = None,
    environment: Annotated[str | None, typer.Option(help="New environment")] = None,
    provider: Annotated[str | None, typer.Option(help="New provider")] = None,
    output: _OutputOpt = "table",
    api_url: _ApiUrlOpt = None,
    api_key: _ApiKeyOpt = None,
) -> None:
    """Update an agent group."""
    fields: dict[str, str] = {}
    if name is not None:
        fields["name"] = name
    if slug is not None:
        fields["slug"] = slug
    if environment is not None:
        fields["environment"] = environment
    if provider is not None:
        fields["provider"] = provider
    if not fields:
        render_error("Provide at least one field to update (--name, --slug, --environment, --provider)")
        raise typer.Exit(1)
    try:
        with _build_client(api_url, api_key) as client:
            ag = client.update_agent_group(id, **fields)
            display_updated_agent_group(ag, output=output)
    except Exception as e:
        _handle_error(e)
        raise typer.Exit(1)


@register_command("agent-group", "delete")
def agent_group_delete(
    id: Annotated[str, typer.Option(help="Agent group ID")],
    output: _OutputOpt = "table",
    api_url: _ApiUrlOpt = None,
    api_key: _ApiKeyOpt = None,
) -> None:
    """Delete an agent group."""
    try:
        with _build_client(api_url, api_key) as client:
            client.delete_agent_group(id)
            display_deleted_agent_group(id, output=output)
    except Exception as e:
        _handle_error(e)
        raise typer.Exit(1)


# --- Agent commands ---


@register_command("agent", "list")
def agent_list(
    org_id: Annotated[str | None, typer.Option(help="Organization ID (lists agents across all groups)")] = None,
    agent_group_id: Annotated[str | None, typer.Option(help="Agent group ID")] = None,
    output: _OutputOpt = "table",
    api_url: _ApiUrlOpt = None,
    api_key: _ApiKeyOpt = None,
) -> None:
    """List agents. Provide --org-id or --agent-group-id."""
    if org_id is None and agent_group_id is None:
        render_error("Provide --org-id or --agent-group-id")
        raise typer.Exit(1)
    try:
        with _build_client(api_url, api_key) as client:
            if agent_group_id is not None:
                agents = client.list_agents(agent_group_id)
            else:
                groups = client.list_agent_groups(org_id)  # type: ignore[arg-type]
                agents = []
                for g in groups:
                    agents.extend(client.list_agents(g.id))
            display_agent_list(agents, output=output)
    except Exception as e:
        _handle_error(e)
        raise typer.Exit(1)


@register_command("agent", "status")
def agent_status(
    agent_group_id: Annotated[str, typer.Option(help="Agent group ID")],
    output: _OutputOpt = "table",
    api_url: _ApiUrlOpt = None,
    api_key: _ApiKeyOpt = None,
) -> None:
    """Show agent status summary for an agent group."""
    try:
        with _build_client(api_url, api_key) as client:
            agents = client.list_agents(agent_group_id)
            display_agent_status(agents, output=output)
    except Exception as e:
        _handle_error(e)
        raise typer.Exit(1)

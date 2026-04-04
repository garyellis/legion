"""Rich views for fleet management commands."""

from __future__ import annotations

import json
from collections import Counter
from typing import TypeVar, overload

from pydantic import BaseModel
from rich.table import Table

from legion.cli.views.base import console
from legion.core.fleet_api.models import AgentGroupResponse, AgentResponse, OrgResponse, ProjectResponse

ModelT = TypeVar("ModelT", bound=BaseModel)


# --- JSON output helper ---

@overload
def _print_json(obj: BaseModel) -> None:
    ...


@overload
def _print_json(obj: list[ModelT]) -> None:
    ...


def _print_json(obj: object) -> None:
    """Serialize one or more Pydantic models to JSON and print to stdout."""
    if isinstance(obj, list):
        print(json.dumps([item.model_dump(mode="json") for item in obj], indent=2))
    else:
        assert isinstance(obj, BaseModel)
        print(json.dumps(obj.model_dump(mode="json"), indent=2))


# --- Status color mapping ---

_STATUS_COLORS: dict[str, str] = {
    "IDLE": "green",
    "BUSY": "yellow",
    "OFFLINE": "red",
}


def _status_styled(status: str) -> str:
    color = _STATUS_COLORS.get(status, "dim")
    return f"[{color}]{status}[/{color}]"


# --- Organization views ---


def display_created_org(org: OrgResponse, output: str = "table") -> None:
    """Print a newly created organization."""
    if output == "json":
        _print_json(org)
        return
    console.print("[bold green]Organization created:[/]")
    console.print(f"  ID:      {org.id}")
    console.print(f"  Name:    {org.name}")
    console.print(f"  Slug:    {org.slug}")
    console.print(f"  Created: {org.created_at}")


def display_org_list(orgs: list[OrgResponse], output: str = "table") -> None:
    """Display organizations in a Rich table."""
    if output == "json":
        _print_json(orgs)
        return
    if not orgs:
        console.print("[dim]No organizations found.[/dim]")
        return

    table = Table(title="Organizations", header_style="bold magenta", expand=True)
    table.add_column("ID", style="dim")
    table.add_column("Name", style="bold blue")
    table.add_column("Slug", style="cyan")
    table.add_column("Created", style="dim")

    for org in orgs:
        table.add_row(org.id, org.name, org.slug, str(org.created_at))

    console.print(table)


def display_updated_org(org: OrgResponse, output: str = "table") -> None:
    """Print an updated organization."""
    if output == "json":
        _print_json(org)
        return
    console.print("[bold green]Organization updated:[/]")
    console.print(f"  ID:      {org.id}")
    console.print(f"  Name:    {org.name}")
    console.print(f"  Slug:    {org.slug}")
    console.print(f"  Updated: {org.updated_at}")


def display_deleted_org(org_id: str, output: str = "table") -> None:
    """Confirm organization deletion."""
    if output == "json":
        print(json.dumps({"id": org_id, "deleted": True}))
        return
    console.print(f"[bold red]Organization deleted:[/] {org_id}")


# --- Project views ---


def display_created_project(project: ProjectResponse, output: str = "table") -> None:
    """Print a newly created project."""
    if output == "json":
        _print_json(project)
        return
    console.print("[bold green]Project created:[/]")
    console.print(f"  ID:      {project.id}")
    console.print(f"  Name:    {project.name}")
    console.print(f"  Slug:    {project.slug}")
    console.print(f"  Org ID:  {project.org_id}")
    console.print(f"  Created: {project.created_at}")


def display_project_list(projects: list[ProjectResponse], output: str = "table") -> None:
    """Display projects in a Rich table."""
    if output == "json":
        _print_json(projects)
        return
    if not projects:
        console.print("[dim]No projects found.[/dim]")
        return

    table = Table(title="Projects", header_style="bold magenta", expand=True)
    table.add_column("ID", style="dim")
    table.add_column("Name", style="bold blue")
    table.add_column("Slug", style="cyan")
    table.add_column("Org ID", style="dim")
    table.add_column("Created", style="dim")

    for p in projects:
        table.add_row(p.id, p.name, p.slug, p.org_id, str(p.created_at))

    console.print(table)


def display_updated_project(project: ProjectResponse, output: str = "table") -> None:
    """Print an updated project."""
    if output == "json":
        _print_json(project)
        return
    console.print("[bold green]Project updated:[/]")
    console.print(f"  ID:      {project.id}")
    console.print(f"  Name:    {project.name}")
    console.print(f"  Slug:    {project.slug}")
    console.print(f"  Updated: {project.updated_at}")


def display_deleted_project(project_id: str, output: str = "table") -> None:
    """Confirm project deletion."""
    if output == "json":
        print(json.dumps({"id": project_id, "deleted": True}))
        return
    console.print(f"[bold red]Project deleted:[/] {project_id}")


# --- Agent Group views ---


def display_created_agent_group(ag: AgentGroupResponse, output: str = "table") -> None:
    """Print a newly created agent group."""
    if output == "json":
        _print_json(ag)
        return
    console.print("[bold green]Agent group created:[/]")
    console.print(f"  ID:          {ag.id}")
    console.print(f"  Name:        {ag.name}")
    console.print(f"  Slug:        {ag.slug}")
    console.print(f"  Org ID:      {ag.org_id}")
    console.print(f"  Project ID:  {ag.project_id}")
    console.print(f"  Environment: {ag.environment}")
    console.print(f"  Provider:    {ag.provider}")
    console.print(f"  Mode:        {ag.execution_mode}")


def display_agent_group_list(groups: list[AgentGroupResponse], output: str = "table") -> None:
    """Display agent groups in a Rich table."""
    if output == "json":
        _print_json(groups)
        return
    if not groups:
        console.print("[dim]No agent groups found.[/dim]")
        return

    table = Table(title="Agent Groups", header_style="bold magenta", expand=True)
    table.add_column("ID", style="dim")
    table.add_column("Name", style="bold blue")
    table.add_column("Environment", style="cyan")
    table.add_column("Provider", style="yellow")
    table.add_column("Mode", style="dim")

    for ag in groups:
        table.add_row(ag.id, ag.name, ag.environment, ag.provider, ag.execution_mode)

    console.print(table)


def display_updated_agent_group(ag: AgentGroupResponse, output: str = "table") -> None:
    """Print an updated agent group."""
    if output == "json":
        _print_json(ag)
        return
    console.print("[bold green]Agent group updated:[/]")
    console.print(f"  ID:          {ag.id}")
    console.print(f"  Name:        {ag.name}")
    console.print(f"  Slug:        {ag.slug}")
    console.print(f"  Environment: {ag.environment}")
    console.print(f"  Provider:    {ag.provider}")
    console.print(f"  Mode:        {ag.execution_mode}")


def display_deleted_agent_group(ag_id: str, output: str = "table") -> None:
    """Confirm agent group deletion."""
    if output == "json":
        print(json.dumps({"id": ag_id, "deleted": True}))
        return
    console.print(f"[bold red]Agent group deleted:[/] {ag_id}")


# --- Agent views ---


def display_agent_list(agents: list[AgentResponse], output: str = "table") -> None:
    """Display agents in a Rich table with color-coded status."""
    if output == "json":
        _print_json(agents)
        return
    if not agents:
        console.print("[dim]No agents found.[/dim]")
        return

    table = Table(title="Agents", header_style="bold magenta", expand=True)
    table.add_column("ID", style="dim")
    table.add_column("Name", style="bold blue")
    table.add_column("Status", justify="center")
    table.add_column("Capabilities", style="cyan")
    table.add_column("Last Heartbeat", style="dim")

    for agent in agents:
        caps = ", ".join(agent.capabilities) or "-"
        heartbeat = str(agent.last_heartbeat) if agent.last_heartbeat else "-"
        table.add_row(agent.id, agent.name, _status_styled(agent.status), caps, heartbeat)

    console.print(table)


def display_agent_status(agents: list[AgentResponse], output: str = "table") -> None:
    """Display agent status summary counts."""
    if output == "json":
        _print_json(agents)
        return
    if not agents:
        console.print("[dim]No agents found.[/dim]")
        return

    counts: Counter[str] = Counter()
    for agent in agents:
        counts[agent.status] += 1

    total = len(agents)
    console.print(f"\n[bold]Agent Status Summary[/] ({total} total)")
    for status in ("IDLE", "BUSY", "OFFLINE"):
        count = counts.get(status, 0)
        console.print(f"  {_status_styled(status)}: {count}")
    console.print()

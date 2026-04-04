"""Rich views for fleet management commands."""

from __future__ import annotations

from collections import Counter

from rich.table import Table

from legion.cli.views.base import console
from legion.core.fleet_api.models import AgentGroupResponse, AgentResponse, OrgResponse


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


def display_created_org(org: OrgResponse) -> None:
    """Print a newly created organization."""
    console.print("[bold green]Organization created:[/]")
    console.print(f"  ID:      {org.id}")
    console.print(f"  Name:    {org.name}")
    console.print(f"  Slug:    {org.slug}")
    console.print(f"  Created: {org.created_at}")


def display_org_list(orgs: list[OrgResponse]) -> None:
    """Display organizations in a Rich table."""
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


# --- Agent Group views ---


def display_created_agent_group(ag: AgentGroupResponse) -> None:
    """Print a newly created agent group."""
    console.print("[bold green]Agent group created:[/]")
    console.print(f"  ID:          {ag.id}")
    console.print(f"  Name:        {ag.name}")
    console.print(f"  Slug:        {ag.slug}")
    console.print(f"  Org ID:      {ag.org_id}")
    console.print(f"  Environment: {ag.environment}")
    console.print(f"  Provider:    {ag.provider}")
    console.print(f"  Mode:        {ag.execution_mode}")


def display_agent_group_list(groups: list[AgentGroupResponse]) -> None:
    """Display agent groups in a Rich table."""
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


# --- Agent views ---


def display_agent_list(agents: list[AgentResponse]) -> None:
    """Display agents in a Rich table with color-coded status."""
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


def display_agent_status(agents: list[AgentResponse]) -> None:
    """Display agent status summary counts."""
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

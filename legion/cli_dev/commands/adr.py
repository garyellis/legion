from __future__ import annotations

import os
from datetime import date
from pathlib import Path
from typing import Annotated

import typer
from rich.markdown import Markdown
from rich.panel import Panel
from rich.table import Table

from legion.plumbing.registry import register_command
from legion.cli_dev.views import console, print_message, render_error
from legion.internal.adr import (
    AdrDocument,
    AdrRelationship,
    build_adr_analysis_prompt,
    detect_next_id,
    extract_adr_references,
    find_adr_file,
    find_decisionlog_dir,
    generate_template,
    parse_adr_document,
    parse_status_from_file,
    read_dependency_specs,
    resolve_relationships,
    slugify,
    title_from_filename,
)
from legion.plumbing.agents import available_agents, run_agent_capture


# ---------------------------------------------------------------------------
# Helpers (surface-layer only)
# ---------------------------------------------------------------------------


def _project_root() -> Path:
    """Return the project root (parent of the 'legion' package directory)."""
    return Path(__file__).resolve().parent.parent.parent.parent


# ---------------------------------------------------------------------------
# Commands
# ---------------------------------------------------------------------------


@register_command("adr", "create")
def adr_create(
    title: Annotated[str, typer.Argument(help="Title for the new ADR")],
    author: Annotated[str, typer.Option("--author", "-a", help="Author name")] = "developer",
    status: Annotated[str, typer.Option("--status", "-s", help="Initial status")] = "PROPOSED",
    dependency: Annotated[bool, typer.Option("--dependency", "-d", help="Include dependency details table")] = False,
) -> None:
    """Create a new ADR with the next available ID."""
    valid_statuses = {"PROPOSED", "ACCEPTED", "DEPRECATED", "SUPERSEDED"}
    status = status.upper()
    if status not in valid_statuses:
        render_error(
            f"Invalid status: {status}",
            hint=f"Valid choices: {', '.join(sorted(valid_statuses))}",
        )
        raise typer.Exit(code=1)

    try:
        decisionlog_dir = find_decisionlog_dir(_project_root())
    except FileNotFoundError as exc:
        render_error(str(exc))
        raise typer.Exit(code=1) from exc

    next_id = detect_next_id(decisionlog_dir)
    slug = slugify(title)
    filename = f"{next_id:04d}-{slug}.md"
    filepath = decisionlog_dir / filename

    content = generate_template(
        adr_id=next_id,
        title=title,
        status=status,
        author=author,
        adr_date=date.today().isoformat(),
        include_dependency=dependency,
    )

    filepath.write_text(content, encoding="utf-8")
    print_message(f"Created {filepath}", style="green")

    editor = os.environ.get("EDITOR")
    if editor:
        print_message(f"Open with: {editor} {filepath}", style="dim")


@register_command("adr", "list")
def adr_list() -> None:
    """List all existing ADRs."""
    try:
        decisionlog_dir = find_decisionlog_dir(_project_root())
    except FileNotFoundError as exc:
        render_error(str(exc))
        raise typer.Exit(code=1) from exc

    files = sorted(decisionlog_dir.glob("[0-9][0-9][0-9][0-9]-*.md"))
    # Exclude the template
    files = [f for f in files if not f.name.startswith("0000-template")]

    if not files:
        print_message("No ADRs found.", style="yellow")
        return

    table = Table(title="Decision Records")
    table.add_column("ID", style="cyan", no_wrap=True)
    table.add_column("Title", style="white")
    table.add_column("Status", style="bold")

    for filepath in files:
        adr_id = filepath.name[:4]
        title = title_from_filename(filepath.name)
        status = parse_status_from_file(filepath)
        table.add_row(adr_id, title, status)

    console.print(table)


@register_command("adr", "next-id")
def adr_next_id() -> None:
    """Show the next available ADR ID."""
    try:
        decisionlog_dir = find_decisionlog_dir(_project_root())
    except FileNotFoundError as exc:
        render_error(str(exc))
        raise typer.Exit(code=1) from exc

    next_id = detect_next_id(decisionlog_dir)
    print_message(f"{next_id:04d}")


_STATUS_COLORS = {
    "PROPOSED": "yellow",
    "ACCEPTED": "green",
    "DEPRECATED": "red",
    "SUPERSEDED": "dim",
}


def _render_metadata_panel(doc: AdrDocument) -> None:
    """Render the ADR metadata header as a Rich panel."""
    status_color = _STATUS_COLORS.get(doc.status, "white")
    meta_lines = [
        f"[bold]{doc.title}[/]",
        "",
        f"[cyan]ID:[/]     ADR-{doc.adr_id:04d}",
        f"[cyan]Status:[/] [{status_color}]{doc.status}[/{status_color}]",
        f"[cyan]Date:[/]   {doc.date}",
        f"[cyan]Author:[/] {doc.author}",
        f"[cyan]File:[/]   {doc.filepath.name}",
    ]
    console.print(Panel("\n".join(meta_lines), border_style="cyan"))


def _render_relationships(relationships: list[AdrRelationship]) -> None:
    """Render related ADRs as a compact list."""
    if not relationships:
        return
    console.print("[bold]Related ADRs[/]")
    for rel in relationships:
        color = _STATUS_COLORS.get(rel.status, "white")
        console.print(
            f"  [cyan]ADR-{rel.adr_id:04d}[/] {rel.title} [{color}]{rel.status}[/{color}]"
        )
    console.print()


def _resolve_doc_and_exit(adr_id: int) -> tuple[AdrDocument, Path]:
    """Locate and parse an ADR, or exit with an error. Returns (doc, decisionlog_dir)."""
    try:
        decisionlog_dir = find_decisionlog_dir(_project_root())
    except FileNotFoundError as exc:
        render_error(str(exc))
        raise typer.Exit(code=1) from exc

    filepath = find_adr_file(decisionlog_dir, adr_id)
    if filepath is None:
        render_error(
            f"ADR-{adr_id:04d} not found.",
            hint="Use 'legion-dev adr list' to see available ADRs.",
        )
        raise typer.Exit(code=1)

    return parse_adr_document(filepath), decisionlog_dir


_AGENT_HELP = f"AI agent to use ({', '.join(available_agents())})"


def _run_agent(prompt: str, agent: str) -> None:
    """Shell out to an AI agent CLI, capture output, and render as Rich Markdown."""
    try:
        with console.status(f"[bold cyan]Waiting for {agent} response…"):
            returncode, output = run_agent_capture(agent, prompt)
    except (ValueError, FileNotFoundError) as exc:
        render_error(str(exc))
        raise typer.Exit(code=1) from exc
    if returncode != 0:
        if output.strip():
            console.print(Markdown(output))
        raise typer.Exit(code=returncode)
    if output.strip():
        console.print(Markdown(output))


@register_command("adr", "show")
def adr_show(
    adr_id: Annotated[int, typer.Argument(help="ADR number to display (e.g. 1, 9)")],
) -> None:
    """Display the content of a specific ADR."""
    doc, _dir = _resolve_doc_and_exit(adr_id)
    _render_metadata_panel(doc)

    for section_name, content in doc.sections.items():
        if not content:
            continue
        section_md = f"## {section_name}\n\n{content}"
        console.print(Markdown(section_md))
        console.print()


@register_command("adr", "overview")
def adr_overview(
    adr_id: Annotated[int, typer.Argument(help="ADR number to display (e.g. 1, 9)")],
    agent: Annotated[str, typer.Option("--agent", help=_AGENT_HELP)] = "claude",
) -> None:
    """Analyze an ADR against the codebase using an AI agent."""
    doc, decisionlog_dir = _resolve_doc_and_exit(adr_id)

    # Metadata
    _render_metadata_panel(doc)

    # Relationships
    adr_text = doc.filepath.read_text(encoding="utf-8")
    refs = extract_adr_references(adr_text, doc.adr_id)
    relationships = resolve_relationships(refs, decisionlog_dir)
    _render_relationships(relationships)

    # Analysis via AI agent
    dep_specs = read_dependency_specs(_project_root())
    prompt = build_adr_analysis_prompt(doc, relationships, dep_specs)
    _run_agent(prompt, agent)

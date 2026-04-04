from __future__ import annotations

from datetime import date
from pathlib import Path
from typing import Annotated

import typer

from legion.plumbing.registry import register_command
from legion.cli_dev.views import console, print_message, render_error
from legion.internal.feature import (
    build_feature_handoff_prompt,
    find_feature_file,
    parse_feature_document,
    feature_filepath,
    generate_feature_template,
)


def _project_root() -> Path:
    """Return the project root (parent of the 'legion' package directory)."""
    return Path(__file__).resolve().parent.parent.parent.parent


@register_command("feature", "create")
def feature_create(
    title: Annotated[str, typer.Argument(help="Title for the new feature brief")],
    dry_run: Annotated[
        bool, typer.Option("--dry-run", help="Show what would be created without writing files")
    ] = False,
) -> None:
    """Create a structured feature brief in docs/features/."""
    root = _project_root()
    path = feature_filepath(root, title)

    if dry_run:
        print_message("[bold]Dry run — file that would be created:[/bold]")
        print_message(f"  {path.relative_to(root)}")
        return

    if path.exists():
        render_error(
            f"Refusing to overwrite existing file: {path.relative_to(root)}",
            hint="Remove it first or choose a different title.",
        )
        raise typer.Exit(code=1)

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        generate_feature_template(title=title, created_date=date.today().isoformat()),
        encoding="utf-8",
    )
    print_message(f"[bold]Created feature brief:[/bold] [green]{path.relative_to(root)}[/green]")
    print_message(
        "Use `legion-dev feature show` to inspect it or `legion-dev feature handoff` to generate a session handoff.",
        style="dim",
    )


def _resolve_feature_file_or_exit(title: str) -> tuple[Path, Path]:
    """Return the feature file and project root, or exit with a clean error."""
    root = _project_root()
    path = find_feature_file(root, title)
    if path is None:
        render_error(
            f"Feature brief not found: {feature_filepath(root, title).relative_to(root)}",
            hint="Create it first with 'legion-dev feature create <title>'.",
        )
        raise typer.Exit(code=1)
    return root, path


@register_command("feature", "show")
def feature_show(
    title: Annotated[str, typer.Argument(help="Title of the feature brief to display")],
) -> None:
    """Render a feature brief locally."""
    _root, path = _resolve_feature_file_or_exit(title)
    doc = parse_feature_document(path)

    print_message(doc.title, style="bold")
    print_message(f"Status: {doc.status or 'UNKNOWN'}", style="cyan")
    print_message(f"Date:   {doc.date or 'UNKNOWN'}", style="cyan")
    print_message(f"File:   {path.relative_to(_root)}", style="cyan")
    console.print(doc.content, markup=False)


@register_command("feature", "handoff")
def feature_handoff(
    title: Annotated[str, typer.Argument(help="Title of the feature brief to hand off")],
) -> None:
    """Print a deterministic handoff prompt for a new session or sub-agent."""
    _root, path = _resolve_feature_file_or_exit(title)
    doc = parse_feature_document(path)
    console.print(build_feature_handoff_prompt(doc), markup=False)

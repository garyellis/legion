from __future__ import annotations

from datetime import date
from pathlib import Path
from typing import Annotated

import typer

from legion.plumbing.registry import register_command
from legion.cli_dev.views import print_message, render_error
from legion.internal.feature import (
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

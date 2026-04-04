from __future__ import annotations

from pathlib import Path
from typing import Annotated

import typer

from legion.plumbing.registry import register_command
from legion.cli_dev.views import print_message, render_error
from legion.internal.scaffold import (
    CORE_TEMPLATES,
    DOMAIN_TEMPLATE,
    REPOSITORY_TEMPLATE,
    SERVICE_TEMPLATE,
    TEST_STUB,
    VALID_SURFACES,
    check_existing,
    command_paths,
    command_template,
    core_paths,
    domain_paths,
    service_paths,
    write_file,
)


# ---------------------------------------------------------------------------
# Helpers (surface-layer only)
# ---------------------------------------------------------------------------


def _project_root() -> Path:
    """Return the project root (parent of the 'legion' package directory)."""
    return Path(__file__).resolve().parent.parent.parent.parent


def _print_created(paths: list[Path], root: Path) -> None:
    for p in paths:
        try:
            rel = p.relative_to(root)
        except ValueError:
            rel = p
        print_message(f"  [green]\u2714[/green] {rel}")


def _print_dry_run(paths: list[Path], root: Path) -> None:
    print_message("[bold]Dry run — files that would be created:[/bold]")
    for p in paths:
        try:
            rel = p.relative_to(root)
        except ValueError:
            rel = p
        print_message(f"  {rel}")


# ---------------------------------------------------------------------------
# Commands
# ---------------------------------------------------------------------------


@register_command("scaffold", "core")
def scaffold_core(
    name: Annotated[str, typer.Argument(help="Name of the new core module")],
    dry_run: Annotated[
        bool, typer.Option("--dry-run", help="Show what would be created without writing files")
    ] = False,
) -> None:
    """Scaffold a new core module with client, models, and test stub."""
    root = _project_root()
    paths = core_paths(name, root)

    if dry_run:
        _print_dry_run(paths, root)
        return

    existing = check_existing(paths)
    if existing:
        render_error(
            f"Refusing to overwrite existing files: {', '.join(str(e.relative_to(root)) for e in existing)}",
            hint="Remove them first or choose a different name.",
        )
        raise typer.Exit(code=1)

    contents = [
        CORE_TEMPLATES["__init__.py"],
        CORE_TEMPLATES["client.py"],
        CORE_TEMPLATES["models.py"],
        TEST_STUB,
    ]
    for path, content in zip(paths, contents):
        write_file(path, content)

    print_message(f"[bold]Scaffolded core module '[green]{name}[/green]':[/bold]")
    _print_created(paths, root)


@register_command("scaffold", "service")
def scaffold_service(
    name: Annotated[str, typer.Argument(help="Name of the new service")],
    dry_run: Annotated[
        bool, typer.Option("--dry-run", help="Show what would be created without writing files")
    ] = False,
) -> None:
    """Scaffold a new service with repository interface and test stub."""
    root = _project_root()
    paths = service_paths(name, root)

    if dry_run:
        _print_dry_run(paths, root)
        return

    existing = check_existing(paths)
    if existing:
        render_error(
            f"Refusing to overwrite existing files: {', '.join(str(e.relative_to(root)) for e in existing)}",
            hint="Remove them first or choose a different name.",
        )
        raise typer.Exit(code=1)

    contents = [SERVICE_TEMPLATE, REPOSITORY_TEMPLATE, TEST_STUB]
    for path, content in zip(paths, contents):
        write_file(path, content)

    print_message(f"[bold]Scaffolded service '[green]{name}[/green]':[/bold]")
    _print_created(paths, root)


@register_command("scaffold", "domain")
def scaffold_domain(
    name: Annotated[str, typer.Argument(help="Name of the new domain entity")],
    dry_run: Annotated[
        bool, typer.Option("--dry-run", help="Show what would be created without writing files")
    ] = False,
) -> None:
    """Scaffold a new domain entity with Pydantic model and test stub."""
    root = _project_root()
    paths = domain_paths(name, root)

    if dry_run:
        _print_dry_run(paths, root)
        return

    existing = check_existing(paths)
    if existing:
        render_error(
            f"Refusing to overwrite existing files: {', '.join(str(e.relative_to(root)) for e in existing)}",
            hint="Remove them first or choose a different name.",
        )
        raise typer.Exit(code=1)

    contents = [DOMAIN_TEMPLATE, TEST_STUB]
    for path, content in zip(paths, contents):
        write_file(path, content)

    print_message(f"[bold]Scaffolded domain entity '[green]{name}[/green]':[/bold]")
    _print_created(paths, root)


@register_command("scaffold", "command")
def scaffold_command(
    surface: Annotated[str, typer.Argument(help="Target surface (cli or cli_dev)")],
    group: Annotated[str, typer.Argument(help="Command group name")],
    name: Annotated[str, typer.Argument(help="Command name")],
    dry_run: Annotated[
        bool, typer.Option("--dry-run", help="Show what would be created without writing files")
    ] = False,
) -> None:
    """Scaffold a new CLI command in a surface."""
    if surface not in VALID_SURFACES:
        render_error(
            f"Invalid surface '{surface}'. Must be one of: {', '.join(VALID_SURFACES)}"
        )
        raise typer.Exit(code=1)

    root = _project_root()
    paths = command_paths(surface, group, name, root)

    if dry_run:
        _print_dry_run(paths, root)
        return

    existing = check_existing(paths)
    if existing:
        render_error(
            f"Refusing to overwrite existing files: {', '.join(str(e.relative_to(root)) for e in existing)}",
            hint="Remove them first or choose a different name.",
        )
        raise typer.Exit(code=1)

    write_file(paths[0], command_template(group, name))

    print_message(f"[bold]Scaffolded command '[green]{group} {name}[/green]':[/bold]")
    _print_created(paths, root)

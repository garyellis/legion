from __future__ import annotations

import importlib
import pkgutil

import typer

from legion.plumbing.logging import LogOutput, setup_logging
from legion.plumbing.registry import get_registry

app = typer.Typer()


def load_cli_dev_commands() -> None:
    from legion.cli_dev import commands
    for _, module_name, _ in pkgutil.iter_modules(commands.__path__):
        importlib.import_module(f"legion.cli_dev.commands.{module_name}")


def register_with_typer() -> None:
    """Build Typer command tree from the registry."""
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


def main() -> None:
    setup_logging(level="WARNING", output=LogOutput.STDERR)
    load_cli_dev_commands()
    register_with_typer()
    app()


if __name__ == "__main__":
    main()

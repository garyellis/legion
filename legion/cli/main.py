import importlib
import pkgutil

import typer

from legion.cli.registry import get_registry
from legion.plumbing.logging import LogOutput, setup_logging

app = typer.Typer()

def load_cli_commands() -> None:
    from legion.cli import commands
    for _, module_name, _ in pkgutil.iter_modules(commands.__path__):
        importlib.import_module(f"legion.cli.commands.{module_name}")

def register_with_typer() -> None:
    """Build Typer command tree from the registry.

    Groups support dotted names for nesting: ``register_command("a.b", "c")``
    produces ``legion-cli a b c``.
    """
    group_apps: dict[str, typer.Typer] = {}

    for group, name, func in get_registry():
        parts = group.split(".")
        # Walk / create the nested group chain
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
    load_cli_commands()
    register_with_typer()
    app()

if __name__ == "__main__":
    main()

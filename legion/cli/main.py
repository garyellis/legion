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
    group_apps: dict[str, typer.Typer] = {}

    for group, name, func in get_registry():
        if group not in group_apps:
            group_apps[group] = typer.Typer()
            app.add_typer(group_apps[group], name=group)
        group_apps[group].command(name)(func)

def main() -> None:
    setup_logging(level="WARNING", output=LogOutput.STDERR)
    load_cli_commands()
    register_with_typer()
    app()

if __name__ == "__main__":
    main()

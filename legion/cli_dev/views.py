from __future__ import annotations

from typing import Optional

from rich.console import Console

console = Console()


def render_error(message: str, hint: Optional[str] = None) -> None:
    """Displays a standardized error message."""
    console.print(f"[bold red]Error:[/] {message}")
    if hint:
        console.print(f"[dim]Hint: {hint}[/]")


def print_message(message: str, style: str = "") -> None:
    """Prints a simple message with optional styling."""
    if style:
        console.print(f"[{style}]{message}[/]")
    else:
        console.print(message)

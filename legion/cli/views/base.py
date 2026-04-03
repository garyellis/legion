from typing import Optional
from rich.console import Console
from rich.progress import Progress, SpinnerColumn, TextColumn, BarColumn, TaskProgressColumn

# Centralized console instance for the entire CLI
console = Console()

def get_progress_bar(description: str, total: int) -> Progress:
    """Returns a standardized progress bar for CLI operations."""
    progress = Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        BarColumn(),
        TaskProgressColumn(),
        console=console,
    )
    progress.add_task(description, total=total)
    return progress

def render_error(message: str, hint: Optional[str] = None):
    """Displays a standardized error message."""
    console.print(f"[bold red]Error:[/] {message}")
    if hint:
        console.print(f"[dim]Hint: {hint}[/]")

def render_status(message: str):
    """Context manager for showing status."""
    return console.status(f"[bold green]{message}...")

def print_message(message: str, style: str = ""):
    """Prints a simple message with optional styling."""
    if style:
        console.print(f"[{style}]{message}[/]")
    else:
        console.print(message)

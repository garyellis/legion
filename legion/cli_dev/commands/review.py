from __future__ import annotations

from pathlib import Path
from typing import Annotated, Optional

import typer

from rich.markdown import Markdown

from legion.plumbing.agents import available_agents, run_agent_capture
from legion.plumbing.registry import register_command
from legion.cli_dev.views import console, print_message, render_error
from legion.plumbing.subprocess import (
    git_diff,
    git_log,
    git_root,
)
from legion.internal.review import build_review_prompt, read_claude_md

_AGENT_HELP = f"AI agent to use ({', '.join(available_agents())})"


def find_git_root() -> Path | None:
    """Return the git repository root, or None if not inside a repo."""
    return git_root()


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


def _get_git_root_or_exit() -> Path:
    """Return the git root or exit with an error."""
    root = find_git_root()
    if root is None:
        render_error("Not inside a git repository.")
        raise typer.Exit(code=1)
    return root


@register_command("review", "diff")
def review_diff(
    staged: Annotated[
        bool, typer.Option("--staged", help="Review only staged changes")
    ] = False,
    cached: Annotated[
        bool, typer.Option("--cached", help="Alias for --staged")
    ] = False,
    base: Annotated[
        Optional[str],
        typer.Option("--base", help="Diff against a branch (e.g. main)"),
    ] = None,
    agent: Annotated[str, typer.Option("--agent", help=_AGENT_HELP)] = "claude",
) -> None:
    """Review the current git diff using an AI agent."""
    repo_root = _get_git_root_or_exit()
    rules = read_claude_md(repo_root)

    diff_args: list[str] = []
    if base:
        diff_args = [f"{base}...HEAD"]
        diff_type = f"diff against {base}"
    elif staged or cached:
        diff_args = ["--cached"]
        diff_type = "staged changes"
    else:
        diff_type = "working tree changes (staged + unstaged)"

    diff = git_diff(diff_args if diff_args else None)
    if not diff.strip():
        print_message("No diff content to review.", style="yellow")
        return

    prompt = build_review_prompt(rules=rules, diff=diff, diff_type=diff_type)
    _run_agent(prompt, agent)


@register_command("review", "file")
def review_file(
    path: Annotated[str, typer.Argument(help="Path to the file to review")],
    agent: Annotated[str, typer.Option("--agent", help=_AGENT_HELP)] = "claude",
) -> None:
    """Review a specific file using an AI agent."""
    repo_root = _get_git_root_or_exit()
    rules = read_claude_md(repo_root)

    file_path = Path(path)
    if not file_path.exists():
        render_error(f"File not found: {path}")
        raise typer.Exit(code=1)

    content = file_path.read_text(encoding="utf-8")
    if not content.strip():
        print_message("File is empty, nothing to review.", style="yellow")
        return

    diff_type = f"file: {path}"
    prompt = build_review_prompt(rules=rules, diff=content, diff_type=diff_type)
    _run_agent(prompt, agent)


@register_command("review", "pr")
def review_pr(
    base: Annotated[
        str,
        typer.Option("--base", help="Base branch to compare against"),
    ] = "main",
    agent: Annotated[str, typer.Option("--agent", help=_AGENT_HELP)] = "claude",
) -> None:
    """Review all changes on the current branch vs a base branch."""
    repo_root = _get_git_root_or_exit()
    rules = read_claude_md(repo_root)

    # Gather the diff
    diff = git_diff([f"{base}...HEAD"])
    if not diff.strip():
        print_message(f"No changes between {base} and HEAD.", style="yellow")
        return

    # Gather commit messages
    commits = git_log([f"{base}...HEAD", "--pretty=format:%h %s"]).strip()

    # Build combined content
    combined = f"Commits on this branch:\n{commits}\n\n---\n\nDiff:\n{diff}"
    diff_type = f"pull request (branch changes vs {base})"
    prompt = build_review_prompt(rules=rules, diff=combined, diff_type=diff_type)
    _run_agent(prompt, agent)

"""Thin subprocess helpers for shelling out to external tools.

This lives in plumbing/ so that surface layers (cli, api, etc.) can invoke
external processes without importing subprocess directly — which is restricted
to plumbing/, internal/, and core/ by architectural rules.
"""

from __future__ import annotations

import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True, slots=True)
class RunResult:
    """Minimal result object for subprocess calls."""

    returncode: int
    stdout: str
    stderr: str


def run_capture(args: list[str]) -> RunResult:
    """Run a command, capture stdout and stderr, and return a ``RunResult``."""
    result = subprocess.run(args, capture_output=True, text=True)
    return RunResult(
        returncode=result.returncode,
        stdout=result.stdout,
        stderr=result.stderr,
    )


def run_passthrough(args: list[str]) -> int:
    """Run a command with stdout/stderr connected to the terminal.

    Returns the process exit code.
    """
    result = subprocess.run(args)
    return result.returncode


def run_capture_text(args: list[str]) -> RunResult:
    """Run a command, capture stdout/stderr, and detach stdin.

    Stdin is connected to ``/dev/null`` so the child process cannot block
    waiting for interactive input (e.g. permission prompts, workspace
    trust dialogs).
    """
    result = subprocess.run(
        args, capture_output=True, text=True, stdin=subprocess.DEVNULL,
    )
    return RunResult(
        returncode=result.returncode,
        stdout=result.stdout,
        stderr=result.stderr,
    )


def find_on_path(name: str) -> str | None:
    """Return the full path to *name* if it exists on ``$PATH``, else ``None``."""
    return shutil.which(name)


def git_root() -> Path | None:
    """Return the git repository root, or ``None`` if not in a repo."""
    result = run_capture(["git", "rev-parse", "--show-toplevel"])
    if result.returncode != 0:
        return None
    return Path(result.stdout.strip())


def git_diff(args: list[str] | None = None) -> str:
    """Run ``git diff`` with optional extra arguments and return stdout."""
    cmd = ["git", "diff"]
    if args:
        cmd.extend(args)
    return run_capture(cmd).stdout


def git_log(args: list[str] | None = None) -> str:
    """Run ``git log`` with optional extra arguments and return stdout."""
    cmd = ["git", "log"]
    if args:
        cmd.extend(args)
    return run_capture(cmd).stdout

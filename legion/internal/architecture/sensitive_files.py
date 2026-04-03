"""Sensitive file detection to prevent committing secrets.

Checks staged git files (or a directory tree) against patterns that
commonly indicate credentials, private keys, or environment files.
"""

from __future__ import annotations

import subprocess
from fnmatch import fnmatch
from pathlib import Path
from typing import NamedTuple

from legion.internal.architecture.dependency_check import PACKAGE_ROOT

PROJECT_ROOT = PACKAGE_ROOT.parent

# Filename patterns that indicate sensitive content.
SENSITIVE_PATTERNS: list[str] = [
    # Private keys and certificates
    "*.pem",
    "*.key",
    "*.p12",
    "*.pfx",
    "*.jks",
    "id_rsa",
    "id_ed25519",
    "id_ecdsa",
    # Environment and credentials files
    ".env",
    ".env.*",
    "env.sh",
    "credentials.json",
    "service-account*.json",
    # Generic secret patterns
    "*_secret*",
    "*.secret",
]

# Files that match patterns above but are safe (templates, examples).
SAFE_EXCEPTIONS: set[str] = {
    ".env.example",
    "env.example",
    ".env.template",
    "env.template",
}


class SensitiveFileViolation(NamedTuple):
    file: str
    pattern_matched: str
    reason: str


def _matches_sensitive_pattern(filename: str) -> str | None:
    """Return the matched pattern if filename is sensitive, else None."""
    basename = Path(filename).name

    # Check safe exceptions first
    if basename in SAFE_EXCEPTIONS:
        return None

    for pattern in SENSITIVE_PATTERNS:
        if fnmatch(basename, pattern):
            return pattern

    return None


def check_staged_files() -> list[SensitiveFileViolation]:
    """Check git-staged files for sensitive filename patterns.

    Uses ``git diff --cached`` to inspect only files being committed.
    Returns violations for any staged file matching a sensitive pattern.
    """
    result = subprocess.run(
        ["git", "diff", "--cached", "--name-only", "--diff-filter=ACR"],
        capture_output=True,
        text=True,
        cwd=str(PROJECT_ROOT),
    )

    if result.returncode != 0:
        return []  # not in a git repo or no staged files

    violations: list[SensitiveFileViolation] = []
    for line in result.stdout.splitlines():
        filename = line.strip()
        if not filename:
            continue
        pattern = _matches_sensitive_pattern(filename)
        if pattern:
            violations.append(SensitiveFileViolation(
                file=filename,
                pattern_matched=pattern,
                reason=f"matches sensitive pattern '{pattern}'",
            ))

    return violations


def check_directory(path: Path | None = None) -> list[SensitiveFileViolation]:
    """Walk a directory tree and flag files matching sensitive patterns.

    Useful outside git context (e.g., scanning a build artifact directory).
    """
    root = path or PROJECT_ROOT
    violations: list[SensitiveFileViolation] = []

    for filepath in root.rglob("*"):
        if not filepath.is_file():
            continue
        # Skip .git directory
        if ".git" in filepath.parts:
            continue
        # Skip virtual environments
        if ".venv" in filepath.parts:
            continue

        rel_path = str(filepath.relative_to(root))
        pattern = _matches_sensitive_pattern(rel_path)
        if pattern:
            violations.append(SensitiveFileViolation(
                file=rel_path,
                pattern_matched=pattern,
                reason=f"matches sensitive pattern '{pattern}'",
            ))

    return violations


def format_sensitive_violations(
    violations: list[SensitiveFileViolation],
) -> str:
    """Format sensitive file violations into a human-readable report."""
    lines = ["\nSensitive files detected:\n"]
    for v in sorted(violations):
        lines.append(f"  {v.file}  — {v.reason}")
    lines.append(
        "\nRule: files matching credential/key patterns must not be committed. "
        "Add to .gitignore or rename (e.g., .env.example)."
    )
    return "\n".join(lines)

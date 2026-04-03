"""Banned external imports by architectural layer.

Enforces that certain third-party packages are not imported in layers
where they don't belong (e.g., no Rich in core/, no LangChain in domain/).
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path
from typing import NamedTuple

from legion.internal.architecture.dependency_check import (
    PACKAGE_ROOT,
    SURFACES,
    classify_layer,
)

# External packages banned from each layer.
# Rationale lives in CLAUDE.md — this is the enforcement mechanism.
LAYER_BANNED_IMPORTS: dict[str, set[str]] = {
    "plumbing": set(),
    "internal": set(),
    "core": {
        "rich", "langchain", "langchain_core", "langchain_openai",
        "slack_bolt", "fastapi", "typer", "uvicorn",
    },
    "domain": {
        "rich", "langchain", "langchain_core", "langchain_openai",
        "slack_bolt", "slack_sdk", "fastapi", "typer", "uvicorn",
        "sqlalchemy", "httpx", "aiohttp",
    },
    "services": {
        "rich", "langchain", "langchain_core", "langchain_openai",
        "slack_bolt", "slack_sdk", "fastapi", "typer", "uvicorn",
    },
    "agents": {
        "rich", "fastapi", "typer", "uvicorn", "slack_bolt", "slack_sdk",
    },
}

# Python standard library module names (3.10+).
_STDLIB_MODULES = sys.stdlib_module_names


class BannedImportViolation(NamedTuple):
    file: str
    line: int
    layer: str
    banned_package: str
    import_statement: str


def _extract_external_top_packages(filepath: Path) -> list[tuple[int, str, str]]:
    """Extract external (non-legion, non-stdlib) top-level package names.

    Returns list of (line, top_package, full_import_statement) tuples.
    """
    source = filepath.read_text(encoding="utf-8")
    try:
        tree = ast.parse(source, filename=str(filepath))
    except SyntaxError:
        return []

    results: list[tuple[int, str, str]] = []

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                top = alias.name.split(".")[0]
                if top not in _STDLIB_MODULES and top != "legion":
                    results.append((node.lineno, top, f"import {alias.name}"))

        elif isinstance(node, ast.ImportFrom):
            if node.level and node.level > 0:
                continue  # relative imports are intra-package
            if node.module:
                top = node.module.split(".")[0]
                if top not in _STDLIB_MODULES and top != "legion":
                    names = ", ".join(a.name for a in node.names)
                    results.append(
                        (node.lineno, top, f"from {node.module} import {names}")
                    )

    return results


def find_banned_import_violations() -> list[BannedImportViolation]:
    """Scan all .py files and return banned import violations."""
    violations: list[BannedImportViolation] = []

    for filepath in PACKAGE_ROOT.rglob("*.py"):
        layer = classify_layer(filepath)
        if layer is None:
            continue

        # Surfaces don't have layer-level bans (they're the boundary)
        if layer in SURFACES:
            continue

        banned = LAYER_BANNED_IMPORTS.get(layer, set())
        if not banned:
            continue

        for lineno, top_pkg, stmt in _extract_external_top_packages(filepath):
            if top_pkg in banned:
                violations.append(
                    BannedImportViolation(
                        file=str(filepath.relative_to(PACKAGE_ROOT.parent)),
                        line=lineno,
                        layer=layer,
                        banned_package=top_pkg,
                        import_statement=stmt,
                    )
                )

    return violations


def format_banned_violations(violations: list[BannedImportViolation]) -> str:
    """Format banned import violations into a human-readable report."""
    lines = ["\nBanned import violations found:\n"]
    for v in sorted(violations):
        lines.append(
            f"  {v.file}:{v.line}  "
            f"[{v.layer}] imports banned package '{v.banned_package}' "
            f"via '{v.import_statement}'"
        )
    lines.append(
        "\nRule: certain external packages are banned from specific layers. "
        "See LAYER_BANNED_IMPORTS in "
        "legion/internal/architecture/banned_imports.py"
    )
    return "\n".join(lines)

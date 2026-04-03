"""Unused dependency detection.

Compares declared dependencies in pyproject.toml against actual imports
found in the codebase. Uses tomllib (stdlib 3.11+) and AST analysis.
"""

from __future__ import annotations

import ast
import re
import tomllib
from pathlib import Path
from typing import NamedTuple

from legion.internal.architecture.dependency_check import PACKAGE_ROOT

PROJECT_ROOT = PACKAGE_ROOT.parent


# PyPI package names that differ from their Python import names.
PACKAGE_IMPORT_MAP: dict[str, str] = {
    "python-openstackclient": "openstackclient",
    "openstacksdk": "openstack",
    "pydantic-settings": "pydantic_settings",
    "dnspython": "dns",
    "slack-bolt": "slack_bolt",
    "slack-sdk": "slack_sdk",
    "langchain-openai": "langchain_openai",
    "langchain-core": "langchain_core",
    "asciichartpy": "asciichartpy",
    "ipython": "IPython",
}

# Dependencies that are legitimately needed but never directly imported.
# Key = normalized package name, value = reason for allowlisting.
RUNTIME_ALLOWLIST: dict[str, str] = {
    # Database drivers loaded by SQLAlchemy via connection string
    "psycopg": "PostgreSQL driver loaded by SQLAlchemy at runtime",
    # CLI tools providing shell commands, not Python libraries
    "python-openstackclient": "CLI tool (openstack command), not a Python library",
    # Runtime deps of other packages
    "aiohttp": "async HTTP runtime required by slack-bolt",
    # Interactive shells invoked as entry points
    "ipython": "interactive shell, invoked via entry point",
    "ptpython": "interactive shell, invoked via entry point",
}

# Dev dependencies that are CLI tools (invoked via `python -m`), not libraries.
# These are never imported in application code by design.
DEV_CLI_TOOLS: set[str] = {
    "bandit",
    "mypy",
    "pip-audit",
    "vulture",
    "httpx",  # used by FastAPI TestClient and scripts/
}

# Strip version specifiers from dependency strings.
_VERSION_RE = re.compile(r"[><=!~\[;].*$")


class UnusedDependency(NamedTuple):
    package_name: str       # as declared in pyproject.toml
    import_name: str        # the Python import name
    dependency_group: str   # "main", "agents", "postgres", "dev"


class SkippedDependency(NamedTuple):
    package_name: str
    reason: str
    dependency_group: str


class UnusedDepsResult(NamedTuple):
    unused: list[UnusedDependency]
    skipped: list[SkippedDependency]
    scanned_files: int


def _normalize_package_name(name: str) -> str:
    """Strip version specifiers and extras from a dependency string."""
    return _VERSION_RE.sub("", name).strip()


def _package_to_import_name(package_name: str) -> str:
    """Convert a PyPI package name to its Python import name."""
    normalized = _normalize_package_name(package_name)
    if normalized in PACKAGE_IMPORT_MAP:
        return PACKAGE_IMPORT_MAP[normalized]
    # Default: replace hyphens with underscores, strip extras
    base = normalized.split("[")[0]
    return base.replace("-", "_")


def parse_dependencies(
    pyproject_path: Path | None = None,
) -> dict[str, list[tuple[str, str]]]:
    """Parse pyproject.toml and return {group: [(package_name, import_name)]}.

    Groups: "main", optional dependency group names, dev dependency group names.
    """
    path = pyproject_path or (PROJECT_ROOT / "pyproject.toml")
    with open(path, "rb") as f:
        data = tomllib.load(f)

    result: dict[str, list[tuple[str, str]]] = {}

    # [project.dependencies]
    main_deps = data.get("project", {}).get("dependencies", [])
    result["main"] = [
        (_normalize_package_name(d), _package_to_import_name(d))
        for d in main_deps
    ]

    # [project.optional-dependencies]
    optional = data.get("project", {}).get("optional-dependencies", {})
    for group_name, deps in optional.items():
        result[group_name] = [
            (_normalize_package_name(d), _package_to_import_name(d))
            for d in deps
        ]

    # [dependency-groups]
    dep_groups = data.get("dependency-groups", {})
    for group_name, deps in dep_groups.items():
        result[group_name] = [
            (_normalize_package_name(d), _package_to_import_name(d))
            for d in deps
            if isinstance(d, str)  # skip include-group entries
        ]

    return result


def collect_all_imports(root: Path | None = None) -> set[str]:
    """Walk all .py files and collect top-level external import package names."""
    package_root = root or PACKAGE_ROOT
    imports: set[str] = set()

    for filepath in package_root.rglob("*.py"):
        source = filepath.read_text(encoding="utf-8")
        try:
            tree = ast.parse(source, filename=str(filepath))
        except SyntaxError:
            continue

        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    top = alias.name.split(".")[0]
                    if top != "legion":
                        imports.add(top)
            elif isinstance(node, ast.ImportFrom):
                if node.level and node.level > 0:
                    continue  # relative import
                if node.module:
                    top = node.module.split(".")[0]
                    if top != "legion":
                        imports.add(top)

    # Also scan test files
    test_dir = package_root.parent / "tests"
    if test_dir.is_dir():
        for filepath in test_dir.rglob("*.py"):
            source = filepath.read_text(encoding="utf-8")
            try:
                tree = ast.parse(source, filename=str(filepath))
            except SyntaxError:
                continue

            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    for alias in node.names:
                        top = alias.name.split(".")[0]
                        if top != "legion":
                            imports.add(top)
                elif isinstance(node, ast.ImportFrom):
                    if node.level and node.level > 0:
                        continue
                    if node.module:
                        top = node.module.split(".")[0]
                        if top != "legion":
                            imports.add(top)

    return imports


def find_unused_dependencies(
    pyproject_path: Path | None = None,
) -> UnusedDepsResult:
    """Compare declared deps against actual imports."""
    deps = parse_dependencies(pyproject_path)
    actual_imports = collect_all_imports()

    scanned_files = sum(1 for _ in PACKAGE_ROOT.rglob("*.py"))

    unused: list[UnusedDependency] = []
    skipped: list[SkippedDependency] = []
    for group, packages in deps.items():
        for pkg_name, import_name in packages:
            if import_name in actual_imports:
                continue

            # Check runtime allowlist
            if pkg_name in RUNTIME_ALLOWLIST:
                skipped.append(
                    SkippedDependency(
                        package_name=pkg_name,
                        reason=RUNTIME_ALLOWLIST[pkg_name],
                        dependency_group=group,
                    )
                )
                continue

            # Skip dev CLI tools — invoked via `python -m`, never imported
            if group == "dev" and pkg_name in DEV_CLI_TOOLS:
                skipped.append(
                    SkippedDependency(
                        package_name=pkg_name,
                        reason="dev CLI tool (invoked via python -m)",
                        dependency_group=group,
                    )
                )
                continue

            unused.append(
                UnusedDependency(
                    package_name=pkg_name,
                    import_name=import_name,
                    dependency_group=group,
                )
            )

    return UnusedDepsResult(
        unused=unused, skipped=skipped, scanned_files=scanned_files
    )


def format_unused_deps(result: UnusedDepsResult, *, verbose: bool = False) -> str:
    """Format results into a human-readable report."""
    lines: list[str] = []

    if result.unused:
        lines.append(
            f"\nUnused dependencies found ({result.scanned_files} files scanned):\n"
        )
        for dep in sorted(
            result.unused, key=lambda d: (d.dependency_group, d.package_name)
        ):
            lines.append(f"   {dep.package_name} (import as '{dep.import_name}')")
    else:
        lines.append(
            f"All dependencies are used ({result.scanned_files} files scanned)."
        )

    if verbose and result.skipped:
        lines.append(f"\nSkipped ({len(result.skipped)} allowlisted):")
        for skipped in sorted(result.skipped, key=lambda d: d.package_name):
            lines.append(f"   {skipped.package_name} — {skipped.reason}")

    return "\n".join(lines)

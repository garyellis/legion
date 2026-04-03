"""Shared AST utilities for architectural analysis modules.

Provides import extraction and relative import resolution used by
dependency_check, banned_imports, and circular_imports.
"""

from __future__ import annotations

import ast
from pathlib import Path
from typing import NamedTuple


class ImportInfo(NamedTuple):
    """A single import found in a Python source file."""

    line: int
    module: str  # dotted module path (e.g. "legion.core.openstack" or "os.path")


def resolve_relative_import(
    filepath: Path,
    node: ast.ImportFrom,
    package_root: Path,
) -> str | None:
    """Resolve a relative import to an absolute dotted module path.

    Python relative import semantics:
    - ``from . import X`` (level=1): import from current package
    - ``from .. import X`` (level=2): import from parent package
    - ``from .sub import X`` (level=1, module='sub'): import sub of current package

    For __init__.py the file IS the package; for regular .py the package is
    the containing directory.  In both cases we strip the last path component
    to obtain the package, then go up ``level - 1`` additional levels.
    """
    parts = list(filepath.relative_to(package_root).parts)
    parts[-1] = parts[-1].removesuffix(".py")

    # Both __init__.py and regular modules: drop the last component to get
    # the containing package path.
    pkg_parts = parts[:-1]

    # Go up (level - 1) additional directories from the package.
    ascend = node.level - 1
    if ascend > 0:
        pkg_parts = pkg_parts[: len(pkg_parts) - ascend]
    if not pkg_parts:
        return None  # went above the package root

    base = "legion." + ".".join(pkg_parts)
    if node.module:
        return f"{base}.{node.module}"
    return base


def extract_all_imports(filepath: Path, package_root: Path) -> list[ImportInfo]:
    """Parse a Python file and return all import targets.

    Returns both legion-internal and external imports as ImportInfo tuples.
    Relative imports are resolved to absolute dotted paths.
    """
    source = filepath.read_text(encoding="utf-8")
    try:
        tree = ast.parse(source, filename=str(filepath))
    except SyntaxError:
        return []

    imports: list[ImportInfo] = []

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                imports.append(ImportInfo(line=node.lineno, module=alias.name))

        elif isinstance(node, ast.ImportFrom):
            if node.level and node.level > 0:
                # Relative import — resolve to absolute
                resolved = resolve_relative_import(filepath, node, package_root)
                if resolved:
                    imports.append(ImportInfo(line=node.lineno, module=resolved))
            elif node.module:
                imports.append(ImportInfo(line=node.lineno, module=node.module))
                # Also handle ``from legion import services`` → legion.services
                if node.module == "legion":
                    for alias in node.names:
                        imports.append(
                            ImportInfo(line=node.lineno, module=f"legion.{alias.name}")
                        )

    return imports

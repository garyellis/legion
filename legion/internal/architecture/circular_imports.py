"""Circular import detection via graph cycle analysis.

Builds a directed graph of module-to-module imports within the legion
package and detects cycles using DFS. Circular imports cause runtime
ImportError and should be treated as bugs.
"""

from __future__ import annotations

from pathlib import Path
from typing import NamedTuple

from legion.internal.architecture._ast_utils import extract_all_imports
from legion.internal.architecture.dependency_check import PACKAGE_ROOT


class ImportCycle(NamedTuple):
    """A circular import chain."""

    chain: tuple[str, ...]  # e.g. ("legion.a", "legion.b", "legion.a")


def _filepath_to_module(filepath: Path, package_root: Path) -> str:
    """Convert a file path to a dotted module name."""
    relative = filepath.relative_to(package_root)
    parts = list(relative.parts)
    parts[-1] = parts[-1].removesuffix(".py")
    if parts[-1] == "__init__":
        parts = parts[:-1]
    return "legion." + ".".join(parts) if parts else "legion"


def build_import_graph(root: Path | None = None) -> dict[str, set[str]]:
    """Build a directed graph of legion module imports.

    Returns adjacency list: module → set of imported legion modules.
    Only tracks imports within the legion package.
    """
    package_root = root or PACKAGE_ROOT
    graph: dict[str, set[str]] = {}

    for filepath in package_root.rglob("*.py"):
        module = _filepath_to_module(filepath, package_root)
        imports = extract_all_imports(filepath, package_root)

        legion_targets: set[str] = set()
        for imp in imports:
            if imp.module.startswith("legion."):
                legion_targets.add(imp.module)

        graph[module] = legion_targets

    return graph


def find_cycles(graph: dict[str, set[str]]) -> list[ImportCycle]:
    """Find all cycles in the import graph using DFS coloring.

    Uses white(0)/gray(1)/black(2) coloring to detect back edges.
    Returns minimal cycles (the path from the first gray node to itself).
    """
    WHITE, GRAY, BLACK = 0, 1, 2
    color: dict[str, int] = {node: WHITE for node in graph}
    path: list[str] = []
    cycles: list[ImportCycle] = []
    seen_cycle_keys: set[frozenset[str]] = set()

    def dfs(node: str) -> None:
        color[node] = GRAY
        path.append(node)

        for neighbor in graph.get(node, set()):
            if neighbor not in color:
                # Target module not in graph (external or missing) — skip
                continue
            if color[neighbor] == GRAY:
                # Back edge — found a cycle
                cycle_start = path.index(neighbor)
                cycle = tuple(path[cycle_start:]) + (neighbor,)
                # Deduplicate: same cycle can be found from different start nodes
                key = frozenset(path[cycle_start:])
                if key not in seen_cycle_keys:
                    seen_cycle_keys.add(key)
                    cycles.append(ImportCycle(chain=cycle))
            elif color[neighbor] == WHITE:
                dfs(neighbor)

        path.pop()
        color[node] = BLACK

    for node in graph:
        if color[node] == WHITE:
            dfs(node)

    return cycles


def find_circular_imports(root: Path | None = None) -> list[ImportCycle]:
    """Top-level entry point: build graph and find cycles."""
    graph = build_import_graph(root)
    return find_cycles(graph)


def format_cycles(cycles: list[ImportCycle]) -> str:
    """Format circular import chains into a human-readable report."""
    if not cycles:
        return "No circular imports found."

    lines = ["\nCircular import chains found:\n"]
    for cycle in sorted(cycles):
        chain_str = " → ".join(cycle.chain)
        lines.append(f"  {chain_str}")
    lines.append(
        "\nCircular imports cause runtime ImportError. "
        "Break the cycle by moving shared types to a lower layer "
        "or using lazy imports."
    )
    return "\n".join(lines)

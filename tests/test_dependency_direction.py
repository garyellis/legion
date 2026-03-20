"""Enforce architectural dependency direction via static import analysis.

Rules from CONTRIBUTING.md (imports flow DOWNWARD only):

    core/      → imports NOTHING from legion/
    domain/    → imports core/ models only (never core logic, never services/agents/surfaces)
    services/  → imports from core/ and domain/ only
    agents/    → imports from core/, domain/, services/ only
    surfaces   → import from any layer below, never from each other

This test parses every .py file's AST to extract `legion.*` imports and
verifies they only target allowed layers. No runtime imports needed — pure
static analysis.
"""

from __future__ import annotations

import ast
import os
from pathlib import Path
from typing import NamedTuple


PACKAGE_ROOT = Path(__file__).resolve().parent.parent / "legion"

# Layer classification order (lower index = lower layer)
LAYERS = ["core", "domain", "services", "agents"]
SURFACES = {"cli", "slack", "api", "tui"}

# For each layer, which legion sub-packages may it import from?
# An empty set means "no legion imports allowed".
LAYER_ALLOWED_IMPORTS: dict[str, set[str]] = {
    "plumbing": set(),                              # imports NOTHING from legion
    "core": {"plumbing"},                           # plumbing only
    "domain": {"plumbing", "core"},                 # core models only
    "services": {"plumbing", "core", "domain"},     # core + domain
    "agents": {"plumbing", "core", "domain", "services"},  # everything below
}

# Surfaces can import from all non-surface layers, but never from other surfaces.
SURFACE_ALLOWED_IMPORTS = {"plumbing", "core", "domain", "services", "agents"}

# The top-level legion/main.py is a thin bootstrap — it may import from any layer.
BOOTSTRAP_MODULES = {"main"}


class ImportViolation(NamedTuple):
    file: str
    line: int
    source_layer: str
    imported_module: str
    target_layer: str


def classify_layer(module_path: Path) -> str | None:
    """Determine which architectural layer a file belongs to.

    Returns the layer name (e.g. 'core', 'cli') or None for top-level
    bootstrap files that are exempt from checks.
    """
    relative = module_path.relative_to(PACKAGE_ROOT)
    parts = relative.parts

    if len(parts) == 1:
        # Top-level file like legion/main.py or legion/__init__.py
        stem = parts[0].removesuffix(".py")
        if stem in BOOTSTRAP_MODULES or stem == "__init__":
            return None  # exempt
        return None  # unknown top-level files are exempt

    top_dir = parts[0]
    if top_dir in SURFACES:
        return top_dir
    if top_dir in LAYER_ALLOWED_IMPORTS:
        return top_dir
    return None  # unknown directory — exempt


def extract_legion_imports(filepath: Path) -> list[tuple[int, str]]:
    """Parse a Python file's AST and return all legion.* import targets.

    Returns list of (line_number, dotted_module_name) tuples.
    """
    source = filepath.read_text(encoding="utf-8")
    try:
        tree = ast.parse(source, filename=str(filepath))
    except SyntaxError:
        return []

    imports: list[tuple[int, str]] = []

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name.startswith("legion."):
                    imports.append((node.lineno, alias.name))

        elif isinstance(node, ast.ImportFrom):
            if node.module and node.module.startswith("legion."):
                imports.append((node.lineno, node.module))
            elif node.level and node.level > 0:
                # Relative import — resolve to absolute
                resolved = _resolve_relative_import(filepath, node)
                if resolved and resolved.startswith("legion."):
                    imports.append((node.lineno, resolved))

    return imports


def _resolve_relative_import(filepath: Path, node: ast.ImportFrom) -> str | None:
    """Resolve a relative import to an absolute dotted module path."""
    parts = list(filepath.relative_to(PACKAGE_ROOT).parts)
    # Remove the filename to get the package path
    parts[-1] = parts[-1].removesuffix(".py")
    if parts[-1] == "__init__":
        parts = parts[:-1]

    # Go up `node.level` levels
    pkg_parts = parts[: len(parts) - node.level + 1]
    if not pkg_parts:
        return None

    base = "legion." + ".".join(pkg_parts)
    if node.module:
        return f"{base}.{node.module}"
    return base


def get_target_layer(dotted_import: str) -> str | None:
    """Extract the layer from a legion.X.* import string.

    'legion.core.openstack.models' → 'core'
    'legion.cli.main' → 'cli'
    'legion.main' → None (top-level bootstrap)
    """
    parts = dotted_import.split(".")
    if len(parts) < 2:
        return None
    # parts[0] = 'legion', parts[1] = layer/module
    target = parts[1]
    if target in LAYER_ALLOWED_IMPORTS or target in SURFACES:
        return target
    return None  # top-level module like legion.main


def find_violations() -> list[ImportViolation]:
    """Scan all .py files and return dependency direction violations."""
    violations: list[ImportViolation] = []

    for root, _dirs, files in os.walk(PACKAGE_ROOT):
        for filename in files:
            if not filename.endswith(".py"):
                continue

            filepath = Path(root) / filename
            source_layer = classify_layer(filepath)

            if source_layer is None:
                continue  # exempt

            imports = extract_legion_imports(filepath)

            for lineno, dotted_import in imports:
                target_layer = get_target_layer(dotted_import)
                if target_layer is None:
                    continue  # top-level import, exempt

                # Determine if this import is allowed
                if source_layer in SURFACES:
                    allowed = SURFACE_ALLOWED_IMPORTS
                    # Also check: no cross-surface imports
                    if target_layer in SURFACES and target_layer != source_layer:
                        violations.append(
                            ImportViolation(
                                file=str(filepath.relative_to(PACKAGE_ROOT.parent)),
                                line=lineno,
                                source_layer=source_layer,
                                imported_module=dotted_import,
                                target_layer=target_layer,
                            )
                        )
                        continue
                else:
                    allowed = LAYER_ALLOWED_IMPORTS[source_layer]

                if target_layer not in allowed and target_layer != source_layer:
                    violations.append(
                        ImportViolation(
                            file=str(filepath.relative_to(PACKAGE_ROOT.parent)),
                            line=lineno,
                            source_layer=source_layer,
                            imported_module=dotted_import,
                            target_layer=target_layer,
                        )
                    )

    return violations


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

def _format_violations(violations: list[ImportViolation]) -> str:
    lines = ["\nArchitectural dependency violations found:\n"]
    for v in sorted(violations):
        lines.append(
            f"  {v.file}:{v.line}  "
            f"[{v.source_layer}] imports [{v.target_layer}] "
            f"via '{v.imported_module}'"
        )
    lines.append(
        "\nRule: imports flow DOWNWARD only "
        "(core → domain → services → agents → surfaces). "
        "No lateral surface-to-surface imports."
    )
    return "\n".join(lines)


def test_no_dependency_direction_violations():
    """Every import in the codebase must respect the layer dependency DAG."""
    violations = find_violations()
    assert violations == [], _format_violations(violations)


def test_core_has_no_legion_imports():
    """core/ must not import anything from the legion package."""
    violations = [v for v in find_violations() if v.source_layer == "core"]
    assert violations == [], _format_violations(violations)


def test_surfaces_do_not_import_each_other():
    """No surface (cli/, slack/, api/, tui/) may import from another surface."""
    violations = [
        v for v in find_violations()
        if v.source_layer in SURFACES and v.target_layer in SURFACES
    ]
    assert violations == [], _format_violations(violations)


def test_domain_does_not_import_services_or_agents():
    """domain/ may only reference core/ models, never higher layers."""
    violations = [
        v for v in find_violations()
        if v.source_layer == "domain"
        and v.target_layer in {"services", "agents"} | SURFACES
    ]
    assert violations == [], _format_violations(violations)


def test_services_do_not_import_agents_or_surfaces():
    """services/ may only import from core/ and domain/."""
    violations = [
        v for v in find_violations()
        if v.source_layer == "services"
        and v.target_layer in {"agents"} | SURFACES
    ]
    assert violations == [], _format_violations(violations)


def test_layer_rules_are_complete():
    """Verify every Python file in the package is classified into a known layer.

    Guards against new top-level directories silently bypassing the checks.
    """
    unchecked_dirs: set[str] = set()

    for entry in PACKAGE_ROOT.iterdir():
        if not entry.is_dir():
            continue
        if entry.name.startswith("_"):
            continue  # __pycache__ etc.
        name = entry.name
        if name not in LAYER_ALLOWED_IMPORTS and name not in SURFACES:
            unchecked_dirs.add(name)

    assert unchecked_dirs == set(), (
        f"New directories {unchecked_dirs} are not covered by dependency rules. "
        f"Add them to LAYER_ALLOWED_IMPORTS or SURFACES in {__file__}"
    )

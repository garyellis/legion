"""Static import analysis for architectural dependency direction enforcement.

Rules (imports flow DOWNWARD only):

    plumbing/  → imports NOTHING from legion (stdlib + external libs only)
    internal/  → imports NOTHING from legion (stdlib + external libs only)
    core/      → imports plumbing/ only
    domain/    → imports plumbing/, core/ (models only, never logic)
    services/  → imports plumbing/, core/, domain/
    agents/    → imports plumbing/, core/, domain/, services/
    surfaces   → import from any layer below, never from each other
"""

from __future__ import annotations

import ast
from pathlib import Path
from typing import NamedTuple

from legion.internal.architecture._ast_utils import resolve_relative_import


PACKAGE_ROOT = Path(__file__).resolve().parent.parent.parent


# For each layer, which legion sub-packages may it import from?
# An empty set means "no legion imports allowed".
LAYER_ALLOWED_IMPORTS: dict[str, set[str]] = {
    "plumbing": set(),                                         # imports NOTHING from legion
    "internal": set(),                                         # imports NOTHING from legion
    "core": {"plumbing"},                                      # plumbing only
    "domain": {"plumbing", "core"},                            # core models only
    "services": {"plumbing", "core", "domain"},                # core + domain
    "agents": {"plumbing", "core", "domain", "services"},      # everything below
}

SURFACES = {"cli", "cli_dev", "slack", "api", "tui"}

# Surfaces can import from all non-surface layers, but never from other surfaces.
SURFACE_ALLOWED_IMPORTS = {"plumbing", "internal", "core", "domain", "services", "agents"}

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
            elif node.module == "legion":
                # ``from legion import services`` — the imported names are
                # the sub-packages, so treat each as ``legion.<name>``.
                for alias in node.names:
                    imports.append((node.lineno, f"legion.{alias.name}"))
            elif node.level and node.level > 0:
                # Relative import — resolve to absolute
                resolved = resolve_relative_import(filepath, node, PACKAGE_ROOT)
                if resolved and resolved.startswith("legion."):
                    imports.append((node.lineno, resolved))

    return imports


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

    for filepath in PACKAGE_ROOT.rglob("*.py"):
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


def format_violations(violations: list[ImportViolation]) -> str:
    """Format violations into a human-readable report."""
    lines = ["\nArchitectural dependency violations found:\n"]
    for v in sorted(violations):
        lines.append(
            f"  {v.file}:{v.line}  "
            f"[{v.source_layer}] imports [{v.target_layer}] "
            f"via '{v.imported_module}'"
        )
    lines.append(
        "\nRule: imports flow DOWNWARD only "
        "(plumbing → core → domain → services → agents → surfaces). "
        "No lateral surface-to-surface imports."
    )
    return "\n".join(lines)


def find_uncovered_directories() -> set[str]:
    """Find top-level directories under legion/ not covered by layer rules."""
    unchecked: set[str] = set()
    for entry in PACKAGE_ROOT.iterdir():
        if not entry.is_dir():
            continue
        if entry.name.startswith("_"):
            continue  # __pycache__ etc.
        if entry.name not in LAYER_ALLOWED_IMPORTS and entry.name not in SURFACES:
            unchecked.add(entry.name)
    return unchecked

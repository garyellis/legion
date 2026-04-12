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

SURFACES = {"cli", "cli_dev", "slack", "api", "tui", "agent_runner"}

# Surfaces can import from all non-surface layers, but never from other surfaces.
SURFACE_ALLOWED_IMPORTS = {"plumbing", "internal", "core", "domain", "services", "agents"}

# Top-level modules that are intentionally allowed at the package root.
ALLOWED_TOP_LEVEL_MODULES = {"main", "orm_registry"}

# Approved dynamic-import seams. Only these files may dynamically import
# internal ``legion.*`` modules.
ALLOWED_DYNAMIC_IMPORT_SITES = {
    Path("cli/main.py"),
    Path("cli_dev/main.py"),
    Path("slack/main.py"),
    Path("slack/manifest.py"),
}

DYNAMIC_IMPORT_TARGET = "dynamic-import"


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
        if stem in ALLOWED_TOP_LEVEL_MODULES or stem == "__init__":
            return None  # exempt
        return None  # unknown top-level files are still handled elsewhere

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


def _evaluate_string_expression(node: ast.AST, bindings: dict[str, str]) -> str | None:
    """Best-effort evaluation of a string-like AST node.

    The dynamic-import checker only needs enough resolution to spot
    ``legion.*`` targets. Unresolved formatted values collapse to an empty
    string so f-strings still contribute their constant prefix.
    """
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value

    if isinstance(node, ast.Name):
        return bindings.get(node.id)

    if isinstance(node, ast.JoinedStr):
        pieces: list[str] = []
        for value in node.values:
            if isinstance(value, ast.Constant) and isinstance(value.value, str):
                pieces.append(value.value)
            elif isinstance(value, ast.FormattedValue):
                resolved = _evaluate_string_expression(value.value, bindings)
                pieces.append(resolved or "")
            else:
                return None
        return "".join(pieces)

    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
        left = _evaluate_string_expression(node.left, bindings)
        right = _evaluate_string_expression(node.right, bindings)
        if left is None or right is None:
            return None
        return left + right

    return None


def _collect_string_bindings(tree: ast.AST) -> dict[str, str]:
    """Collect simple string bindings used by dynamic import targets."""
    bindings: dict[str, str] = {}

    for node in ast.walk(tree):
        if isinstance(node, ast.Assign):
            value = _evaluate_string_expression(node.value, bindings)
            if value is None:
                continue
            for target in node.targets:
                if isinstance(target, ast.Name):
                    bindings[target.id] = value
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            value = _evaluate_string_expression(node.value, bindings) if node.value else None
            if value is not None:
                bindings[node.target.id] = value

    return bindings


def _collect_dynamic_import_aliases(tree: ast.AST) -> tuple[set[str], set[str]]:
    """Collect aliases that refer to ``importlib`` and ``import_module``."""
    importlib_aliases: set[str] = {"importlib"}
    import_module_aliases: set[str] = {"__import__"}

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name == "importlib":
                    importlib_aliases.add(alias.asname or alias.name)
        elif isinstance(node, ast.ImportFrom) and node.module == "importlib":
            for alias in node.names:
                if alias.name == "import_module":
                    import_module_aliases.add(alias.asname or alias.name)

    return importlib_aliases, import_module_aliases


def _extract_dynamic_import_calls(filepath: Path) -> list[tuple[int, str]]:
    """Return dynamic imports that target internal ``legion.*`` modules."""
    source = filepath.read_text(encoding="utf-8")
    try:
        tree = ast.parse(source, filename=str(filepath))
    except SyntaxError:
        return []

    bindings = _collect_string_bindings(tree)
    importlib_aliases, import_module_aliases = _collect_dynamic_import_aliases(tree)

    calls: list[tuple[int, str]] = []

    for node in ast.walk(tree):
        if not isinstance(node, ast.Call) or not node.args:
            continue

        target: str | None = None
        call_name = None

        if isinstance(node.func, ast.Name):
            call_name = node.func.id
            if call_name in import_module_aliases:
                target = _evaluate_string_expression(node.args[0], bindings)
        elif isinstance(node.func, ast.Attribute):
            if isinstance(node.func.value, ast.Name):
                if node.func.value.id in importlib_aliases and node.func.attr == "import_module":
                    call_name = f"{node.func.value.id}.import_module"
                    target = _evaluate_string_expression(node.args[0], bindings)

        if target and target.startswith("legion.") and call_name is not None:
            calls.append((node.lineno, f"{call_name}({target})"))

    return calls


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


def _get_source_label(filepath: Path) -> str:
    """Return a stable label for a file's architectural source context."""
    source_layer = classify_layer(filepath)
    if source_layer is not None:
        return source_layer
    if filepath.parent == PACKAGE_ROOT and filepath.name.endswith(".py"):
        if filepath.stem in ALLOWED_TOP_LEVEL_MODULES:
            return "bootstrap"
        return "top-level"
    return "unclassified"


def find_violations() -> list[ImportViolation]:
    """Scan all .py files and return dependency direction violations."""
    violations: list[ImportViolation] = []

    for filepath in PACKAGE_ROOT.rglob("*.py"):
        source_layer = classify_layer(filepath)

        if source_layer is not None:
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

        for lineno, dynamic_import in _extract_dynamic_import_calls(filepath):
            if filepath.relative_to(PACKAGE_ROOT) in ALLOWED_DYNAMIC_IMPORT_SITES:
                continue
            violations.append(
                ImportViolation(
                    file=str(filepath.relative_to(PACKAGE_ROOT.parent)),
                    line=lineno,
                    source_layer=_get_source_label(filepath),
                    imported_module=dynamic_import,
                    target_layer=DYNAMIC_IMPORT_TARGET,
                )
            )

    return violations


def format_violations(violations: list[ImportViolation]) -> str:
    """Format violations into a human-readable report."""
    lines = ["\nArchitectural dependency violations found:\n"]
    for v in sorted(violations):
        if v.target_layer == DYNAMIC_IMPORT_TARGET:
            lines.append(
                f"  {v.file}:{v.line}  "
                f"[{v.source_layer}] uses unapproved dynamic import "
                f"via '{v.imported_module}'"
            )
        else:
            lines.append(
                f"  {v.file}:{v.line}  "
                f"[{v.source_layer}] imports [{v.target_layer}] "
                f"via '{v.imported_module}'"
            )
    lines.append(
        "\nRule: imports flow DOWNWARD only "
        "(plumbing → core → domain → services → agents → surfaces). "
        "No lateral surface-to-surface imports. "
        "Dynamic imports are only allowed from approved seams."
    )
    return "\n".join(lines)


def find_uncovered_directories() -> set[str]:
    """Find top-level directories/files under legion/ not covered by layer rules."""
    unchecked: set[str] = set()
    for entry in PACKAGE_ROOT.iterdir():
        if entry.is_dir():
            if entry.name.startswith("_"):
                continue  # __pycache__ etc.
            if entry.name not in LAYER_ALLOWED_IMPORTS and entry.name not in SURFACES:
                unchecked.add(entry.name)
        elif entry.is_file() and entry.suffix == ".py":
            if entry.name == "__init__.py":
                continue
            if entry.stem not in ALLOWED_TOP_LEVEL_MODULES:
                unchecked.add(entry.name)
    return unchecked

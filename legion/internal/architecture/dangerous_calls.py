"""Dangerous stdlib call and import detection by architectural layer.

Enforces three categories of security constraints:
1. Stdlib modules restricted to specific layers (e.g., subprocess only in core/internal/plumbing)
2. Modules banned globally (e.g., pickle, marshal)
3. Function calls banned globally (e.g., eval, exec, os.system, os.popen)
"""

from __future__ import annotations

import ast
from pathlib import Path
from typing import NamedTuple

from legion.internal.architecture.dependency_check import (
    PACKAGE_ROOT,
    classify_layer,
)

# --- Configuration ---

# Stdlib modules allowed only in certain layers.
# Any layer not listed is prohibited from importing the module.
LAYER_ALLOWED_STDLIB: dict[str, set[str]] = {
    "subprocess": {"plumbing", "internal", "core"},
}

# Modules banned from import everywhere — no exceptions.
GLOBALLY_BANNED_IMPORTS: set[str] = {"pickle", "marshal"}

# (module, function) pairs banned as calls everywhere.
# "builtins" is a pseudo-module for bare names like eval() and exec().
GLOBALLY_BANNED_CALLS: list[tuple[str, str]] = [
    ("os", "system"),
    ("os", "popen"),
    ("builtins", "eval"),
    ("builtins", "exec"),
]

# Bare function names that are globally banned (eval, exec).
_BANNED_BARE_NAMES: set[str] = {
    fn for mod, fn in GLOBALLY_BANNED_CALLS if mod == "builtins"
}

# Module-qualified banned calls: module → set of function names.
_BANNED_ATTR_CALLS: dict[str, set[str]] = {}
for _mod, _fn in GLOBALLY_BANNED_CALLS:
    if _mod != "builtins":
        _BANNED_ATTR_CALLS.setdefault(_mod, set()).add(_fn)


class DangerousCallViolation(NamedTuple):
    file: str
    line: int
    layer: str
    violation_type: str   # "banned_import", "restricted_import", "banned_call"
    detail: str


def _scan_file(filepath: Path, layer: str) -> list[DangerousCallViolation]:
    """Scan a single file for dangerous imports and calls."""
    source = filepath.read_text(encoding="utf-8")
    try:
        tree = ast.parse(source, filename=str(filepath))
    except SyntaxError:
        return []

    violations: list[DangerousCallViolation] = []
    rel_path = str(filepath.relative_to(PACKAGE_ROOT.parent))

    # Track direct imports like ``from os import system`` so we can flag
    # bare calls like ``system(...)`` later.
    direct_danger_imports: dict[str, tuple[str, str]] = {}
    # e.g. {"system": ("os", "system")}

    for node in ast.walk(tree):
        # --- Import checks ---
        if isinstance(node, ast.Import):
            for alias in node.names:
                top = alias.name.split(".")[0]
                _check_import(
                    violations, rel_path, node.lineno, layer, top,
                    f"import {alias.name}",
                )

        elif isinstance(node, ast.ImportFrom):
            if node.level and node.level > 0:
                continue  # relative imports are intra-package
            if node.module:
                top = node.module.split(".")[0]
                names_str = ", ".join(a.name for a in node.names)
                _check_import(
                    violations, rel_path, node.lineno, layer, top,
                    f"from {node.module} import {names_str}",
                )
                # Track ``from os import system`` patterns
                if top in _BANNED_ATTR_CALLS:
                    for alias in node.names:
                        if alias.name in _BANNED_ATTR_CALLS[top]:
                            local_name = alias.asname or alias.name
                            direct_danger_imports[local_name] = (top, alias.name)

        # --- Call checks ---
        elif isinstance(node, ast.Call):
            # Bare call: eval(...), exec(...)
            if isinstance(node.func, ast.Name):
                name = node.func.id
                if name in _BANNED_BARE_NAMES:
                    violations.append(DangerousCallViolation(
                        file=rel_path,
                        line=node.lineno,
                        layer=layer,
                        violation_type="banned_call",
                        detail=f"call to '{name}()' is banned",
                    ))
                # Also catch ``from os import system; system(...)``
                elif name in direct_danger_imports:
                    mod, fn = direct_danger_imports[name]
                    violations.append(DangerousCallViolation(
                        file=rel_path,
                        line=node.lineno,
                        layer=layer,
                        violation_type="banned_call",
                        detail=f"call to '{mod}.{fn}()' (imported as '{name}') is banned",
                    ))

            # Attribute call: os.system(...), os.popen(...)
            elif isinstance(node.func, ast.Attribute):
                if isinstance(node.func.value, ast.Name):
                    mod_name = node.func.value.id
                    attr_name = node.func.attr
                    if (
                        mod_name in _BANNED_ATTR_CALLS
                        and attr_name in _BANNED_ATTR_CALLS[mod_name]
                    ):
                        violations.append(DangerousCallViolation(
                            file=rel_path,
                            line=node.lineno,
                            layer=layer,
                            violation_type="banned_call",
                            detail=f"call to '{mod_name}.{attr_name}()' is banned",
                        ))

    return violations


def _check_import(
    violations: list[DangerousCallViolation],
    rel_path: str,
    lineno: int,
    layer: str,
    top_module: str,
    import_stmt: str,
) -> None:
    """Check a single import against banned and restricted rules."""
    # Globally banned?
    if top_module in GLOBALLY_BANNED_IMPORTS:
        violations.append(DangerousCallViolation(
            file=rel_path,
            line=lineno,
            layer=layer,
            violation_type="banned_import",
            detail=f"'{import_stmt}' — '{top_module}' is banned globally",
        ))
        return

    # Layer-restricted?
    if top_module in LAYER_ALLOWED_STDLIB:
        allowed_layers = LAYER_ALLOWED_STDLIB[top_module]
        if layer not in allowed_layers:
            violations.append(DangerousCallViolation(
                file=rel_path,
                line=lineno,
                layer=layer,
                violation_type="restricted_import",
                detail=(
                    f"'{import_stmt}' — '{top_module}' is only allowed in "
                    f"{sorted(allowed_layers)} layers"
                ),
            ))


def find_dangerous_call_violations() -> list[DangerousCallViolation]:
    """Scan all .py files and return dangerous call/import violations."""
    violations: list[DangerousCallViolation] = []

    for filepath in PACKAGE_ROOT.rglob("*.py"):
        layer = classify_layer(filepath)
        if layer is None:
            continue

        # Surfaces are exempt from layer-restricted imports but NOT from
        # globally banned imports/calls.  We still scan them.
        violations.extend(_scan_file(filepath, layer))

    return violations


def format_dangerous_violations(
    violations: list[DangerousCallViolation],
) -> str:
    """Format dangerous call violations into a human-readable report."""
    lines = ["\nDangerous call/import violations found:\n"]
    for v in sorted(violations):
        lines.append(f"  {v.file}:{v.line}  [{v.layer}] {v.detail}")
    lines.append(
        "\nRule: certain stdlib modules and functions are restricted or banned. "
        "See LAYER_ALLOWED_STDLIB and GLOBALLY_BANNED_* in "
        "legion/internal/architecture/dangerous_calls.py"
    )
    return "\n".join(lines)

"""Enforce architectural dependency direction via static import analysis.

Delegates to ``legion.internal.architecture.dependency_check`` for the
actual logic. This file contains only pytest test functions.
"""

from __future__ import annotations

import ast
import tempfile
import textwrap
from pathlib import Path

import pytest

from legion.internal.architecture._ast_utils import resolve_relative_import
from legion.internal.architecture import dependency_check
from legion.internal.architecture.dependency_check import (
    LAYER_ALLOWED_IMPORTS,
    PACKAGE_ROOT,
    SURFACES,
    ImportViolation,
    extract_legion_imports,
    find_uncovered_directories,
    find_violations,
    format_violations,
)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_no_dependency_direction_violations():
    """Every import in the codebase must respect the layer dependency DAG."""
    violations = find_violations()
    assert violations == [], format_violations(violations)


def test_core_has_no_upward_imports():
    """core/ may only import from plumbing/ — nothing else in legion."""
    violations = [v for v in find_violations() if v.source_layer == "core"]
    assert violations == [], format_violations(violations)


def test_surfaces_do_not_import_each_other():
    """No surface (cli/, slack/, api/, tui/) may import from another surface."""
    violations = [
        v for v in find_violations()
        if v.source_layer in SURFACES and v.target_layer in SURFACES
    ]
    assert violations == [], format_violations(violations)


def test_domain_does_not_import_services_or_agents():
    """domain/ may only reference core/ models, never higher layers."""
    violations = [
        v for v in find_violations()
        if v.source_layer == "domain"
        and v.target_layer in {"services", "agents"} | SURFACES
    ]
    assert violations == [], format_violations(violations)


def test_services_do_not_import_agents_or_surfaces():
    """services/ may only import from core/ and domain/."""
    violations = [
        v for v in find_violations()
        if v.source_layer == "services"
        and v.target_layer in {"agents"} | SURFACES
    ]
    assert violations == [], format_violations(violations)


def test_relative_import_resolution():
    """Relative imports resolve correctly for regular modules and __init__.py."""

    def make_node(level: int, module: str | None = None) -> ast.ImportFrom:
        return ast.ImportFrom(module=module, names=[], level=level)

    # services/dispatch_service.py: from . import X → legion.services
    path = PACKAGE_ROOT / "services" / "dispatch_service.py"
    result = resolve_relative_import(path, make_node(level=1), PACKAGE_ROOT)
    assert result == "legion.services", f"got {result}"

    # services/dispatch_service.py: from .filter_service import X
    result = resolve_relative_import(path, make_node(level=1, module="filter_service"), PACKAGE_ROOT)
    assert result == "legion.services.filter_service", f"got {result}"

    # services/__init__.py: from . import X → legion.services
    init_path = PACKAGE_ROOT / "services" / "__init__.py"
    result = resolve_relative_import(init_path, make_node(level=1), PACKAGE_ROOT)
    assert result == "legion.services", f"got {result}"

    # services/sub/module.py: from .. import X → legion.services
    nested_path = PACKAGE_ROOT / "services" / "sub" / "module.py"
    result = resolve_relative_import(nested_path, make_node(level=2), PACKAGE_ROOT)
    assert result == "legion.services", f"got {result}"

    # services/sub/module.py: from ..domain import models
    result = resolve_relative_import(nested_path, make_node(level=2, module="domain.models"), PACKAGE_ROOT)
    assert result == "legion.services.domain.models", f"got {result}"

    # services/sub/__init__.py: from .. import X → legion.services
    nested_init = PACKAGE_ROOT / "services" / "sub" / "__init__.py"
    result = resolve_relative_import(nested_init, make_node(level=2), PACKAGE_ROOT)
    assert result == "legion.services", f"got {result}"

    # core/module.py: from .. import X → goes above package root → None
    core_path = PACKAGE_ROOT / "core" / "module.py"
    result = resolve_relative_import(core_path, make_node(level=2), PACKAGE_ROOT)
    assert result is None, f"got {result}"


def test_from_legion_import_detected():
    """``from legion import services`` is detected as importing legion.services."""
    code = textwrap.dedent("""\
        from legion import services
        from legion import domain, core
    """)

    with tempfile.NamedTemporaryFile(
        suffix=".py", dir=PACKAGE_ROOT / "agents", mode="w", delete=False
    ) as f:
        f.write(code)
        f.flush()
        tmp_path = Path(f.name)

    try:
        imports = extract_legion_imports(tmp_path)
        imported_modules = [mod for _, mod in imports]
        assert "legion.services" in imported_modules
        assert "legion.domain" in imported_modules
        assert "legion.core" in imported_modules
    finally:
        tmp_path.unlink()


def test_layer_rules_are_complete():
    """Verify every directory in legion/ is classified into a known layer.

    Guards against new top-level directories silently bypassing the checks.
    """
    unchecked = find_uncovered_directories()
    assert unchecked == set(), (
        f"New directories {unchecked} are not covered by dependency rules. "
        f"Add them to LAYER_ALLOWED_IMPORTS or SURFACES in "
        f"legion/internal/architecture/dependency_check.py"
    )


def test_layer_rules_fail_closed_for_unclassified_top_level_modules(
    monkeypatch: pytest.MonkeyPatch,
):
    """Unknown top-level ``legion/*.py`` modules must be reported."""
    with tempfile.TemporaryDirectory() as tmpdir:
        root = Path(tmpdir)
        (root / "main.py").write_text("", encoding="utf-8")
        (root / "orm_registry.py").write_text("", encoding="utf-8")
        (root / "example.py").write_text("", encoding="utf-8")
        (root / "cli").mkdir()

        monkeypatch.setattr(dependency_check, "PACKAGE_ROOT", root)

        unchecked = dependency_check.find_uncovered_directories()

    assert "example.py" in unchecked
    assert "main.py" not in unchecked
    assert "orm_registry.py" not in unchecked


def test_dynamic_import_sites_are_allowlisted(
    monkeypatch: pytest.MonkeyPatch,
):
    """Only approved internal dynamic-import seams may use ``legion.*`` targets."""
    with tempfile.TemporaryDirectory() as tmpdir:
        root = Path(tmpdir)

        allowed = root / "cli" / "main.py"
        allowed.parent.mkdir(parents=True)
        allowed.write_text(
            textwrap.dedent(
                """\
                import importlib

                def load() -> None:
                    importlib.import_module("legion.cli.commands.example")
                """
            ),
            encoding="utf-8",
        )

        blocked = root / "services" / "helper.py"
        blocked.parent.mkdir(parents=True)
        blocked.write_text(
            textwrap.dedent(
                """\
                from importlib import import_module

                def load() -> None:
                    import_module("legion.services.internal")
                """
            ),
            encoding="utf-8",
        )

        external = root / "core" / "module.py"
        external.parent.mkdir(parents=True)
        external.write_text(
            textwrap.dedent(
                """\
                from importlib import import_module

                def load() -> None:
                    import_module("kubernetes.client")
                """
            ),
            encoding="utf-8",
        )

        monkeypatch.setattr(dependency_check, "PACKAGE_ROOT", root)

        violations = dependency_check.find_violations()

    assert len(violations) == 1
    violation = violations[0]
    assert violation.file.endswith("services/helper.py")
    assert violation.target_layer == dependency_check.DYNAMIC_IMPORT_TARGET
    assert "legion.services.internal" in violation.imported_module

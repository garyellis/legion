"""Enforce that banned external packages are not imported in restricted layers."""

from __future__ import annotations

from legion.internal.architecture.banned_imports import (
    find_banned_import_violations,
    format_banned_violations,
)


def test_no_banned_import_violations() -> None:
    """No layer imports a banned external package."""
    violations = find_banned_import_violations()
    assert violations == [], format_banned_violations(violations)

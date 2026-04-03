"""Enforce that no circular import chains exist in the codebase."""

from __future__ import annotations

from legion.internal.architecture.circular_imports import (
    find_circular_imports,
    format_cycles,
)


def test_no_circular_imports() -> None:
    """No circular import chains exist in the legion package."""
    cycles = find_circular_imports()
    assert cycles == [], format_cycles(cycles)

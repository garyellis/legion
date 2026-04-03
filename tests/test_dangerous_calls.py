"""Gate test: no dangerous stdlib calls or imports in the codebase."""

from __future__ import annotations

from legion.internal.architecture.dangerous_calls import (
    find_dangerous_call_violations,
    format_dangerous_violations,
)


def test_no_dangerous_call_violations() -> None:
    violations = find_dangerous_call_violations()
    assert violations == [], format_dangerous_violations(violations)

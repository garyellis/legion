"""Static type checking wrapper for architectural enforcement.

Invokes mypy programmatically and returns structured results that
can be consumed by CLI commands or tests.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path
from typing import NamedTuple

PACKAGE_ROOT = Path(__file__).resolve().parent.parent.parent


class TypeCheckError(NamedTuple):
    file: str
    line: int
    column: int
    severity: str  # "error" | "warning" | "note"
    code: str  # mypy error code, e.g. "arg-type"
    message: str


class TypeCheckResult(NamedTuple):
    success: bool
    errors: list[TypeCheckError]
    stdout: str
    stderr: str
    return_code: int


def _parse_mypy_output(output: str) -> list[TypeCheckError]:
    """Parse mypy output lines into structured errors.

    Expected format: ``file.py:line:col: severity: message  [code]``
    """
    errors: list[TypeCheckError] = []
    for line in output.splitlines():
        if ": error:" not in line and ": warning:" not in line and ": note:" not in line:
            continue

        # Split on first colon-space after col to get file:line:col vs rest
        parts = line.split(":")
        if len(parts) < 5:
            continue

        try:
            filepath = parts[0].strip()
            lineno = int(parts[1].strip())
            col = int(parts[2].strip())
        except (ValueError, IndexError):
            continue

        # Rejoin remaining parts — severity: message  [code]
        rest = ":".join(parts[3:]).strip()
        # rest = "error: Incompatible return value  [return-value]"
        sev_end = rest.index(":")
        severity = rest[:sev_end].strip()
        msg_part = rest[sev_end + 1:].strip()

        # Extract error code from bracketed suffix
        code = ""
        if msg_part.endswith("]"):
            bracket_start = msg_part.rfind("[")
            if bracket_start != -1:
                code = msg_part[bracket_start + 1:-1]
                msg_part = msg_part[:bracket_start].strip()

        errors.append(TypeCheckError(
            file=filepath,
            line=lineno,
            column=col,
            severity=severity,
            code=code,
            message=msg_part,
        ))

    return errors


def run_type_check(
    paths: list[str] | None = None,
    *,
    strict: bool = False,
) -> TypeCheckResult:
    """Run mypy on the specified paths or the entire legion package.

    Args:
        paths: Specific files or directories to check. Defaults to the
               legion package root.
        strict: Enable mypy --strict mode for maximum enforcement.

    Returns:
        Structured result with parsed errors and raw output.
    """
    targets = paths or [str(PACKAGE_ROOT)]

    cmd = [
        sys.executable, "-m", "mypy",
        "--show-column-numbers",
        "--show-error-codes",
        "--no-error-summary",
    ]

    if strict:
        cmd.append("--strict")

    cmd.extend(targets)

    result = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        cwd=str(PACKAGE_ROOT.parent),  # project root
    )

    errors = _parse_mypy_output(result.stdout)

    return TypeCheckResult(
        success=result.returncode == 0,
        errors=errors,
        stdout=result.stdout,
        stderr=result.stderr,
        return_code=result.returncode,
    )


def format_type_errors(result: TypeCheckResult) -> str:
    """Format type check results into a human-readable report."""
    if result.success:
        return "No type errors found."

    lines = ["\nType checking errors found:\n"]

    for err in result.errors:
        if err.severity == "error":
            code_suffix = f"  [{err.code}]" if err.code else ""
            lines.append(f"  {err.file}:{err.line}:{err.column}  {err.message}{code_suffix}")

    error_count = sum(1 for e in result.errors if e.severity == "error")
    lines.append(f"\n{error_count} error(s) found.")

    return "\n".join(lines)

from __future__ import annotations

from typing import Annotated, Optional

import typer

from legion.plumbing.registry import register_command
from legion.cli_dev.views import print_message, render_error
from legion.internal.architecture.banned_imports import (
    find_banned_import_violations,
    format_banned_violations,
)
from legion.internal.architecture.dangerous_calls import (
    find_dangerous_call_violations,
    format_dangerous_violations,
)
from legion.internal.architecture.circular_imports import (
    find_circular_imports,
    format_cycles,
)
from legion.internal.architecture.security_scan import (
    format_security_findings,
    run_security_scan,
)
from legion.internal.architecture.sensitive_files import (
    check_staged_files,
    format_sensitive_violations,
)
from legion.internal.architecture.vuln_scan import (
    format_vuln_scan,
    run_vuln_scan,
)
from legion.internal.architecture.dead_code import (
    format_dead_code,
    run_dead_code_check,
)
from legion.internal.architecture.dependency_check import (
    find_uncovered_directories,
    find_violations,
    format_violations,
)
from legion.internal.architecture.type_check import (
    format_type_errors,
    run_type_check,
)
from legion.internal.architecture.unused_deps import (
    find_unused_dependencies,
    format_unused_deps,
)


def _format_uncovered_directories(uncovered: set[str]) -> str:
    """Format directories not covered by the dependency rules."""
    lines = ["\nUncovered directories found:\n"]
    for name in sorted(uncovered):
        lines.append(f"  {name}")
    lines.append(
        "\nRule: every top-level directory under legion/ must be covered by "
        "LAYER_ALLOWED_IMPORTS or SURFACES in "
        "legion/internal/architecture/dependency_check.py"
    )
    return "\n".join(lines)


@register_command("architecture", "check")
def architecture_check(
    verbose: Annotated[bool, typer.Option("--verbose", "-v", help="Show per-file details")] = False,
) -> None:
    """Check architectural constraints: dependency direction + banned imports."""
    uncovered = find_uncovered_directories()
    if uncovered:
        render_error(
            f"Uncovered directories: {uncovered}. "
            "Add them to LAYER_ALLOWED_IMPORTS or SURFACES in "
            "legion/internal/architecture/dependency_check.py"
        )
        raise typer.Exit(code=1)

    violations = find_violations()
    if violations:
        render_error(format_violations(violations))
        raise typer.Exit(code=1)

    banned = find_banned_import_violations()
    if banned:
        render_error(format_banned_violations(banned))
        raise typer.Exit(code=1)

    dangerous = find_dangerous_call_violations()
    if dangerous:
        render_error(format_dangerous_violations(dangerous))
        raise typer.Exit(code=1)

    print_message("No architectural violations found.", style="green")


@register_command("architecture", "gate")
def architecture_gate() -> None:
    """Run the enforced developer gate for Legion changes."""
    failures: list[str] = []

    uncovered = find_uncovered_directories()
    if uncovered:
        failures.append(_format_uncovered_directories(uncovered))

    violations = find_violations()
    if violations:
        failures.append(format_violations(violations))

    banned = find_banned_import_violations()
    if banned:
        failures.append(format_banned_violations(banned))

    dangerous = find_dangerous_call_violations()
    if dangerous:
        failures.append(format_dangerous_violations(dangerous))

    type_result = run_type_check()
    if not type_result.success:
        failures.append(format_type_errors(type_result))

    cycles = find_circular_imports()
    if cycles:
        failures.append(format_cycles(cycles))

    secrets = check_staged_files()
    if secrets:
        failures.append(format_sensitive_violations(secrets))

    if failures:
        render_error("\n".join(failures))
        raise typer.Exit(code=1)

    print_message("No gate violations found.", style="green")


@register_command("architecture", "typecheck")
def architecture_typecheck(
    path: Annotated[
        Optional[list[str]],
        typer.Argument(help="Specific files or directories to check (default: entire package)"),
    ] = None,
    strict: Annotated[bool, typer.Option("--strict", "-s", help="Enable strict mode")] = False,
) -> None:
    """Run static type checking on the codebase."""
    result = run_type_check(paths=path, strict=strict)

    if result.success:
        print_message("No type errors found.", style="green")
    else:
        render_error(format_type_errors(result))
        raise typer.Exit(code=1)


@register_command("architecture", "circular")
def architecture_circular() -> None:
    """Detect circular import chains in the codebase."""
    cycles = find_circular_imports()

    if not cycles:
        print_message("No circular imports found.", style="green")
    else:
        render_error(format_cycles(cycles))
        raise typer.Exit(code=1)


@register_command("architecture", "deadcode")
def architecture_deadcode(
    path: Annotated[
        Optional[list[str]],
        typer.Argument(help="Specific files or directories to check (default: entire package)"),
    ] = None,
    min_confidence: Annotated[
        int, typer.Option("--min-confidence", "-c", help="Minimum confidence threshold (0-100)")
    ] = 80,
) -> None:
    """Find potentially unused code (advisory)."""
    result = run_dead_code_check(paths=path, min_confidence=min_confidence)

    if result.success:
        print_message("No dead code found.", style="green")
    else:
        render_error(format_dead_code(result))
        raise typer.Exit(code=1)


@register_command("architecture", "dangerous-calls")
def architecture_dangerous_calls() -> None:
    """Detect banned stdlib calls and restricted module imports."""
    violations = find_dangerous_call_violations()

    if not violations:
        print_message("No dangerous call/import violations found.", style="green")
    else:
        render_error(format_dangerous_violations(violations))
        raise typer.Exit(code=1)


@register_command("architecture", "secrets-check")
def architecture_secrets_check() -> None:
    """Detect sensitive files (keys, credentials, .env) staged for commit."""
    violations = check_staged_files()

    if not violations:
        print_message("No sensitive files staged.", style="green")
    else:
        render_error(format_sensitive_violations(violations))
        raise typer.Exit(code=1)


@register_command("architecture", "security")
def architecture_security(
    path: Annotated[
        Optional[list[str]],
        typer.Argument(help="Specific files or directories to scan (default: entire package)"),
    ] = None,
    severity: Annotated[
        str, typer.Option("--severity", "-s", help="Minimum severity: low, medium, high")
    ] = "medium",
    gate: Annotated[
        bool, typer.Option("--gate", help="Exit with code 1 on findings (for CI)")
    ] = False,
) -> None:
    """Run bandit static security analysis (advisory)."""
    result = run_security_scan(paths=path, severity=severity)

    if result.success:
        print_message("No security findings.", style="green")
    else:
        render_error(format_security_findings(result))
        if gate:
            raise typer.Exit(code=1)


@register_command("architecture", "audit")
def architecture_audit() -> None:
    """Scan dependencies for known vulnerabilities (advisory, needs network)."""
    result = run_vuln_scan()

    if result.success:
        print_message("No known vulnerabilities found.", style="green")
    else:
        render_error(format_vuln_scan(result))


@register_command("architecture", "unused-deps")
def architecture_unused_deps(
    verbose: Annotated[bool, typer.Option("--verbose", "-v", help="Show allowlisted deps")] = False,
) -> None:
    """Find declared dependencies with no matching imports (advisory)."""
    result = find_unused_dependencies()

    if not result.unused:
        print_message(format_unused_deps(result, verbose=verbose), style="green")
    else:
        render_error(format_unused_deps(result, verbose=verbose))

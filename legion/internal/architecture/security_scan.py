"""Static application security testing via bandit.

Invokes bandit programmatically and returns structured results that
can be consumed by CLI commands. Advisory by default.
"""

from __future__ import annotations

import json
import subprocess
import sys
from typing import NamedTuple

from legion.internal.architecture.dependency_check import PACKAGE_ROOT

PROJECT_ROOT = PACKAGE_ROOT.parent


class SecurityFinding(NamedTuple):
    file: str
    line: int
    test_id: str        # e.g., "B602"
    test_name: str      # e.g., "subprocess_popen_with_shell_equals_true"
    severity: str       # "LOW", "MEDIUM", "HIGH"
    confidence: str     # "LOW", "MEDIUM", "HIGH"
    message: str


class SecurityScanResult(NamedTuple):
    success: bool           # True if no findings
    findings: list[SecurityFinding]
    stdout: str
    stderr: str
    return_code: int


def _parse_bandit_json(output: str) -> list[SecurityFinding]:
    """Parse bandit JSON output into structured findings."""
    if not output.strip():
        return []

    try:
        data = json.loads(output)
    except json.JSONDecodeError:
        return []

    findings: list[SecurityFinding] = []
    for result in data.get("results", []):
        findings.append(
            SecurityFinding(
                file=result.get("filename", ""),
                line=result.get("line_number", 0),
                test_id=result.get("test_id", ""),
                test_name=result.get("test_name", ""),
                severity=result.get("issue_severity", "UNKNOWN"),
                confidence=result.get("issue_confidence", "UNKNOWN"),
                message=result.get("issue_text", ""),
            )
        )
    return findings


def run_security_scan(
    paths: list[str] | None = None,
    *,
    severity: str = "medium",
) -> SecurityScanResult:
    """Run bandit on the specified paths or the entire legion package.

    Args:
        paths: Specific files or directories to scan. Defaults to the
               legion package directory.
        severity: Minimum severity level to report ("low", "medium", "high").

    Returns:
        Structured result with parsed findings and raw output.
    """
    targets = paths or [str(PACKAGE_ROOT)]

    cmd = [
        sys.executable, "-m", "bandit",
        "-r", *targets,
        "-f", "json",
        "--severity-level", severity.lower(),
    ]

    result = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        cwd=str(PROJECT_ROOT),
    )

    findings = _parse_bandit_json(result.stdout)

    return SecurityScanResult(
        success=len(findings) == 0,
        findings=findings,
        stdout=result.stdout,
        stderr=result.stderr,
        return_code=result.returncode,
    )


def format_security_findings(result: SecurityScanResult) -> str:
    """Format security scan results into a human-readable report."""
    if result.success:
        return "No security findings."

    lines = ["\nSecurity findings:\n"]

    for f in sorted(result.findings, key=lambda x: (x.severity, x.file, x.line)):
        lines.append(
            f"  {f.file}:{f.line}  [{f.severity}/{f.confidence}] "
            f"{f.test_id} ({f.test_name}): {f.message}"
        )

    lines.append(f"\n{len(result.findings)} finding(s).")
    lines.append(
        "Suppress false positives with '# nosec' inline comments "
        "or add rules to [tool.bandit] skips in pyproject.toml."
    )

    return "\n".join(lines)

"""Dependency vulnerability scanning via pip-audit.

Invokes pip-audit programmatically and returns structured results.
Advisory only — requires network access to query the OSV database.
"""

from __future__ import annotations

import json
import subprocess
import sys
from typing import NamedTuple

from legion.internal.architecture.dependency_check import PACKAGE_ROOT

PROJECT_ROOT = PACKAGE_ROOT.parent


class VulnerablePackage(NamedTuple):
    name: str
    installed_version: str
    vulnerability_id: str   # CVE or GHSA ID
    fix_versions: str       # comma-separated fix versions
    description: str


class VulnScanResult(NamedTuple):
    success: bool               # True if no vulnerabilities found
    vulnerabilities: list[VulnerablePackage]
    stdout: str
    stderr: str
    return_code: int


def _parse_pip_audit_json(output: str) -> list[VulnerablePackage]:
    """Parse pip-audit JSON output into structured results."""
    if not output.strip():
        return []

    try:
        data = json.loads(output)
    except json.JSONDecodeError:
        return []

    results: list[VulnerablePackage] = []
    for dep in data.get("dependencies", []):
        for vuln in dep.get("vulns", []):
            results.append(
                VulnerablePackage(
                    name=dep.get("name", ""),
                    installed_version=dep.get("version", ""),
                    vulnerability_id=vuln.get("id", ""),
                    fix_versions=", ".join(vuln.get("fix_versions", [])),
                    description=vuln.get("description", ""),
                )
            )
    return results


def run_vuln_scan() -> VulnScanResult:
    """Run pip-audit against installed packages.

    Returns:
        Structured result with parsed vulnerabilities and raw output.
    """
    cmd = [
        sys.executable, "-m", "pip_audit",
        "--format", "json",
        "--desc",
    ]

    result = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        cwd=str(PROJECT_ROOT),
    )

    vulns = _parse_pip_audit_json(result.stdout)

    return VulnScanResult(
        success=result.returncode == 0 and len(vulns) == 0,
        vulnerabilities=vulns,
        stdout=result.stdout,
        stderr=result.stderr,
        return_code=result.returncode,
    )


def format_vuln_scan(result: VulnScanResult) -> str:
    """Format vulnerability scan results into a human-readable report."""
    if result.success:
        return "No known vulnerabilities found."

    lines = ["\nVulnerable dependencies found:\n"]

    for v in sorted(result.vulnerabilities, key=lambda x: x.name):
        fix_info = f"fix: {v.fix_versions}" if v.fix_versions else "no fix available"
        lines.append(
            f"  {v.name}=={v.installed_version}  "
            f"{v.vulnerability_id} ({fix_info})"
        )
        if v.description:
            # Truncate long descriptions
            desc = v.description[:120] + "..." if len(v.description) > 120 else v.description
            lines.append(f"    {desc}")

    lines.append(f"\n{len(result.vulnerabilities)} vulnerability(ies) found.")
    lines.append("Update affected packages or pin to fixed versions.")

    return "\n".join(lines)

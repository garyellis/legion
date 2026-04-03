# ADR-0004: Add pip-audit for Dependency Vulnerability Scanning

**Status**: ACCEPTED
**Date**: 2026-04-03
**Author**: garyellis

## Context

Legion depends on ~20 external packages (FastAPI, SQLAlchemy, Paramiko, Slack Bolt, etc.). Any of these could receive a CVE disclosure at any time. Without automated vulnerability scanning, the project relies on manual monitoring of security advisories — a process that doesn't scale with the number of dependencies or the pace of AI agent contributions.

## Decision

Add `pip-audit` as a dev dependency for dependency vulnerability scanning, exposed via `legion-cli architecture audit`. Advisory only — not a CI gate or pre-commit hook since it requires network access to query the OSV database.

## Dependency Details

| Field | Value |
|:------|:------:|
| Package | `pip-audit` |
| Version | `>=2.7,<3` |
| License | Apache-2.0 |
| PyPI downloads/month | ~2M |
| Maintainers | PyPA (Python Packaging Authority) |
| Transitive deps | ~5 (packaging, pip-api, etc.) |
| Last release | 2025 |
| Known CVEs | None |

## Alternatives Considered

1. **safety** — Was the standard tool, but Safety CLI 3.x requires an API key for full database access. The free tier has delayed vulnerability updates. Commercial model is a poor fit for an open dev dependency.
2. **osv-scanner** — Google's OSV scanner. Go binary, not pip-installable. Doesn't fit the subprocess-wrapper pattern. More suited for CI than developer tooling.
3. **Manual GitHub Dependabot** — GitHub-specific, doesn't integrate with the CLI harness, and requires the repo to be hosted on GitHub.

## Why a Dev Dependency Instead of CI-Only?

While `pip-audit` requires network access (making it unsuitable for pre-commit hooks), exposing it as a CLI command (`legion-cli architecture audit`) gives AI agents and developers on-demand vulnerability checking during development. A developer adding or upgrading a dependency can immediately verify it's clean *before* committing. CI should also run `pip-audit` as a gate — but the local CLI command enables proactive checking rather than reactive CI failures.

## Consequences

- Developers and AI agents can check for known vulnerabilities via `legion-cli architecture audit`.
- Advisory only — requires network access, not suitable for pre-commit hooks.
- Uses the OSV database (same as GitHub Advisory DB) — comprehensive coverage.
- Dev dependency only — no impact on production runtime.

## References

- https://github.com/pypa/pip-audit
- https://pypi.org/project/pip-audit/

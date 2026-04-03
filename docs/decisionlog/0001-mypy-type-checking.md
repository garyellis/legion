# ADR-0001: Add mypy for Static Type Checking

**Status**: ACCEPTED
**Date**: 2026-04-03
**Author**: garyellis

## Context

Legion enforces architectural constraints via static import analysis (`legion-cli architecture check`). However, type errors — wrong argument types, missing attributes, incompatible return types — are only caught at runtime. Adding static type checking as a pre-commit gate lets AI agents and developers verify correctness before committing, catching a class of bugs that import analysis cannot.

## Decision

Add `mypy` as a dev dependency for static type checking, exposed via `legion-cli architecture typecheck`. The implementation lives in `legion/internal/architecture/type_check.py` alongside the existing dependency direction checker.

## Dependency Details

| Field | Value |
|:------|:------|
| Package | `mypy` |
| Version | `>=1.20,<2` |
| License | MIT |
| PyPI downloads/month | ~40M |
| Maintainers | 5+ active (Python core team members) |
| Transitive deps | 3 (`mypy-extensions`, `typing-extensions`, `tomli` on <3.11) |
| Last release | 2025 |
| Known CVEs | None |

## Alternatives Considered

1. **pyright** — Faster, but requires Node.js runtime. Adding a non-Python runtime dependency is a larger burden than a pure-Python tool.
2. **pytype (Google)** — Less mainstream, fewer maintainers, slower release cadence.
3. **stdlib only** — Python has no built-in type checker. `typing` module provides annotations but no verification.

## Consequences

- AI agents can self-check type correctness before committing via `legion-cli architecture typecheck`.
- Catches type mismatches, missing attributes, and incompatible signatures at analysis time.
- Dev dependency only — no impact on production runtime or deployment.
- Adds ~3 transitive dependencies to the dev environment.
- mypy configuration lives in `pyproject.toml` under `[tool.mypy]`.

## References

- https://mypy-lang.org/
- https://mypy.readthedocs.io/en/stable/

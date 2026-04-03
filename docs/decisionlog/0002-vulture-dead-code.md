# ADR-0002: Add vulture for Dead Code Detection

**Status**: ACCEPTED
**Date**: 2026-04-03
**Author**: garyellis

## Context

As the Legion codebase grows with contributions from multiple AI agents and developers, unused functions, classes, imports, and variables accumulate. Dead code increases maintenance burden, confuses contributors, and can mask real bugs. Adding automated dead code detection as an advisory check lets agents and developers identify cleanup opportunities before the codebase diverges from its intended structure.

## Decision

Add `vulture` as a dev dependency for dead code detection, exposed via `legion-cli architecture deadcode`. The implementation lives in `legion/internal/architecture/dead_code.py` alongside the existing architecture checks. A whitelist file (`vulture_whitelist.py`) at the project root suppresses known false positives.

## Dependency Details

| Field | Value |
|:------|:------:|
| Package | `vulture` |
| Version | `>=2.14` |
| License | MIT |
| PyPI downloads/month | ~5M |
| Maintainers | 2 active |
| Transitive deps | 0 |
| Last release | 2025 |
| Known CVEs | None |

## Alternatives Considered

1. **Custom AST analysis** — Would require building definition-tracking, cross-module reference resolution, and handling dynamic attribute access. Weeks of work to approach vulture's maturity.
2. **pyflakes/flake8** — Detects unused imports within single files but not unused functions or classes across the codebase.
3. **pylint** — Full linter with dead code detection, but heavyweight (~20 transitive deps) and slower. Vulture is purpose-built and minimal.

## Consequences

- AI agents can identify dead code via `legion-cli architecture deadcode`.
- Advisory only — not a CI gate. Dead code may be intentional during active development.
- Whitelist file handles false positives (dynamically called functions, Pydantic model_config, etc.).
- Dev dependency only — no impact on production runtime.
- Zero transitive dependencies.

## References

- https://github.com/jendrikseipp/vulture
- https://pypi.org/project/vulture/

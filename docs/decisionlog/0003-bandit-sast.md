# ADR-0003: Add bandit for Static Application Security Testing

**Status**: ACCEPTED
**Date**: 2026-04-03
**Author**: garyellis

## Context

Legion is an SRE agent fleet system where AI agents contribute code alongside developers. The codebase handles SSH connections, subprocess execution, API keys, and infrastructure operations. While the project currently has no security vulnerabilities (no eval/exec/pickle, SQLAlchemy ORM throughout, SecretStr for credentials), there is no automated SAST to catch regressions. A custom `dangerous_calls.py` check handles the most critical patterns (eval, exec, pickle, os.system), but broader security analysis — hardcoded passwords, weak crypto, insecure temp files, HTTP without TLS — requires a mature tool.

## Decision

Add `bandit` as a dev dependency for static application security testing, exposed via `legion-cli architecture security`. Advisory by default with a `--gate` flag for CI enforcement. Noisy rules (B101 assert_used, B404 import_subprocess) are skipped via `[tool.bandit]` in `pyproject.toml` since our custom `dangerous_calls.py` already covers subprocess restrictions with layer-aware enforcement.

## Dependency Details

| Field | Value |
|:------|:------:|
| Package | `bandit` |
| Version | `>=1.8,<2` |
| License | Apache-2.0 |
| PyPI downloads/month | ~8M |
| Maintainers | PyCQA team (3+ active) |
| Transitive deps | 3 (PyYAML, stevedore, rich) |
| Last release | 2025 |
| Known CVEs | None |

## Alternatives Considered

1. **ruff `S` ruleset** — Reimplements bandit rules in Rust. Faster, but ruff is a Rust binary, not pip-installable in the same subprocess-wrapper pattern. Would require a separate tool management approach.
2. **semgrep** — Powerful semantic analysis, but heavyweight (separate binary, network calls for rule updates, designed for polyglot codebases). Overkill for a single-language project.
3. **Custom AST only** — We already have `dangerous_calls.py` for the most critical patterns. Bandit adds breadth (100+ rules) without duplicating the layer-aware enforcement.

## Why Local (Pre-commit) Instead of CI-Only?

Legion is developed by multiple AI agents operating autonomously. CI catches problems *after* code is pushed — but by then the damage is done: secrets may be exposed in git history, vulnerable patterns are committed, and remediation requires force-pushes or revert commits. Running security checks locally (via pre-commit hooks and CLI commands) shifts detection left:

1. **AI agents get immediate feedback** during development, not after a CI round-trip.
2. **Secrets never reach the remote** — a CI-only check catches leaked credentials *after* they're in git history (already compromised).
3. **Faster iteration** — local checks run in seconds vs. minutes for CI pipelines.
4. **CI is the backstop, not the frontline** — the `--gate` flag allows CI to enforce what pre-commit advises.

## Consequences

- AI agents get broad security scanning via `legion-cli architecture security`.
- Advisory by default — `--gate` flag available for CI pipelines.
- B101 (assert) and B404 (subprocess import) skipped to reduce noise.
- Dev dependency only — no impact on production runtime.
- 3 transitive dependencies, all well-maintained.

## References

- https://github.com/PyCQA/bandit
- https://bandit.readthedocs.io/

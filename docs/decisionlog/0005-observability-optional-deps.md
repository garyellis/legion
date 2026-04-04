# ADR-0005: Optional Prometheus Metrics Dependency

**Status**: ACCEPTED
**Date**: 2026-04-04
**Author**: Codex

## Context

Legion needs Prometheus-compatible metrics exposure for API and service observability, but the base runtime must remain usable without a metrics SDK. The project rules require optional dependencies to be justified, pinned, and documented with supply-chain considerations.

## Decision

Add `prometheus-client>=0.20,<1` as an optional `metrics` extra and implement a plumbing-level facade that degrades to silent no-op metric objects when the package is absent. This keeps observability opt-in, avoids background initialization, and preserves the architectural rule that plumbing imports no Legion modules.

## Dependency Details (if adding a package)

| Field | Value |
|:------|:------|
| Package | `prometheus-client` |
| Version | `>=0.20,<1` |
| License | Apache-2.0 |
| PyPI downloads/month | ~200M+ |
| Maintainers | Prometheus project maintainers |
| Transitive deps | 0 |
| Last release | 2024-11-15 |
| Known CVEs | None known at decision time |

## Alternatives Considered

1. **Require Prometheus in core dependencies** — rejected because it violates the zero-cost disabled requirement and forces telemetry code into all installs.
2. **Build a custom exposition renderer with no dependency** — rejected because it recreates mature Prometheus behavior and increases maintenance burden.
3. **stdlib approach** — insufficient because the standard library does not provide Prometheus metric types or exposition helpers.

## Consequences

- Legion can expose `/metrics` when explicitly installed with the `metrics` extra.
- Base installs remain free of Prometheus runtime cost and import failures.
- Observability code must stay behind the plumbing facade to avoid direct optional-dependency spread.

## References

- `docs/decisionlog/0000-template.md`
- https://pypi.org/project/prometheus-client/
- https://prometheus.io/docs/instrumenting/exposition_formats/

# ADR-0006: Move httpx from Dev to Runtime Dependency

**Status**: ACCEPTED
**Date**: 2026-04-04
**Author**: garyellis

## Context

The Fleet CLI uses `FleetAPIClient` (in `legion/core/fleet_api/client.py`) to communicate with the Legion control plane API over HTTP. This client is built on `httpx`, which was previously listed only as a dev dependency. Since the CLI is a runtime surface that end users invoke, `httpx` must be a project (runtime) dependency.

## Decision

Move `httpx` from `[dependency-groups] dev` to `[project] dependencies` with a compatible-release pin of `>=0.27,<1`.

## Dependency Details

| Field | Value |
|:------|:------:|
| Package | `httpx` |
| Version | `>=0.27,<1` |
| License | BSD-3-Clause |
| PyPI downloads/month | ~30M |
| Maintainers | encode (Tom Christie) |
| Transitive deps | ~5 (httpcore, certifi, idna, sniffio, anyio) |
| Last release | 2025 |
| Known CVEs | None |

## Alternatives Considered

1. **urllib3 / requests** — The de facto standard, but `httpx` provides a cleaner typed API, context manager support, and async capability if needed later. Already in use in the codebase.
2. **aiohttp** — Already a project dependency, but async-only. The Fleet CLI client is synchronous, making `aiohttp` awkward without an event loop wrapper.
3. **stdlib urllib.request** — No connection pooling, no timeout defaults, verbose error handling. Not practical for a typed HTTP client.

## Consequences

- `httpx` is now available at runtime for any surface or core module that needs synchronous HTTP.
- Adds ~5 transitive dependencies to the runtime footprint (most already pulled in by other deps).
- Version pin `>=0.27,<1` guards against breaking changes from a future 1.0 release.
- Removed from dev dependencies to avoid duplication.

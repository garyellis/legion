# ADR-0015: Kubernetes Python Client for Core Tools

**Status**: ACCEPTED
**Date**: 2026-04-04
**Author**: developer

## Context

Sprint B1 introduces core Kubernetes tools in `core/kubernetes/` — the first real plugins for the agent fleet system. These tools inspect pod status, fetch logs, describe resources, and list events. The agent process runs alongside or near the cluster it monitors, with access to a local kubeconfig or in-cluster service account.

Legion is an SRE agent platform. Kubernetes inspection is a core capability, not an optional add-on. Every production deployment will have agents monitoring Kubernetes clusters. Making the dependency optional would add ImportError guards throughout `core/kubernetes/`, complicate testing, and create a false impression that Legion works without it.

## Decision

Add `kubernetes` as a **required** runtime dependency.

The official Kubernetes Python client handles kubeconfig parsing, multiple auth providers (exec-based, token, certificate), token refresh, in-cluster config detection, and the full API surface. These are all things an SRE tool encounters in production across AKS, EKS, GKE, on-prem, kind, and k3s environments.

The dependency is heavier than alternatives (~15 transitive deps), but Legion is an SRE platform — operators already have the kubernetes ecosystem installed. The weight is justified by correctness and compatibility guarantees. Making it required means `core/kubernetes/` tools are always importable with no guards, simplifying both code and testing.

Tools in `core/kubernetes/` use the sync client. B2's agent runner can wrap sync calls in `asyncio.to_thread()` if needed.

## Dependency Details

| Field | Value |
|:------|:------:|
| Package | `kubernetes` |
| Version | `>=29.0,<32` |
| License | Apache-2.0 |
| PyPI downloads/month | ~15M |
| Maintainers | Kubernetes Python SIG (5+ active) |
| Transitive deps | ~15 (urllib3, requests, google-auth, oauthlib, certifi, pyyaml, python-dateutil, six) |
| Last release | 2025 |
| Known CVEs | None current (generally patched within days) |

## Alternatives Considered

1. **`kr8s`** — Lightweight, modern async Kubernetes client (~5 transitive deps, Pythonic API). Rejected: newer library (since 2023), less battle-tested in production. Doesn't handle all auth provider edge cases (exec-based auth, GKE/AKS workload identity). For an SRE platform that must work across diverse cluster configurations, the official client's broader compatibility is worth the weight.

2. **`lightkube`** — Lightweight, typed Kubernetes client with async support (~8 transitive deps). Rejected: smaller community, less ecosystem coverage for auth providers. For an SRE tool where production issues need fast upstream fixes, community size matters.

3. **`httpx` + raw K8s API** — Use httpx (already a dependency) to call the Kubernetes API directly. Zero new deps. Rejected: kubeconfig parsing, auth token refresh, certificate handling, exec-based auth providers, and in-cluster config detection all require significant implementation effort. The official client exists because this is hard.

4. **Optional dependency (`legion[kubernetes]`)** — Make kubernetes an extras group. Rejected by operator decision: Legion is a Kubernetes SRE platform. Making the core capability optional adds ImportError guards, dual code paths, and test complexity. Required is the right default.

## Consequences

- `core/kubernetes/` tools use the full K8s client API surface without import guards.
- Every `uv pip install legion` includes the kubernetes client and its ~15 transitive deps.
- Tests mock the kubernetes client — no real cluster needed in CI.
- Kubeconfig handling is the kubernetes client's responsibility, not Legion's.
- Version pin `>=29.0,<32` covers K8s 1.29-1.31 API compatibility.
- The initial implementation uses a simple process-local `CoreV1Api` cache and centralized API error translation to keep repeated tool calls deterministic and bounded.
- Future: if dependency weight becomes a concern for CLI-only installs, we can revisit with an optional split. That's a packaging concern, not an architecture concern.

## References

- kubernetes-client/python: https://github.com/kubernetes-client/python
- ADR-0006: httpx runtime dependency (similar evaluation pattern)
- Sprint B1 build phases: `docs/sre/planning/build-phases.md`
- Decision 27 (plugin system): `docs/sre/planning/decisions.md`

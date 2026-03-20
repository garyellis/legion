# SRE Agent Fleet — Build Proposal

This directory contains the implementation plan for the distributed SRE agent fleet described in `SLACK_SRE_ARCHITECTURE.md`. The plan maps that vision onto the existing `legion` layered architecture.

## Documents

| Document | Purpose |
|:---------|:--------|
| [Architecture Fit](./architecture-fit.md) | How the SRE fleet maps to existing layers, what's ready, what's missing |
| [Domain Model](./domain-model.md) | New entities, relationships, and where they live |
| [Build Phases](./build-phases.md) | Ordered implementation plan with deliverables per phase |
| [Decisions](./decisions.md) | Key architectural decisions and their rationale |

## Guiding Principles

1. **Build domain and services first, surfaces last.** Every phase is testable before any surface exists.
2. **The existing incident bot keeps working throughout.** Nothing breaks while the fleet is being built.
3. **Each phase is independently demoable.** Phase 1 has pytest. Phase 2 has curl. Phase 3 has CLI. You never need the full distributed system to make progress.
4. **No new architectural concepts.** The layer diagram, dependency rules, config system, repository pattern, and contract tests all carry forward unchanged.

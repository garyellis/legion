# Codex Supplemental Instructions

## Worktree Coordination

This project uses git worktrees for parallel development. Multiple agents may work simultaneously on independent features.

## Feature Intake Default

For non-trivial feature requests, use the `legion-dev feature create` workflow by default before implementation or delegation.

Create a feature handoff brief when any of these are true:

- More than one subsystem, surface, or layer is likely to change.
- The request is underspecified and behavior would otherwise be inferred.
- There are meaningful implementation tradeoffs.
- The work is likely to be handed to a sub-agent or a fresh session.
- Acceptance criteria or verification steps are not already explicit.
- The change affects user-visible workflows, persistence, config, or public interfaces.

Skip the brief only when the task is clearly small and local. If skipping, warn the operator briefly that skipping the feature gate increases the risk of ambiguity, architectural drift, and weaker handoff quality, then proceed if they still want to skip it.

When using the feature brief, treat it as a handoff contract:

- Fill in repo-grounded context, constraints, target files, risks, verification commands, and done condition.
- Use it as the source of truth for sub-agent delegation or session handoff.
- Prefer the smallest implementation that satisfies the brief cleanly.

### Rules

- Each worktree works on an independent feature branch.
- Never modify files outside your assigned scope without checking with the operator.
- Run `uv run pytest tests/test_dependency_direction.py` before committing to verify architecture.
- Prefer small, focused commits with clear messages.

### Coordination

- **Domain models are shared state**: If your task adds a new domain entity, coordinate with other worktrees. Two agents adding to `domain/` simultaneously can conflict.
- **Services depend on domain**: If you add a domain model, the service that uses it should be in the same worktree.
- **Surfaces are independent**: CLI, Slack, API work can happen in separate worktrees safely.
- **Core modules are independent**: `core/kubernetes/` and `core/database/` can be developed in parallel.

### Safe Parallelization

| Worktree A | Worktree B | Worktree C |
|:-----------|:-----------|:-----------|
| core/kubernetes/ + agents/personas/ | api/routes/ + api/schemas | core/database/ + services/ |
| domain/job.py + services/dispatch_service.py | cli/commands/ + cli/views/ | slack/listeners/ + slack/views/ |

Avoid: Two worktrees modifying the same service or domain file.

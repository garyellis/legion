# Codex Supplemental Instructions

## Worktree Coordination

This project uses git worktrees for parallel development. Multiple agents may work simultaneously on independent features.

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

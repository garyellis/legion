# ADR-0011: Feature brief generator in legion-dev

**Status**: PROPOSED
**Date**: 2026-04-04
**Author**: developer

## Context

Feature development is inconsistent when work starts from a loose prompt. Agents and humans both have to reconstruct the problem, intended behavior, placement rules, and testing expectations from scattered project docs. That ambiguity causes predictable failures: wrong layer placement, missing tests, unclear scope, and implementation work that drifts away from the original need.

Legion already uses `legion-dev` as a development harness to constrain code generation and review workflows. ADR-0009 established that harness for scaffolding and review because reducing the agent's decision space improves accuracy and lowers iteration cost. The same problem exists one step earlier in the workflow: before code is written, there is no consistent feature brief artifact that captures the problem, constraints, intended changes, and acceptance criteria in a format that is easy to hand to a new session or delegated implementation agent.

The result is wasted time and tokens. Review cycles become a cleanup step for missing context instead of a validation step for deliberate implementation.

## Decision

Add a new `feature` command group to the `legion-dev` developer harness with an initial command: `legion-dev feature create <title>`.

The command generates a deterministic markdown requirements gate in `docs/features/<slug>.md`. Generated feature briefs are local working artifacts, not decision records, so `docs/features/*.md` is gitignored while `docs/features/.gitkeep` keeps the workspace directory present in the repo. The template is static in v1. It does not call an AI agent, inspect the repo, or infer implementation details. Its job is to make the author fill in the missing context explicitly before implementation starts, then hand that context to a new session or delegated agent without losing accuracy.

The implementation follows the existing harness pattern from ADR-0009:

- `legion/internal/feature.py` contains pure generation logic: slug creation, path generation, and template assembly.
- `legion/cli_dev/commands/feature.py` is a thin CLI adapter that resolves project paths, supports `--dry-run`, refuses overwrites, and writes the generated file.
- The template includes a requirements gate plus sections for problem, desired outcome, non-goals, workflow, current repo context, constraints, architecture placement, interfaces, file ownership, failure modes, acceptance criteria, verification, done condition, open questions, and session handoff instructions.

No new dependency is added. This is stdlib-only markdown generation.

## Alternatives Considered

1. **Freeform prompt writing only** — rejected because that is the current failure mode. It keeps all structure in the author's head and produces inconsistent briefs across people and agents.
2. **Add feature briefs under `legion-dev scaffold`** — rejected because scaffolding in Legion currently means code artifact generation. A feature brief is a planning and handoff artifact, not source-code boilerplate.
3. **Generate an AI-enriched or repo-aware brief in v1** — rejected because it adds complexity before the team validates the basic workflow. A static template is easier to trust, test, and evolve.

## Consequences

- Feature work gets a standard pre-implementation artifact that captures scope, constraints, and validation steps in one place without polluting the repo with feature-specific markdown.
- The artifact is optimized for session-to-session or agent-to-agent handoff, not just for human note taking.
- `legion-dev` constrains agent work earlier in the lifecycle, not just at code-generation or review time.
- The team must maintain one more template as project conventions evolve.
- The command only helps if it becomes part of the normal workflow before implementation starts.
- A later revision can add optional repo-derived guidance if the static template proves useful without becoming noisy.

## References

- ADR-0009: Developer CLI scaffolding and review commands
- `legion/cli_dev/commands/scaffold.py`
- `docs/decisionlog/0000-template.md`

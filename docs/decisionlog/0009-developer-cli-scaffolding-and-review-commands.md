# ADR-0009: Developer CLI scaffolding and review commands

**Status**: ACCEPTED
**Date**: 2026-04-04
**Author**: gary

## Context

AI coding agents (Claude, Codex) working on this codebase must follow strict architectural rules: layered imports, correct file placement, naming conventions, test file structure. When agents create new modules from scratch, they frequently guess wrong — placing files in the wrong layer, using incorrect import paths, or missing boilerplate like `from __future__ import annotations`. Each mistake requires a review-fix cycle that costs time and tokens.

Similarly, code review against project rules is a manual step that agents either skip or perform inconsistently. The rules live in CLAUDE.md but there's no structured way to invoke a review pass from the CLI.

## Decision

Add three command groups to the `legion-dev` developer harness:

### `legion-dev scaffold` — Architecture-aware code generation

Generates boilerplate files that conform to the layered architecture by construction:
- `scaffold core <name>` — `core/<name>/` with `__init__.py`, `client.py`, `models.py`, test stub
- `scaffold service <name>` — `services/<name>_service.py`, `<name>_repository.py`, test stub
- `scaffold domain <name>` — `domain/<name>.py`, test stub
- `scaffold command <surface> <group> <name>` — surface command with `@register_command` wiring

All generated Python source files include `from __future__ import annotations` and correct imports for their layer (the sole exception is `__init__.py`, which is generated empty). Matching test files follow the project's naming convention. `--dry-run` flag shows what would be created without writing.

The key insight: scaffolding constrains the AI agent's decision space. Instead of "understand the architecture and create correct files," the task becomes "run a command." This eliminates an entire class of architectural violations at the point of creation rather than catching them after the fact.

### `legion-dev review` — Structured code review via AI agent

Sends the current diff + CLAUDE.md rules to an AI agent CLI, requesting a structured PASS/FAIL checklist:
- `review diff` — reviews working tree changes (supports `--staged`, `--base`)
- `review file <path>` — reviews a specific file
- `review pr` — reviews all changes on the branch vs base

Supports `--agent claude|codex` (default: claude). Agent output is captured and rendered as Rich Markdown with syntax highlighting. A Rich spinner displays while waiting for the agent response.

No new Python dependencies — uses `subprocess` to call the agent CLI.

### `legion-dev adr` — ADR lifecycle management

- `adr create <title>` — auto-increments ID, slugifies title, generates template (`--dependency` flag for package ADRs)
- `adr list` — Rich table of existing ADRs with parsed status
- `adr next-id` — prints next available ID for scripting
- `adr show <id>` — renders an ADR locally with Rich: metadata panel, sections as formatted Markdown
- `adr overview <id>` — renders metadata and related ADRs locally, then sends the ADR to an AI agent (`--agent claude|codex`) for drift analysis against the codebase (dependency versions, architectural claims, status accuracy)

Removes friction from a required process step. AI instructions (CLAUDE.md, AGENTS.md, CONTRIBUTING.md) updated to reference this command.

### Supporting infrastructure

**`legion/plumbing/subprocess.py`** — thin subprocess helpers (`run_capture`, `run_capture_text`, `run_passthrough`, `git_diff`, `git_log`, `git_root`, `find_on_path`). `run_capture_text` detaches stdin (`/dev/null`) so child processes cannot block on interactive prompts when output is captured. Lives in plumbing so surfaces can shell out without importing `subprocess` directly (restricted by dangerous-calls check).

**`legion/plumbing/agents.py`** — agent backend registry using the strategy pattern. An `AgentBackend` dataclass maps agent names to their binary and argument format. `AGENT_BACKENDS` dict holds registered agents (currently `claude` and `codex`). Provides `run_agent_prompt` (passthrough to terminal) and `run_agent_capture` (capture stdout for Rich rendering). Adding a new agent backend = one entry in the dict.

**`legion/internal/{scaffold,adr,review}.py`** — pure business logic extracted from `cli_dev/commands/`. These modules contain templates, prompt assembly, path generation, ADR parsing, and slug generation — all stdlib-only with no legion imports, following the `internal/` layer rule. The surface commands in `cli_dev/commands/` are thin adapters that import from these modules.

## Alternatives Considered

1. **Document-only approach (status quo)** — rely on CLAUDE.md instructions for agents to create correct files. Rejected because agents still guess wrong frequently, especially for file placement and naming.
2. **Cookiecutter/copier templates** — external templating tools. Rejected because they add a dependency for something achievable with 50 lines of pathlib code.
3. **Pre-commit hook validation only** — catch violations after creation. Keeps the scaffold approach but this is complementary, not a replacement. Catching errors at creation time is strictly better than catching them after.

## Consequences

- AI agents can create architecturally-correct modules with a single command, reducing review iterations
- The scaffold command encodes architectural conventions as executable code rather than prose
- Review and ADR overview commands standardize AI-assisted analysis across human and AI workflows, with pluggable agent backends (`--agent claude|codex`)
- ADR command removes friction from a required governance step; `adr show` provides local rendering, `adr overview` adds AI-powered drift detection
- Agent backend registry (`plumbing/agents.py`) makes adding new AI CLIs a one-line change
- Pure logic in `internal/` is reusable by other surfaces or scripts without CLI dependencies
- All three commands are stdlib-only (no new dependencies) — subprocess helpers use only `subprocess`, `shutil`, `pathlib`
- Templates must be updated when architectural conventions change (low maintenance — conventions are stable)

## References

- ADR-0008: Command registry moved to plumbing (enabling `cli_dev/` surface)
- CLAUDE.md: Architecture rules and decision tree
- CONTRIBUTING.md: Development workflow with quality gates

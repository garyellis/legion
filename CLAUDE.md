# CLAUDE.md — Legion Project Guidelines

## Project Overview

Legion is an SRE and Platform Engineering agent fleet system. A control plane (FastAPI + Slack Bolt + PostgreSQL + Redis) orchestrates data-plane agents that run LangGraph ReAct loops with local infrastructure tools.

**Runtime**: Python 3.13+, uv for package management, pydantic for data models, SQLAlchemy for persistence, pytest for testing.

## Architecture: Layer Model

Imports flow **downward only**. No exceptions. Enforced by `legion-dev architecture check` and `tests/test_dependency_direction.py`.

```
plumbing/    → imports NOTHING from legion (stdlib + external libs only)
internal/    → imports NOTHING from legion (dev tooling: architecture checks, linting)
core/        → imports plumbing/ only
domain/      → imports plumbing/, core/ (models only, never logic)
services/    → imports plumbing/, core/, domain/
agents/      → imports plumbing/, core/, domain/, services/
surfaces     → import from any layer below, never from each other
```

Surfaces: `cli/`, `cli_dev/`, `slack/`, `api/`, `tui/`. Each is an independent entry point. `cli_dev/` is the developer harness (`legion-dev` command) — not shipped to end users.

## Do NOT

- NEVER import upward in the layer stack.
- NEVER import between surfaces (cli/ ↛ slack/, api/ ↛ cli/).
- NEVER put LangChain, Rich, Slack SDK, or FastAPI imports in core/.
- NEVER use loose dicts for structured data. Use Pydantic models.
- NEVER put formatting logic in services/. Surfaces format, services return models.
- NEVER put Slack-specific fields (channel_id, message_ts) on domain models.
- NEVER add vendor-specific parsing logic in domain/. Parsers belong at the boundary.
- NEVER skip the architecture test. Run `test_dependency_direction.py` before committing.
- NEVER commit `.env` files, credentials, or secrets.
- NEVER add a dependency without an ADR in `docs/decisionlog/`. See Security section.

## Security and Dependencies

- **No unnecessary dependencies.** Every new dependency increases attack surface.
- **Adding a dependency requires an ADR** in `docs/decisionlog/` documenting: why it's needed, what alternatives were considered, license, maintenance status, and supply chain risk.
- **Pin versions** in `pyproject.toml`. Use exact or compatible-release pins (`>=X.Y,<X+1`), not unbounded.
- **Audit before adding**: Check package age, maintainer count, download stats, known CVEs, and transitive dependency count.
- **Prefer stdlib**: If the standard library can do it, don't add a package.
- **Credentials never in code or config files**: Use environment variables or secret managers. Never log secrets.
- **Treat all external input as untrusted**: Alert messages, tool output, API payloads, Slack events.

### ADR Format for Dependencies

Run `legion-dev adr create "<title>"` to generate the next ADR with the correct ID and template. Add `--dependency` flag when the ADR is for a new package. See `docs/decisionlog/0000-template.md` for the full format reference. Every dependency addition or removal gets an ADR.

## Decision Tree: Where Code Goes

```
Utility, config base, or cross-cutting concern?              → plumbing/
Dev tooling, architecture checks, or internal analysis?       → internal/
One API call returning data?                                  → core/<domain>/
Data structure 1:1 with an API response?                      → core/<domain>/models.py
Data structure spans multiple core domains?                   → domain/<concept>.py
Coordinates multiple APIs or applies business rules?          → services/<concept>_service.py
Parses input or formats output for a specific medium?         → surface layer
AI runtime infrastructure?                                    → agents/
```

## Code Conventions

### Data Modeling

- **Pydantic models or dataclasses** for all data structures. No loose dicts.
- **Enums** for state machines and categorical values (e.g., `IncidentStatus`, `JobState`).
- **Small value objects** — prefer typed result objects over ambiguous tuples/dicts.
- **Typed DTOs** at boundaries. Input DTOs for parsing, output DTOs for responses.
- **`from __future__ import annotations`** at top of every module.

### Design Patterns

- **Ports and adapters**: ABC/Protocol for external dependencies, implementation classes for integrations.
- **Constructor injection**: Services receive dependencies via `__init__`, never global state.
- **Callbacks over imports**: Services communicate outward via injected callables, not surface imports.
- **Thin adapters at boundaries**: Surfaces parse input → call logic → format output.
- **Strategy objects over conditionals**: When conditionals multiply, replace with mappings or strategy pattern.
- **Pass-throughs skip services**: If a command wraps one core function, call core/ directly from the surface.

### Error Handling

- **Exception hierarchy**: `LegionError` (plumbing/) → `ServiceError` (services/) → specific errors.
- **`retryable` hint** on exceptions for callers.
- **Meaningful error types**: `DispatchError`, `AgentNotFoundError`, `SessionError` — not generic `Exception`.
- **Structured logging at boundaries**: Log entry/exit at service boundaries with context via `logging.getLogger(__name__)`.
- **Explicit retries/timeouts**: Never silent retry loops. Configurable, with safe defaults.
- **Safe defaults**: Deny by default for destructive operations, timeout to deny for approvals.

## Testing

- **Encode behavior, not implementation**. Tests should survive refactoring.
- **Every layer testable in isolation**: core/ needs no mocks, services/ need only interface mocks, agents/ need tool stubs.
- **Parameterized repo tests**: Both in-memory and SQLite/Postgres implementations pass identical tests.

```bash
uv run pytest                              # all tests
uv run legion-dev architecture check       # architecture check (dev CLI)
uv run pytest tests/test_dependency_direction.py  # architecture check (pytest)
uv run pytest -k "test_domain"             # domain tests only
```

### Test File Naming

```
tests/
├── test_domain_<concept>.py          # Model + state machine tests
├── test_services_<concept>.py        # Service with in-memory repo + stub callbacks
├── test_services_<concept>_repo.py   # Parameterized across repo implementations
├── test_<concept>_integration.py     # End-to-end with in-memory repo
├── test_dependency_direction.py      # Architectural import enforcement
├── test_api_*.py                     # API route tests
└── test_core_*.py                    # Core client tests
```

`tests/test_dependency_direction.py` scans every `.py` file's AST and verifies import direction. New top-level directories must be added to `LAYER_ALLOWED_IMPORTS` or `SURFACES` in `legion/internal/architecture/dependency_check.py`.

## Key Files

| File | Purpose |
|:-----|:--------|
| `pyproject.toml` | Dependencies, entry points, build config |
| `legion/internal/architecture/` | Dependency direction analysis (source of truth for layer rules) |
| `tests/test_dependency_direction.py` | Architectural enforcement (run before every commit) |
| `legion/plumbing/exceptions.py` | Base exception hierarchy |
| `legion/plumbing/config/base.py` | `LegionConfig` base settings class |
| `legion/plumbing/database.py` | SQLAlchemy `Base` and engine setup |
| `CONTRIBUTING.md` | Full architectural rationale and decision tree |
| `docs/decisionlog/` | ADRs for dependency and architectural decisions |

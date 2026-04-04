# Contributing to Legion

How to work in this codebase without breaking it.

---

## The Architecture in 60 Seconds

Headless core consumed by multiple surfaces. Business logic is written once and exposed through CLI, Slack, HTTP API, and AI agents without duplication.

```
              +--------+--------+--------+----------+
              |  cli/  | slack/ |  api/  | cli_dev/ |   SURFACES
              +---+----+---+----+---+----+----+-----+
                  |    +---+--------+---+
                  |    |   agents/      |       AI
                  |    +-------+--------+
                  +------------+--------+
                  |    +-------+--------+
                  |    |   services/    |       ORCHESTRATION
                  |    +-------+--------+
                  +------------+--------+
                  |    +-------+--------+
                  |    |    domain/     |       ENTITIES
                  |    +-------+--------+
                  +------------+--------+
                       +-------+--------+
                       |     core/      |       FOUNDATION
                       +-------+--------+
                       |   plumbing/    |       INFRASTRUCTURE
                       +----------------+
```

Imports flow downward. Callbacks flow upward. No exceptions.

---

## Layers

| Layer | What lives here | Imports from |
|:------|:----------------|:-------------|
| `plumbing/` | Config, exceptions, database, logging | Nothing from `legion/` |
| `internal/` | Architecture checks, dev tooling | Nothing from `legion/` |
| `core/` | SDK wrappers, infrastructure adapters, colocated models | `plumbing/` only |
| `domain/` | Cross-cutting Pydantic models (Incident, Job, Session) | `plumbing/`, `core/` models |
| `services/` | Stateful coordinators, repositories, scheduling | `plumbing/`, `core/`, `domain/` |
| `agents/` | LLM config, chains, personas | `plumbing/`, `core/`, `domain/`, `services/` |
| Surfaces | Thin entry points: parse input, call logic, format output | Any layer below, never each other |

Models that map 1:1 to an API response stay in `core/`. Models that span multiple core domains go in `domain/`. See `CLAUDE.md` for full rationale.

---

## Where Does My Code Go?

```
Is it one API call that returns data?
  -> core/ function. Surface calls it directly. No service needed.

Does it coordinate multiple APIs or apply business rules?
  -> services/ method. Surface calls the service.

Is the data structure used by more than one core module?
  -> domain/ model.

Is the data structure 1:1 with an API response?
  -> Stays in core/ as a model.

Does it parse input or format output for a specific medium?
  -> Surface layer (cli/, slack/, api/).
```

Not every command needs a service. If a CLI command wraps one core function, call `core/` directly from the surface.

---

## Hard Rules

### Dependency Direction

```
plumbing/  -> imports NOTHING from legion
internal/  -> imports NOTHING from legion
core/      -> imports plumbing/ only
domain/    -> imports plumbing/, core/
services/  -> imports plumbing/, core/, domain/
agents/    -> imports plumbing/, core/, domain/, services/
surfaces   -> import from any layer below, never from each other
```

Enforced by `uv run legion-dev architecture gate` and `tests/test_dependency_direction.py`.

### Core stays framework-free

`core/` never imports LangChain, Rich, Slack SDK, or FastAPI.

### Services communicate via callbacks

Services never import surfaces. Outward communication uses injected callbacks:

```python
# slack/main.py (startup wiring)
incident_service = IncidentService(
    repository=repo,
    on_incident_created=lambda inc: slack_service.create_incident_channel(inc),
)
```

### Dependencies require ADRs

Every new dependency requires a decision record in `docs/decisionlog/`. Run `legion-dev adr create "<title>" --dependency` to generate the next ADR with the correct ID and template. See `docs/decisionlog/0000-template.md` for the full format reference.

### Non-trivial features require a handoff brief

For non-trivial feature requests, create a local feature handoff brief before implementation or delegation:

```bash
uv run legion-dev feature create "<title>"
```

Use `uv run legion-dev feature show "<title>"` to inspect the brief and `uv run legion-dev feature handoff "<title>"` to emit a deterministic handoff prompt for a new session or delegated agent.

Use the brief when any of these are true:

- More than one subsystem, surface, or layer is likely to change
- The request is underspecified and behavior would otherwise be inferred
- There are meaningful implementation tradeoffs
- The work is likely to be handed to a sub-agent or a fresh session
- Acceptance criteria or verification steps are not already explicit
- The change affects user-visible workflows, persistence, config, or public interfaces

Skip the brief only for clearly small, local changes. If skipping, warn the operator that bypassing the feature gate increases the risk of ambiguity, architectural drift, and weaker handoff quality, then proceed only if they still want to skip it.

Generated briefs live in `docs/features/`. The directory is tracked, but generated markdown files are gitignored because they are local working artifacts rather than long-lived repo docs.

---

## Common Mistakes

| Mistake | Do this instead |
|:--------|:----------------|
| Wrapping every command in a service | Surface calls `core/` directly for simple commands |
| Putting API response models in `domain/` | Keep 1:1 API models in `core/` |
| Putting business rules in `core/` | Rules spanning APIs go in `services/` |
| Putting formatting in `services/` | Services return models; surfaces format them |
| `import rich` in `core/` | Rendering belongs in `cli/views/` |
| `from legion.slack import X` in `services/` | Use callback injection |
| Slack-specific fields on domain models | Surface-specific state in `slack/` |

---

## Development Setup

```bash
git clone <repo-url>
cd legion
uv sync --group dev

# Run tests
uv run pytest

# Architecture checks (run before committing)
uv run legion-dev architecture gate            # required gate: layer violations + banned imports + typecheck + circular + dangerous calls + secrets
uv run legion-dev architecture typecheck       # mypy
uv run legion-dev architecture circular        # circular import detection
uv run legion-dev architecture deadcode        # vulture dead code
uv run legion-dev architecture unused-deps     # unused dependency detection
uv run legion-dev architecture dangerous-calls # eval/exec/pickle restrictions
uv run legion-dev architecture security        # bandit SAST
uv run legion-dev architecture audit           # pip-audit CVE scan

# Enable pre-commit hook (runs gate checks automatically)
git config core.hooksPath .githooks
```

### Docker (full stack)

```bash
docker compose up                          # API + PostgreSQL + Redis
docker compose --profile demo up           # ... plus a demo agent
docker compose run --rm api uv run pytest  # run tests against PostgreSQL
docker compose down -v                     # tear down and wipe data
```

### Parallel Development with Worktrees

We use [worktrunk](https://worktrunk.dev/) (`wt`) to manage parallel feature branches in isolated worktrees. Each feature gets its own directory — no stashing, no context switching.

```bash
wt switch -c feature/api-key-auth          # create worktree + branch
wt list                                    # see active worktrees
wt merge main                              # merge current branch to main + cleanup
wt remove                                  # abandon a worktree
```

**Manual development loop** (per feature):

```
1. wt switch -c feature/<name>                  # isolate
2. uv run legion-dev feature create "<title>"    # handoff brief for non-trivial work
3. uv run legion-dev feature handoff "<title>"    # copyable handoff for a new session or sub-agent
4. implement changes                             # code
5. uv run pytest                                 # test
6. uv run legion-dev architecture gate           # gate
7. /review                                       # subagent code review (see below)
8. git add <files> && git commit                 # commit
9. wt merge main                                 # land on main
```

See `.claude/rules/worktrees.md` for AI agent coordination rules (which files are safe to parallelize, which require coordination).

### Claude + Worktrees

The `-x claude` flag launches Claude Code inside an isolated worktree. It works autonomously on the task while you do other things.

Every prompt should end with a **quality gate** — tell Claude to test, review, and open a PR:

```
After implementation:
1. Run uv run pytest
2. Run uv run legion-dev architecture gate
3. Run /review and fix any findings
4. Repeat steps 1-3 up to 3 passes until clean
5. Commit and push the branch
6. Run gh pr create with a summary of changes
```

Two or three passes is enough for most work. Bump to four for cross-cutting changes.

**Examples:**

```bash
# Feature work — Claude implements, tests, reviews, and opens a PR
wt switch -x claude -c feature/health-endpoints -- \
  'Add liveness and readiness endpoints to the API.

- GET /health returns 200 with {"status": "ok"}
- GET /health/ready checks DB connectivity, returns 503 if unreachable
- Both endpoints skip API key auth middleware
- Add tests for healthy and degraded DB scenarios

After implementation:
1. Run uv run pytest
2. Run uv run legion-dev architecture gate
3. Run /review and fix any findings
4. Repeat 1-3 up to 3 passes until clean
5. Commit and push
6. Run gh pr create with a summary'
```

```bash
# Read-only investigation — no edits, just analysis
wt switch -x 'claude --read-only' -c investigate/flaky-tests -- \
  'test_dispatch_service.py::test_reassign_disconnected is flaky — passes
locally, fails ~30% in CI. Find the root cause. Check for timing issues,
shared state, and async races. Report findings with line numbers and a
suggested fix. Do not edit files.'
```

**Parallel agents** — run each in a separate terminal:

```bash
# Terminal 1 — telemetry (touches plumbing/ and api/)
wt switch -x claude -c feature/telemetry -- \
  'Add observability to the plumbing layer.

- plumbing/telemetry.py: Prometheus counters, histograms, gauges + OpenTelemetry
  tracer. No-ops when disabled. No SDK init or background threads when off.
- plumbing/plugins.py: @tool decorator for metadata (name, description, category,
  read_only). No AI framework imports.
- /metrics endpoint on the API (Prometheus scrape target)
- Instrument DispatchService and SessionService with intentional metrics
  (jobs_dispatched_total, job_duration_seconds — not auto-instrumented noise)
- Unit tests for telemetry helpers and the plugin decorator

After implementation:
1. Run uv run pytest
2. Run uv run legion-dev architecture gate
3. Run /review and fix any findings
4. Repeat 1-3 up to 3 passes until clean
5. Commit and push
6. Run gh pr create with a summary'

# Terminal 2 — migrations (touches alembic/ and app startup)
wt switch -x claude -c feature/alembic -- \
  'Set up Alembic for database migrations.

- alembic init, configure env.py against legion/plumbing/database.py models
- Autogenerate initial migration from the existing ORM schema
- Wire alembic upgrade head into app startup (production + dev-with-file-DB)
- Keep create_all() for test fixtures (sqlite:///:memory: skips migrations)
- Add ADR in docs/decisionlog/ for the alembic dependency

After implementation:
1. Run uv run pytest
2. Run uv run legion-dev architecture gate
3. Run /review and fix any findings
4. Repeat 1-3 up to 3 passes until clean
5. Commit and push
6. Run gh pr create with a summary'
```

**Monitoring:**

```bash
wt list
# Branch               Status   Path                          ...
# @ main                   ^    .
# + feature/telemetry  ↑ 🤖     ../legion.feature-telemetry       # working
# + feature/alembic    ↑ 💬     ../legion.feature-alembic         # waiting for input
```

**Landing changes:**

```bash
# If Claude already pushed and opened a PR, just review it on GitHub.

# To merge directly (small, low-risk changes):
wt switch feature/telemetry
wt merge main                      # rebase, merge, clean up worktree

# To clean up after a merged PR:
wt remove feature/alembic
```

**Parallelization safety:** Surfaces (`cli/`, `slack/`, `api/`) and independent core modules (`core/kubernetes/`, `core/database/`) are safe to work on in parallel. Don't let two worktrees touch the same service or domain file. See `.claude/rules/worktrees.md`.

### Pre-Commit Code Review

Before committing, run `/review` in Claude Code. This hands the diff to a fresh agent context that checks:

- Layer violation (imports flowing upward)
- Banned imports in `core/` (LangChain, Rich, Slack SDK, FastAPI)
- Missing `from __future__ import annotations`
- Common mistakes (formatting in services, loose dicts, Slack fields on domain models)
- Test coverage for new modules
- Security concerns (credentials, eval/exec, unsanitized input)

The review outputs a structured PASS/FAIL. Address findings before committing.

For AI agents: the implementing agent should spawn a subagent with a fresh context to perform the review, avoiding the bias of reviewing your own work.

---

## Adding a New Core Domain

Example: adding Cloudflare support.

1. Create `core/cloudflare/client.py` with SDK wrapper functions.
2. Create `core/cloudflare/models.py` for colocated models.
3. Write tests.
4. Zero changes to existing code.

A surface command can call the core functions directly. If it later needs multi-step coordination, a service will handle it.

## Adding a New Surface Command

Pass-through (no service needed):

```python
# cli/commands/cloudflare.py
from legion.plumbing.registry import register_command
from legion.core.cloudflare.client import get_proxy_status

@register_command("network", "proxy-status")
def proxy_status(zone_id: str):
    result = get_proxy_status(zone_id)
    views.render_proxy_status(result)
```

Orchestrated (service needed):

```python
# cli/commands/failover.py
from legion.plumbing.registry import register_command
from legion.services.failover_service import FailoverService

@register_command("ops", "failover")
def execute(source: str, target: str):
    service = get_failover_service()
    plan = service.execute(source_region=source, target_region=target)
    views.render_failover_plan(plan)
```

## Quick Reference

| I need to... | Go to... |
|:-------------|:---------|
| Call one external API | `core/<domain>/client.py` |
| Define a model for one API's response | `core/<domain>/models.py` |
| Define a model spanning multiple APIs | `domain/<concept>.py` |
| Coordinate multiple APIs with state | `services/<concept>_service.py` |
| Add a CLI command | `cli/commands/<domain>.py` |
| Add a Slack slash command | `slack/commands/<domain>.py` |
| Add an API endpoint | `api/routes/<domain>.py` |
| Format output for terminal | `cli/views/<domain>.py` |
| Format output for Slack | `slack/views/<domain>.py` |

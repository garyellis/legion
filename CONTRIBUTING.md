# Contributing to Legion

How to work in this codebase without breaking it.

---

## The Architecture in 60 Seconds

Headless core consumed by multiple surfaces. Business logic is written once and exposed through CLI, Slack, HTTP API, and AI agents without duplication.

```
              +--------+--------+--------+
              |  cli/  | slack/ |  api/  |   SURFACES
              +---+----+---+----+---+----+
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

Enforced by `uv run legion-cli architecture check` and `tests/test_dependency_direction.py`.

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

Every new dependency requires a decision record in `docs/decisionlog/`. See `docs/decisionlog/0000-template.md` for the format.

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
uv run legion-cli architecture check           # layer violations + banned imports
uv run legion-cli architecture typecheck       # mypy
uv run legion-cli architecture circular        # circular import detection
uv run legion-cli architecture deadcode        # vulture dead code
uv run legion-cli architecture unused-deps     # unused dependency detection
uv run legion-cli architecture dangerous-calls # eval/exec/pickle restrictions
uv run legion-cli architecture security        # bandit SAST
uv run legion-cli architecture audit           # pip-audit CVE scan
uv run legion-cli architecture secrets-check   # sensitive file detection

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
from legion.cli.registry import register_command
from legion.core.cloudflare.client import get_proxy_status

@register_command("network", "proxy-status")
def proxy_status(zone_id: str):
    result = get_proxy_status(zone_id)
    views.render_proxy_status(result)
```

Orchestrated (service needed):

```python
# cli/commands/failover.py
from legion.cli.registry import register_command
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

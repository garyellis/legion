# Contributing to Legion

How to work in this codebase without breaking it.

---

## The Architecture in 60 Seconds

The platform is a headless core consumed by multiple surfaces. Business
logic is written once and exposed through CLI, Slack, HTTP API, and AI agents
without duplication.

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

## Six Constraints (Priority Order)

When constraints conflict, higher-numbered ones yield to lower-numbered ones.

| # | Constraint | What it means |
|:--|:-----------|:--------------|
| 1 | **Clarity** | A new engineer reads the folder name and knows what's inside. |
| 2 | **Dependency direction** | Imports flow downward through the layers. Never violated, even for convenience. |
| 3 | **Single owner** | Every concept has exactly one canonical home. `grep` for where `Incident` is defined and you get one result. |
| 4 | **Testability** | Every layer is testable in isolation. Core needs no mocks. Services need only interface mocks. |
| 5 | **Additive extensibility** | Adding a new domain or surface requires zero changes to existing code. |
| 6 | **Minimal layers** | A layer that doesn't earn its keep is deleted. Three clear layers beat five theoretical ones. |

---

## Layer Definitions

### `plumbing/` — Shared infrastructure

Base config, exception hierarchy, database engine, logging setup. Imported by every layer.
Imports nothing from `legion/`.

### `core/` — One API, one adapter

Pure functions and SDK wrappers. Each subdirectory is one infrastructure domain.
Models are colocated with the logic that produces them.

- **Imports**: `plumbing/` + stdlib + external SDKs. Nothing else from `legion/`.
- **Test strategy**: Integration tests against real or mocked SDKs.

Why models live here: `VMInstance` is meaningless without `OpenStackCompute`.
They share a bounded context. Separating them into `domain/` creates artificial distance.

### `domain/` — Concepts that span multiple APIs

Pure Pydantic models for business entities that cross core domain boundaries.
No logic, no API calls, no persistence.

- **Imports**: `plumbing/`, `core/` models only (for type references, never logic).
- **Litmus test**: "Does this entity involve decisions across multiple core domains?" If yes, `domain/`. If it maps 1:1 to an SDK response, it stays in `core/`.

Examples: `Incident` spans K8s + Prometheus + Slack. `Job` coordinates agent dispatch
across multiple infrastructure domains. Neither belongs to a single core domain.

### `services/` — Coordination with state

Stateful coordinators that own persistence, scheduling, and cross-domain workflows.

- **Imports**: `plumbing/`, `core/`, `domain/`. Never from agents or surfaces.
- **Communication outward**: Via injected callbacks, not surface imports.
- **Dependencies**: Received via constructor injection.
- **Litmus test**: "Does this need a constructor with injected dependencies?" If yes, service. If it's a pure function, `core/`.

```python
class IncidentService:
    def __init__(self, repository: IncidentRepository,
                 on_incident_created: Callable[[Incident], Awaitable[None]] | None = None):
        self._repo = repository
        self._on_created = on_incident_created  # Callback, not import
```

The distinction from core is statefulness. Core orchestrators are stateless
pipelines (fetch, filter, return). Services maintain state across calls.

### `agents/` — AI runtime

LLM agent infrastructure: model configuration, chains (simple prompt-LLM pipelines),
and persona configs.

- **Imports**: `plumbing/`, `core/`, `domain/`, `services/`. Never imported by them.

### Surfaces — `cli/`, `slack/`, `api/`

Independent consumers of the layers below. Thin. Parse input, call logic, format output.

- Never imported by anything else. No surface imports from another surface.
- Formatting is a surface concern. Rich tables in `cli/views/`, Block Kit in `slack/views/`, JSON in `api/`.
- Each surface is a standalone entry point with its own DI wiring at startup.

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

### Pass-throughs skip services

Not every command needs a service. If a CLI command is a thin wrapper around one
core function, call `core/` directly from the surface. Don't force everything
through a service layer.

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

Services never import surfaces. When a service needs to notify the outside world,
it calls an injected callback. The surface wires the callback at startup:

```python
# slack/main.py (startup wiring)
incident_service = IncidentService(
    repository=repo,
    on_incident_created=lambda inc: slack_service.create_incident_channel(inc),
)
```

### Dependencies require ADRs

Every new dependency requires a decision record in `docs/decisionlog/`. Document
why it's needed, alternatives considered, license, maintenance status, and supply
chain risk. See the template at `docs/decisionlog/0000-template.md`.

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
| Vendor payload parsing in `domain/` | Parsing is a boundary concern; put it in the surface |

---

## Development Setup

```bash
git clone <repo-url>
cd legion
uv sync --group dev

# Run tests
uv run pytest

# Architecture checks
uv run legion-cli architecture check

# Enable pre-commit hook
git config core.hooksPath .githooks
```

## Adding a New Core Domain

Example: adding Cloudflare support.

1. Create `core/cloudflare/client.py` with SDK wrapper functions.
2. Create `core/cloudflare/models.py` for domain models.
3. Write tests.
4. Zero changes to existing code.

A CLI command or Slack command can call the core functions directly. If it later
needs to participate in a multi-step workflow, a service will coordinate it.

## Adding a New Surface Command

Pass-through (no service needed):

```python
# cli/commands/cloudflare.py
from legion.core.cloudflare.client import get_proxy_status

@register_command("network", "proxy-status")
def proxy_status(zone_id: str):
    result = get_proxy_status(zone_id)
    views.render_proxy_status(result)
```

Orchestrated (service needed):

```python
# cli/commands/failover.py
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

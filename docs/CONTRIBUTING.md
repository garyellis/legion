# Contributing

This guide is for **humans and AI agents** contributing to the `legion` platform. Read this first. See `docs/ARCHITECTURE.md` for deeper rationale.

---

## Setup

```bash
git clone <repo-url> && cd legion
uv sync

# Run CLI
uv run legion-cli lab vm-list

# Run Slack bot
source env.sh   # Set SLACK_BOT_TOKEN, SLACK_APP_TOKEN
uv run legion-slack
```

---

## Where Does My Code Go?

Answer these questions in order. Stop at the first match.

```
Is it shared infrastructure (config, logging, database, exceptions)?
  → plumbing/                        (importable by every layer)

Is it one API call that returns data?
  → core/<domain>/client.py          (add the function)

Is the data structure 1:1 with an API response?
  → core/<domain>/models.py          (keep it with the API it came from)

Does it coordinate multiple APIs or apply business rules?
  → services/<concept>_service.py    (orchestration lives here)

Is the data structure used by more than one core module?
  → domain/<concept>.py              (cross-cutting entity)

Does it parse input or format output for a specific medium?
  → Surface layer: cli/, slack/, api/, tui/
```

### Quick Reference

| I need to... | Go to... |
|:-------------|:---------|
| Add a config class for a new domain | `core/<domain>/config.py` extending `LegionConfig` |
| Change logging behavior | `plumbing/logging.py` |
| Add a new exception type | `plumbing/exceptions.py` (base), or layer-specific `exceptions.py` |
| Add an ORM model | Inherit from `plumbing/database.py:Base`, place in the appropriate layer |
| Call one external API | `core/<domain>/client.py` |
| Define a model for one API's response | `core/<domain>/models.py` |
| Define a model spanning multiple APIs | `domain/<concept>.py` |
| Coordinate multiple APIs with state | `services/<concept>_service.py` |
| Persist or schedule | `services/repository.py`, `plumbing/scheduler.py` |
| Build a simple LLM pipeline | `agents/chains/<name>.py` |
| Add a CLI command | `cli/commands/<domain>.py` |
| Add a Slack slash command | `slack/commands/<domain>.py` |
| Add a webhook endpoint | `api/routes/<domain>.py` |
| Format output for terminal | `cli/views/<domain>.py` |
| Format output for Slack | `slack/views/<domain>.py` |
| Parse a vendor webhook payload | `api/parsers/<vendor>.py` |

---

## The Developer Workflow

Don't think about surfaces until step 4.

```
Step 1: "I need to call the Harness API"
         → core/harness/client.py (does it exist? add the method)

Step 2: "I need to coordinate Harness + GitHub + Jira"
         → services/deployment_service.py

Step 3: "I need a data structure that crosses API boundaries"
         → domain/deployment.py

Step 4: "I need users to trigger this"
         → NOW think about surfaces:
           cli/commands/deploy.py
           slack/commands/deploy.py
           api/routes/deploy.py
         All three call the same service. Each is thin:
         parse args → call logic → format output.
```

Steps 1-3 are identical regardless of surface. Step 4 is thin.

---

## Hard Rules

These are non-negotiable. Violating them creates coupling that compounds over time.

### 1. Dependency Direction

```
plumbing/  → imports NOTHING from legion (only stdlib + pydantic-settings, sqlalchemy, apscheduler)
core/      → imports from plumbing/ only (plus stdlib + external SDKs)
domain/    → imports from plumbing/ and core models (type references, never logic)
services/  → imports from plumbing/, core/, domain/
agents/    → imports from plumbing/, core/, domain/, services/
surfaces   → import from any layer below
```

`plumbing/` is the bedrock. No lateral imports. `cli/` never imports from `slack/`. Callbacks flow up. Imports flow down.

This is enforced by `tests/test_dependency_direction.py` — it will catch violations.

### 2. Core Stays Framework-Free

`core/` never imports LangChain, Rich, or FastAPI. The Slack SDK is allowed only in `core/slack/` (it's the API wrapper for that domain).

### 3. Services Communicate via Callbacks

Services must not import surfaces. Use injected callbacks:

```python
# slack/main.py (startup wiring)
incident_service = IncidentService(
    repository=repo,
    on_stale_incident=lambda inc: notify_channel(inc),
    on_incident_resolved=lambda inc, summary: post_resolution(inc, summary),
)
```

### 4. Pass-Throughs Skip Services

If a command wraps one core function, call `core/` directly from the surface. Don't force indirection where orchestration doesn't exist.

### 5. Formatting Stays in Surfaces

Rich tables → `cli/views/`. Block Kit → `slack/views/`. JSON → `api/`. Never in `core/` or `services/`.

---

## Configuration

Configuration uses `plumbing/config/`. Every config class extends `LegionConfig` (a `pydantic-settings` base class).

### Adding Config for a New Domain

```python
# core/cloudflare/config.py
from legion.plumbing.config import LegionConfig
from pydantic import SecretStr
from pydantic_settings import SettingsConfigDict

class CloudflareConfig(LegionConfig):
    model_config = SettingsConfigDict(env_prefix="CLOUDFLARE_")

    api_token: SecretStr       # Required — no default, fails if missing
    zone_id: str               # Required
    account_id: str = ""       # Optional — has default
```

### Using Config

```python
# Surface creates config at startup, injects it
config = CloudflareConfig()                    # Reads CLOUDFLARE_* env vars
client = CloudflareClient(config)              # Injected, not self-instantiated

# For optional integrations
if CloudflareConfig().is_available():
    # Only init if env vars are present
    ...
```

### Config Rules

- **Prefix all env vars**: `OPENSTACK_AUTH_URL`, `SLACK_BOT_TOKEN`, `AGENT_MODEL_NAME`.
- **Defaults for non-secrets only**. Secrets (`SecretStr`) never have defaults.
- **Inject, don't self-instantiate**. Surfaces create configs, pass to constructors.
- **Fail fast**. Create all configs at startup, not deep in request paths.
- **No global singleton**. Each process composes only what it needs.
- **Use `to_redacted_dict()` for debug logging**. Never log raw secrets.

---

## Plumbing Reference

`plumbing/` provides shared infrastructure. Every layer imports from it; it imports from none of them.

| Module | What It Does | When to Use |
|:-------|:-------------|:------------|
| `config/base.py` | `LegionConfig` base class with `is_available()`, `to_redacted_dict()` | Extend for any new config class |
| `config/platform.py` | `PlatformConfig` — `LEGION_LOG_LEVEL`, `LEGION_ENVIRONMENT` | Platform-wide settings |
| `config/database.py` | `DatabaseConfig` — `DATABASE_URL`, pool settings | Database connection config |
| `config/telemetry.py` | `TelemetryConfig` — observability provider toggles | Telemetry setup |
| `logging.py` | `setup_logging(level, output, fmt)` — text or JSON, stdout or stderr | Called once per surface at startup |
| `database.py` | SQLAlchemy `Base`, `create_engine()`, `create_all()` | Any ORM model or engine creation |
| `exceptions.py` | `LegionError` with `retryable` hint and `to_dict()` | Base class for all project exceptions |
| `scheduler.py` | `SchedulerService` — APScheduler wrapper for recurring jobs | Background tasks (status checks, cleanup) |

### Logging Setup

Each surface calls `setup_logging()` once at startup:

```python
from legion.plumbing.logging import setup_logging, LogFormat, LogOutput

setup_logging(level="INFO", output=LogOutput.STDOUT, fmt=LogFormat.JSON)
```

### Exception Hierarchy

All project exceptions inherit from `LegionError`:

```python
from legion.plumbing.exceptions import LegionError

class ExternalAPIError(LegionError):
    retryable = True    # Hint for callers — retry might succeed
```

---

## Persistence

### Repository Pattern

Every persisted domain uses an ABC + implementations:

```python
# services/repository.py
class IncidentRepository(ABC):
    def save(self, incident: Incident) -> None: ...
    def get_by_id(self, incident_id: str) -> Optional[Incident]: ...
    def list_active(self) -> list[Incident]: ...

class InMemoryIncidentRepository(IncidentRepository): ...   # Tests, simple dev
class SQLiteIncidentRepository(IncidentRepository): ...     # SQLite + PostgreSQL
```

### Adding a New Table

1. Define an ORM class inheriting from `plumbing.database.Base` in the appropriate layer.
2. Surfaces call `create_all(engine)` at startup — all tables from all `Base` subclasses are created.
3. Use `DateTime(timezone=True)` for datetime columns. Add `_ensure_utc()` in the mapper if supporting SQLite (it strips timezone info).

### Contract Tests

Both in-memory and database implementations must pass identical contract tests:

```python
@pytest.fixture(params=["memory", "sqlite"])
def repo(request):
    if request.param == "memory":
        return InMemoryIncidentRepository()
    engine = create_engine("sqlite:///:memory:")
    create_all(engine)
    return SQLiteIncidentRepository(engine)
```

---

## Common Mistakes

| Mistake | Do This Instead |
|:--------|:----------------|
| Wrapping every command in a service | Surface calls `core/` directly for pass-throughs |
| API response models in `domain/` | 1:1 API models stay in `core/` |
| Business rules in `core/` | Rules spanning APIs go in `services/` |
| Formatting in `services/` | Services return models; surfaces format |
| `import rich` in `core/` | Rich belongs in `cli/views/` |
| `from legion.slack import ...` in `services/` | Use callback injection |
| Slack-specific fields on domain models | Surface-specific state stays in `slack/<concept>/models.py` |
| Adding all surfaces at once | Port CLI first, add Slack/API later |
| Config singleton or global settings module | Each process composes its own config at startup |
| Secrets with default values | `SecretStr` fields must be required (no defaults) |
| `import plumbing` from outside legion | `plumbing/` is internal to `legion/`, never a public API |
| `DateTime` without `timezone=True` | SQLite strips tz info; use `DateTime(timezone=True)` + `_ensure_utc()` |

---

## Adding a New Core Domain

Example: adding Cloudflare support.

1. Create `core/cloudflare/config.py` extending `LegionConfig`.
2. Create `core/cloudflare/client.py` with SDK wrapper functions.
3. Create `core/cloudflare/models.py` if the domain has shared models.
4. Write integration tests.
5. **Zero changes to existing code.** (Additive extensibility)

```python
# core/cloudflare/client.py
class CloudflareClient:
    def __init__(self, config: CloudflareConfig) -> None: ...
    def update_proxy_backend(self, zone_id: str, target_origin: str) -> ProxyStatus: ...
```

---

## Adding a New Surface Command

### Pass-through (no service)

```python
# cli/commands/cloudflare.py
from legion.core.cloudflare.client import CloudflareClient

@app.command()
def proxy_status(zone_id: str):
    client = CloudflareClient(CloudflareConfig())
    result = client.get_proxy_status(zone_id)
    views.render_proxy_status(result)
```

### Orchestrated (service needed)

```python
# cli/commands/failover.py
from legion.services.failover_service import FailoverService

@app.command()
def execute(source: str, target: str):
    service = get_failover_service()
    plan = service.execute(source_region=source, target_region=target)
    views.render_failover_plan(plan)
```

---

## Adding a New Bot Process

Follow the Incident Commander pattern:

1. **Domain model** (`domain/<concept>.py`) — Pure Pydantic. No surface state.
2. **Service** (`services/<concept>_service.py`) — Lifecycle coordinator with injected callbacks.
3. **Repository** (`services/repository.py`) — ABC + at least one impl (in-memory for dev, SQLite for persistence).
4. **Core adapter** (if needed, `core/<vendor>/client.py`) — SDK wrapper with error translation.
5. **Slack surface** (`slack/<concept>/`) — models.py (ABC + in-memory index), persistence.py (DB-backed index), handlers.py, wiring.py.
6. **Wire into `slack/main.py`** — Instantiate config, engine, repo, service. Register handlers.
7. **AI chains** (optional, `agents/chains/`) — Wrap in try/except. Bot must work without AI.
8. **Tests** — Domain, service (with in-memory repo + stub callbacks), contract tests (parameterized across impls), integration.

---

## Porting an Existing CLI Tool

1. **Inventory commands.** For each: pass-through or orchestration?
2. **Extract `core/` modules.** Each external API → `core/<name>/client.py`. Add a config class.
3. **Identify cross-cutting models.** Spans multiple APIs → `domain/`. Single API → stays in `core/`.
4. **Extract services only where needed.** Genuine cross-API coordination only.
5. **Wire surfaces.** Thin Typer commands: parse args → call logic → format output.
6. **Add surfaces incrementally.** Slack, API, agent tools added later.

---

## For AI Agents

If you are an LLM or AI coding agent working on this codebase, these are the rules that matter most:

1. **Read this file and `docs/ARCHITECTURE.md` before making changes.** They are the source of truth for project structure.

2. **Never add imports that violate dependency direction.** The layer diagram is strict:
   - `plumbing/` imports nothing from `legion/`
   - `core/` imports only from `plumbing/` (plus stdlib + external SDKs)
   - No surface imports from another surface
   - No upward imports (e.g., `services/` importing from `agents/`)
   - `tests/test_dependency_direction.py` enforces this automatically

3. **Use the decision tree** in "Where Does My Code Go?" to place every file. When uncertain, ask.

4. **Don't over-engineer.** Most commands are pass-throughs. Only create a service when genuine multi-API orchestration or statefulness exists.

5. **Don't add frameworks to `core/`.** No LangChain, no Rich, no FastAPI. Slack SDK is allowed only in `core/slack/`.

6. **Formatting is always a surface concern.** Return data models from logic layers. Let surfaces decide how to render.

7. **Keep domain/ small.** Only models that genuinely cross multiple core domains. When in doubt, keep the model in `core/`.

8. **Config follows the pattern.** Extend `LegionConfig`, use an env var prefix, inject via constructor. Never create config singletons or import config globally.

9. **Test strategy by layer:**
   - `core/` — Integration tests, no mocks needed
   - `services/` — Unit tests with interface mocks and stub callbacks
   - `agents/` — Tool stubs
   - Surfaces — Thin enough to test via integration
   - Persistence — Contract tests parameterized across in-memory + SQLite

10. **When adding a new feature**, follow the workflow: plumbing (if infrastructure) → core → domain (if cross-cutting) → services (if orchestration) → surface. In that order.

11. **Commit conventions**: Small, focused commits. One concern per commit. Descriptive messages that explain why, not what.

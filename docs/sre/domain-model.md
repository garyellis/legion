# Domain Model

New entities for the SRE agent fleet. All are Pydantic models in `domain/`, with ORM rows in the service layer following the existing `Incident`/`IncidentRow` pattern.

---

## Entity Relationship

```
Organization (tenant boundary)
 ├── ClusterGroup (dev-aks, prod-aks, ...)
 │    ├── Agent (running process, state: idle/busy/offline)
 │    ├── PromptConfig (system prompt, stack manifest, persona)
 │    ├── Session (conversational context, pins to one agent)
 │    │    └── Job (query messages within the conversation)
 │    └── Job (triage or query, dispatched to an agent)
 │         └── Incident (outcome of triage, links to existing Incident model)
 └── ChannelMapping (Slack channel → cluster group, mode: alert or chat)
      └── FilterRule (regex/label match → triage trigger, alert mode only)
```

---

## Entities

### Organization

Tenant boundary. All resources scoped to an org.

```python
# domain/organization.py
class Organization(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    name: str
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
```

Placement: `domain/` because it scopes entities across multiple core domains and surfaces.

### ClusterGroup

A registered environment. The routing target for jobs.

```python
# domain/cluster_group.py
class ClusterGroup(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    org_id: str
    name: str                        # "dev-aks", "prod-aks"
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
```

### Agent

A running agent process. Belongs to a cluster group. State machine: `idle` → `busy` → `idle`, or `offline`.

```python
# domain/agent.py
class AgentState(str, Enum):
    IDLE = "idle"
    BUSY = "busy"
    OFFLINE = "offline"

class Agent(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    cluster_group_id: str
    state: AgentState = AgentState.OFFLINE
    last_heartbeat: Optional[datetime] = None
    current_job_id: Optional[str] = None
```

### ChannelMapping

Links a Slack channel to a cluster group. One channel → one cluster group. The `mode` determines how messages are handled.

```python
# domain/channel_mapping.py
class ChannelMode(str, Enum):
    ALERT = "alert"                  # Filter rules evaluate messages → triage jobs
    CHAT = "chat"                    # Every message → query job via session

class ChannelMapping(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    org_id: str
    channel_id: str                  # Slack channel ID
    cluster_group_id: str
    mode: ChannelMode = ChannelMode.ALERT
```

### FilterRule

Per-channel rules that decide what messages trigger triage jobs.

```python
# domain/filter_rule.py
class FilterAction(str, Enum):
    TRIAGE = "triage"
    IGNORE = "ignore"

class FilterRule(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    channel_mapping_id: str
    pattern: str                     # Regex pattern
    action: FilterAction = FilterAction.TRIAGE
    priority: int = 0                # Higher = evaluated first
```

### PromptConfig

System prompts, stack manifests, and persona per cluster group. Delivered in job payloads.

```python
# domain/prompt_config.py
class PromptConfig(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    cluster_group_id: str
    system_prompt: str = ""
    stack_manifest: str = ""         # "Payment-API → Redis → Postgres"
    persona: str = ""                # "PostgreSQL Expert", "Network Architect"
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
```

### Session

A conversational context between a user and an agent. Groups related query jobs so the agent retains context across turns. Pinned to a single agent for the duration.

```python
# domain/session.py
class SessionStatus(str, Enum):
    ACTIVE = "active"
    CLOSED = "closed"

class Session(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    org_id: str
    cluster_group_id: str
    agent_id: Optional[str] = None   # Pinned agent (set on first dispatch)
    slack_channel_id: Optional[str] = None   # Slack channel (if originated from Slack)
    slack_thread_ts: Optional[str] = None    # Thread anchor
    status: SessionStatus = SessionStatus.ACTIVE
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    last_activity: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
```

Placement: `domain/` because sessions span surfaces (Slack today, admin UI tomorrow). The `slack_*` fields are optional — a session started from the dashboard won't have them.

### Job

A unit of work dispatched to an agent.

```python
# domain/job.py
class JobType(str, Enum):
    TRIAGE = "triage"
    QUERY = "query"

class JobStatus(str, Enum):
    PENDING = "pending"              # Waiting for an idle agent
    ASSIGNED = "assigned"            # Dispatched to an agent
    RUNNING = "running"              # Agent executing
    COMPLETED = "completed"
    FAILED = "failed"

class Job(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    org_id: str
    cluster_group_id: str
    job_type: JobType
    status: JobStatus = JobStatus.PENDING
    payload: str                     # Message text or alert payload
    slack_channel_id: str            # Where to post results
    slack_thread_ts: Optional[str] = None
    assigned_agent_id: Optional[str] = None
    session_id: Optional[str] = None     # Set for conversational query jobs
    incident_id: Optional[str] = None  # Links to existing Incident if triage creates one
    result: Optional[str] = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    completed_at: Optional[datetime] = None
```

---

## File Organization

Each entity gets its own file in `domain/`. This keeps files small and imports explicit.

```
domain/
├── incident.py              # Existing — unchanged
├── organization.py          # New
├── cluster_group.py         # New
├── agent.py                 # New
├── channel_mapping.py       # New (includes ChannelMode enum)
├── filter_rule.py           # New
├── prompt_config.py         # New
├── session.py               # New
└── job.py                   # New (session_id links to Session)
```

---

## Existing Incident Integration

`Job` links to `Incident` via `incident_id`. When a triage job's result warrants an incident, the service creates an `Incident` (using the existing `IncidentService`) and sets `job.incident_id`. The existing incident lifecycle (open → investigating → resolved → closed) continues unchanged.

This is a reference, not a foreign key in the domain model. The service layer enforces the relationship. The domain stays clean.

---

## Repository Pattern

Each entity follows the established pattern:

```python
# services/job_repository.py
class JobRepository(ABC):
    @abstractmethod
    def save(self, job: Job) -> None: ...
    @abstractmethod
    def get_by_id(self, job_id: str) -> Optional[Job]: ...
    @abstractmethod
    def list_pending(self, cluster_group_id: str) -> list[Job]: ...

class InMemoryJobRepository(JobRepository): ...
class SQLiteJobRepository(JobRepository): ...
```

Contract tests parameterized across both implementations, using in-memory SQLite for the database variant.

For entities that are simple CRUD with no complex queries (Organization, ClusterGroup, ChannelMapping, FilterRule, PromptConfig), a generic repository or a single combined repository per aggregate may be simpler than one ABC per entity. Decide at implementation time based on query needs.

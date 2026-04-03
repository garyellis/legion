---
paths: ["legion/**/*.py"]
---

# Common Code Patterns

Reference patterns for this codebase. Follow these when creating new files.

## Configuration (plumbing/config/)

```python
from legion.plumbing.config.base import LegionConfig
from pydantic import SecretStr

class KubernetesConfig(LegionConfig):
    model_config = {"env_prefix": "LEGION_K8S_"}
    kubeconfig_path: str = "~/.kube/config"
    context: str | None = None
```

## Repository Pattern (services/)

```python
from abc import ABC, abstractmethod
from sqlalchemy import Engine

class JobRepository(ABC):
    @abstractmethod
    def save(self, job: Job) -> None: ...

    @abstractmethod
    def get_by_id(self, job_id: str) -> Job | None: ...

class SQLiteJobRepository(JobRepository):
    def __init__(self, engine: Engine) -> None:
        self._engine = engine
```

## Service with Callback Injection

```python
class DispatchService:
    def __init__(
        self,
        job_repo: JobRepository,
        fleet_repo: FleetRepository,
        *,
        on_job_created: Callable[[Job], Awaitable[None]] | None = None,
    ) -> None:
        self._jobs = job_repo
        self._fleet = fleet_repo
        self._on_job_created = on_job_created
```

## Domain Entity with Enum State

```python
from enum import Enum
from pydantic import BaseModel, Field

class JobState(str, Enum):
    PENDING = "PENDING"
    DISPATCHED = "DISPATCHED"
    RUNNING = "RUNNING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"

class Job(BaseModel):
    model_config = {"validate_assignment": True}
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    state: JobState = JobState.PENDING
```

## Core Tool (framework-free)

```python
# core/kubernetes/pods.py
from legion.plumbing.plugins import tool

@tool(category="kubernetes", read_only=True)
def get_pod_status(namespace: str, pod_name: str) -> str:
    """Get the current status of a Kubernetes pod."""
    # Pure infrastructure code, no AI framework imports
    ...
```

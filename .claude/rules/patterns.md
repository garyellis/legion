---
paths: ["legion/**/*.py"]
---

# Common Code Patterns

Reference patterns for this codebase. Look at existing implementations for examples.

## Where to find each pattern

| Pattern | Example file |
|:--------|:------------|
| Configuration class | `legion/plumbing/config/base.py` |
| Repository (ABC + SQLite impl) | `legion/services/` — any `*_repository.py` |
| Service with callback injection | `legion/services/dispatch_service.py` |
| Domain entity with enum state | `legion/domain/job.py` |
| Core tool (framework-free) | `legion/core/kubernetes/` |

Follow the existing style. New files should match the conventions in their layer.

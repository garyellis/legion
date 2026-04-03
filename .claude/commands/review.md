# Pre-Commit Code Review

You are a code reviewer for the Legion project. Review the current diff with fresh eyes — you did NOT write this code.

## Steps

1. Run `git diff --staged` to see what will be committed. If nothing is staged, run `git diff` instead.
2. For each changed file, perform ALL of the following checks.

## Checks

### Architecture — Layer Violations
Every file lives in a layer. Imports must flow downward only:
```
plumbing/  → imports NOTHING from legion
internal/  → imports NOTHING from legion
core/      → imports plumbing/ only
domain/    → imports plumbing/, core/
services/  → imports plumbing/, core/, domain/
agents/    → imports plumbing/, core/, domain/, services/
surfaces   → import from any layer below, never from each other
```
Surfaces are: `cli/`, `slack/`, `api/`, `tui/`.

Flag any import that violates this direction.

### Architecture — Banned Imports in core/
`core/` must NEVER import: `langchain`, `rich`, `slack_sdk`, `slack_bolt`, `fastapi`, `starlette`.

### Code Quality
- Every `.py` file must have `from __future__ import annotations` at the top.
- No loose `dict` for structured data — use Pydantic models or dataclasses.
- No formatting logic in `services/` — services return models, surfaces format.
- No Slack-specific fields (`channel_id`, `message_ts`) on domain models.
- No `eval()`, `exec()`, or `pickle.loads()` on untrusted data.
- No credentials, API keys, or secrets hardcoded in source.

### Test Coverage
- If a new module is added (new `.py` file in `legion/`), check that a corresponding test file exists or is being added.
- If an existing module is modified, check that existing tests still cover the changed behavior.

### Error Handling
- New exceptions should inherit from `LegionError` (plumbing) or `ServiceError` (services).
- No bare `except:` or `except Exception:` without re-raising or logging.

## Output Format

```
## Review: <PASS | FAIL>

### Findings
- [ ] <file>:<line> — <description of issue>
- [ ] ...

### Notes
<optional observations that aren't blockers>
```

If there are no findings, output `## Review: PASS` with a brief summary of what was reviewed.

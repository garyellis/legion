from __future__ import annotations

from pathlib import Path


REVIEW_PROMPT_TEMPLATE = """\
You are reviewing code for the Legion project. Apply these project rules:

{rules}

Review the following {diff_type}:

{diff_content}

Produce a structured review with these sections:
## Architecture
- [ ] Layer violations (imports flowing upward)
- [ ] Banned imports in core/ (LangChain, Rich, Slack SDK, FastAPI)
- [ ] Cross-surface imports

## Code Quality
- [ ] Missing `from __future__ import annotations`
- [ ] Loose dicts instead of Pydantic models
- [ ] Formatting logic in services/
- [ ] Slack-specific fields on domain models

## Security
- [ ] Hardcoded credentials or secrets
- [ ] eval()/exec()/pickle.loads() on untrusted data
- [ ] Unsanitized external input

## Testing
- [ ] New modules missing test files
- [ ] Changed behavior missing test updates

End with: **VERDICT: PASS** or **VERDICT: FAIL — {{summary of blocking issues}}**
"""


def build_review_prompt(rules: str, diff: str, diff_type: str) -> str:
    """Assemble the review prompt from rules, diff content, and diff type label."""
    return REVIEW_PROMPT_TEMPLATE.format(
        rules=rules,
        diff_content=diff,
        diff_type=diff_type,
    )


def read_claude_md(repo_root: Path) -> str:
    """Read CLAUDE.md from the repository root, returning empty string if absent."""
    claude_md = repo_root / "CLAUDE.md"
    if claude_md.exists():
        return claude_md.read_text(encoding="utf-8")
    return ""

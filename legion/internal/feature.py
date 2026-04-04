from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class FeatureDocument:
    """Parsed representation of a feature handoff brief."""

    title: str
    status: str
    date: str
    sections: dict[str, str] = field(default_factory=dict)
    filepath: Path = field(default_factory=lambda: Path())
    content: str = ""


def slugify_feature_title(title: str) -> str:
    """Convert a feature title to a filename-safe slug."""
    slug = title.lower().strip()
    slug = re.sub(r"[^a-z0-9\s_-]", "", slug)
    slug = re.sub(r"[\s_]+", "-", slug)
    slug = re.sub(r"-+", "-", slug)
    return slug.strip("-")


def feature_docs_dir(root: Path) -> Path:
    """Return the directory that stores generated feature handoff briefs."""
    return root / "docs" / "features"


def feature_filepath(root: Path, title: str) -> Path:
    """Return the markdown path for a feature handoff brief."""
    return feature_docs_dir(root) / f"{slugify_feature_title(title)}.md"


def find_feature_file(root: Path, title: str) -> Path | None:
    """Find a feature brief by title."""
    path = feature_filepath(root, title)
    return path if path.exists() else None


def generate_feature_template(*, title: str, created_date: str) -> str:
    """Generate a structured feature handoff requirements gate."""
    lines = [
        f"# Feature Requirements Gate: {title}",
        "",
        "**Status**: DRAFT",
        f"**Date**: {created_date}",
        "",
        "<!--",
        "Fill this gate before implementation starts.",
        "Write for execution accuracy, not completeness theater.",
        "This document should be usable as handoff context for a new session or sub-agent.",
        "Name files, layers, interfaces, risks, and verification steps directly.",
        "If a section does not apply, say why instead of deleting it.",
        "-->",
        "",
        "## Problem",
        "",
        "What is failing or inconsistent today? Describe the operational or developer pain.",
        "",
        "## Desired Outcome",
        "",
        "What observable behavior should exist after this feature lands?",
        "",
        "## Non-Goals",
        "",
        "What is explicitly out of scope for this change?",
        "",
        "## Requirements Gate",
        "",
        "- The problem is specific enough that a reviewer can tell when it is fixed.",
        "- The owning layer for each change is identified before coding starts.",
        "- Required tests and validation commands are defined up front.",
        "- Unknowns that would change the implementation are listed explicitly.",
        "",
        "## Workflow",
        "",
        "Describe the end-to-end flow for the human or system using this feature.",
        "",
        "## Current Repo Context",
        "",
        "Summarize the relevant existing behavior, commands, files, and constraints already confirmed in the repo.",
        "",
        "## Constraints",
        "",
        "- Respect the Legion layer model. Note which layer owns each change.",
        "- Do not add dependencies without an ADR in `docs/decisionlog/`.",
        "- Prefer the smallest change that solves the problem without leaking across surfaces.",
        "- Define the tests that prove behavior, not implementation details.",
        "",
        "## Architecture Placement",
        "",
        "### Domain",
        "",
        "List domain models, enums, or value objects that change. If none, say none.",
        "",
        "### Services",
        "",
        "List orchestration or business-rule changes. If none, say none.",
        "",
        "### Surfaces",
        "",
        "List CLI, API, Slack, TUI, or other surface changes. If none, say none.",
        "",
        "### Docs, ADRs, And Migrations",
        "",
        "List documentation, ADR, config, or migration work required. If none, say none.",
        "",
        "## Interfaces And Data Shapes",
        "",
        "List command signatures, DTOs, models, files, or outputs that will change. If none, say none.",
        "",
        "## Files And Ownership",
        "",
        "- List the exact files expected to change.",
        "- Identify any files that must not be touched.",
        "- Note where a follow-up agent can work independently.",
        "",
        "## Failure Modes And Edge Cases",
        "",
        "- What can go wrong?",
        "- What should the system do in that case?",
        "- What is the safe default?",
        "",
        "## Acceptance Criteria",
        "",
        "- Define observable outcomes that must be true when the feature is complete.",
        "- Include at least one negative case when relevant.",
        "",
        "## Verification Plan",
        "",
        "- List unit, integration, and architecture checks required for this feature.",
        "- List exact commands to run before calling the work done.",
        "",
        "## Done Condition",
        "",
        "- State the exact condition for handing this off as complete.",
        "- Include what evidence the next agent must return.",
        "",
        "## Open Questions",
        "",
        "- Capture unresolved decisions, assumptions, or external dependencies.",
        "",
        "## Session Handoff",
        "",
        "Write the final handoff brief for a new session or sub-agent.",
        "Include the implementation order, file targets, banned shortcuts, validation commands, and exact success criteria.",
        "",
    ]
    return "\n".join(lines)


def title_from_filename(filename: str) -> str:
    """Convert a feature filename like ``add-redis.md`` into a title."""
    return filename.removesuffix(".md").replace("-", " ").title()


def parse_feature_document(filepath: Path) -> FeatureDocument:
    """Parse a feature brief markdown file into a structured document."""
    text = filepath.read_text(encoding="utf-8")

    title_match = re.search(r"^#\s+Feature Requirements Gate:\s*(.+)$", text, re.MULTILINE)
    title = title_match.group(1).strip() if title_match else title_from_filename(filepath.name)
    status = _extract_meta(text, "Status")
    feature_date = _extract_meta(text, "Date")
    sections = _parse_sections(text)

    return FeatureDocument(
        title=title,
        status=status,
        date=feature_date,
        sections=sections,
        filepath=filepath,
        content=text,
    )


def _extract_meta(text: str, field_name: str) -> str:
    """Extract a **Field**: Value metadata line."""
    pattern = rf"\*\*{re.escape(field_name)}\*\*:\s*(.+)"
    match = re.search(pattern, text)
    return match.group(1).strip() if match else ""


def _parse_sections(text: str) -> dict[str, str]:
    """Split feature content into sections keyed by ``##`` heading name."""
    sections: dict[str, str] = {}
    headings = list(re.finditer(r"^##\s+(.+)$", text, re.MULTILINE))
    for i, heading in enumerate(headings):
        name = heading.group(1).strip()
        start = heading.end()
        end = headings[i + 1].start() if i + 1 < len(headings) else len(text)
        sections[name] = text[start:end].strip()
    return sections


def build_feature_handoff_prompt(doc: FeatureDocument) -> str:
    """Build a deterministic handoff prompt for a new session or sub-agent."""
    return (
        "You are continuing Legion feature work.\n\n"
        "Use the brief below as the source of truth. Do not widen scope.\n"
        "If key information is missing, report it before changing code.\n\n"
        f"Feature: {doc.title}\n"
        f"Status: {doc.status or 'UNKNOWN'}\n"
        f"Date: {doc.date or 'UNKNOWN'}\n"
        f"File: {doc.filepath.as_posix()}\n\n"
        "Implementation rules:\n"
        "- Follow the Legion layer model.\n"
        "- Do not add dependencies without an ADR.\n"
        "- Prefer the smallest change that satisfies the brief.\n"
        "- Run `uv run pytest` and `uv run legion-dev architecture gate` before handing off.\n\n"
        "Feature brief:\n"
        "```markdown\n"
        f"{doc.content}\n"
        "```\n"
    )

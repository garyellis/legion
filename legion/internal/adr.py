from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path


def find_decisionlog_dir(root: Path) -> Path:
    """Locate the docs/decisionlog/ directory starting from *root*."""
    for parent in [root, *root.parents]:
        candidate = parent / "docs" / "decisionlog"
        if candidate.is_dir():
            return candidate
    msg = "Could not find docs/decisionlog/ directory"
    raise FileNotFoundError(msg)


def detect_next_id(decisionlog_dir: Path) -> int:
    """Scan NNNN-*.md files and return the next available integer ID."""
    max_id = -1
    for path in decisionlog_dir.glob("[0-9][0-9][0-9][0-9]-*.md"):
        try:
            file_id = int(path.name[:4])
            if file_id > max_id:
                max_id = file_id
        except ValueError:
            continue
    return max_id + 1


def slugify(title: str) -> str:
    """Convert a title to a filename-safe slug: lowercase, hyphens, no specials."""
    slug = title.lower().strip()
    slug = re.sub(r"[^a-z0-9\s_-]", "", slug)
    slug = re.sub(r"[\s_]+", "-", slug)
    slug = re.sub(r"-+", "-", slug)
    return slug.strip("-")


def generate_template(
    *,
    adr_id: int,
    title: str,
    status: str,
    author: str,
    adr_date: str,
    include_dependency: bool,
) -> str:
    """Generate ADR markdown content."""
    lines = [
        f"# ADR-{adr_id:04d}: {title}",
        "",
        f"**Status**: {status}",
        f"**Date**: {adr_date}",
        f"**Author**: {author}",
        "",
        "## Context",
        "",
        "What is the problem or decision we need to make?",
        "",
        "## Decision",
        "",
        "What did we decide?",
        "",
    ]

    if include_dependency:
        lines.extend([
            "## Dependency Details",
            "",
            "| Field | Value |",
            "|:------|:------|",
            "| Package | `package-name` |",
            "| Version | `>=X.Y,<X+1` |",
            "| License | MIT / Apache-2.0 / etc. |",
            "| PyPI downloads/month | ~N |",
            "| Maintainers | N active |",
            "| Transitive deps | N |",
            "| Last release | YYYY-MM-DD |",
            "| Known CVEs | None / list |",
            "",
        ])

    lines.extend([
        "## Alternatives Considered",
        "",
        "1. **Alternative A** — why rejected",
        "2. **Alternative B** — why rejected",
        "3. **stdlib approach** — why insufficient (required if adding external dep)",
        "",
        "## Consequences",
        "",
        "- What are the positive outcomes?",
        "- What are the risks or trade-offs?",
        "- What maintenance burden does this add?",
        "",
        "## References",
        "",
        "- Links to relevant issues, PRs, or docs",
        "",
    ])

    return "\n".join(lines)


def parse_status_from_file(filepath: Path) -> str:
    """Extract the Status field from an ADR file."""
    try:
        text = filepath.read_text(encoding="utf-8")
    except OSError:
        return "UNKNOWN"
    match = re.search(r"\*\*Status\*\*:\s*(\S+)", text)
    return match.group(1) if match else "UNKNOWN"


def title_from_filename(filename: str) -> str:
    """Extract a human-readable title from an ADR filename like 0001-my-title.md."""
    name = filename.removesuffix(".md")
    # Strip the NNNN- prefix
    if re.match(r"^\d{4}-", name):
        name = name[5:]
    return name.replace("-", " ").title()


# ---------------------------------------------------------------------------
# ADR document model and parsing
# ---------------------------------------------------------------------------


@dataclass
class AdrDocument:
    """Parsed representation of an ADR markdown file."""

    adr_id: int
    title: str
    status: str
    date: str
    author: str
    sections: dict[str, str] = field(default_factory=dict)
    filepath: Path = field(default_factory=lambda: Path())


def find_adr_file(decisionlog_dir: Path, adr_id: int) -> Path | None:
    """Find an ADR file by its numeric ID. Returns None if not found."""
    prefix = f"{adr_id:04d}-"
    for path in decisionlog_dir.glob(f"{prefix}*.md"):
        return path
    return None


def parse_adr_document(filepath: Path) -> AdrDocument:
    """Parse an ADR markdown file into a structured document."""
    text = filepath.read_text(encoding="utf-8")

    # Extract title from the heading line
    title_match = re.search(r"^#\s+ADR-\d{4}:\s*(.+)$", text, re.MULTILINE)
    title = title_match.group(1).strip() if title_match else title_from_filename(filepath.name)

    # Extract ID from filename
    adr_id = int(filepath.name[:4])

    # Extract metadata fields
    status = _extract_meta(text, "Status")
    adr_date = _extract_meta(text, "Date")
    author = _extract_meta(text, "Author")

    # Split into sections by ## headings
    sections = _parse_sections(text)

    return AdrDocument(
        adr_id=adr_id,
        title=title,
        status=status,
        date=adr_date,
        author=author,
        sections=sections,
        filepath=filepath,
    )


def _extract_meta(text: str, field_name: str) -> str:
    """Extract a **Field**: Value metadata line."""
    pattern = rf"\*\*{re.escape(field_name)}\*\*:\s*(.+)"
    match = re.search(pattern, text)
    return match.group(1).strip() if match else ""


def _parse_sections(text: str) -> dict[str, str]:
    """Split ADR content into sections keyed by ## heading name."""
    sections: dict[str, str] = {}
    # Find all ## headings and their positions
    headings = list(re.finditer(r"^##\s+(.+)$", text, re.MULTILINE))
    for i, heading in enumerate(headings):
        name = heading.group(1).strip()
        start = heading.end()
        end = headings[i + 1].start() if i + 1 < len(headings) else len(text)
        content = text[start:end].strip()
        sections[name] = content
    return sections


# ---------------------------------------------------------------------------
# ADR relationships and analysis
# ---------------------------------------------------------------------------


def extract_adr_references(text: str, self_id: int) -> list[int]:
    """Extract ADR IDs referenced in text, excluding the ADR's own ID."""
    ids = {int(m.group(1)) for m in re.finditer(r"ADR-(\d{4})", text)}
    ids.discard(self_id)
    return sorted(ids)


@dataclass
class AdrRelationship:
    """Compact summary of a related ADR."""

    adr_id: int
    title: str
    status: str


def resolve_relationships(
    references: list[int],
    decisionlog_dir: Path,
) -> list[AdrRelationship]:
    """Resolve ADR IDs to compact summaries."""
    results: list[AdrRelationship] = []
    for ref_id in references:
        path = find_adr_file(decisionlog_dir, ref_id)
        if path is None:
            results.append(AdrRelationship(ref_id, "(not found)", "UNKNOWN"))
            continue
        title = title_from_filename(path.name)
        status = parse_status_from_file(path)
        results.append(AdrRelationship(ref_id, title, status))
    return results


def read_dependency_specs(project_root: Path) -> str:
    """Read dependency and optional-dependency sections from pyproject.toml.

    Returns the raw text of the relevant sections, or empty string if missing.
    """
    pyproject = project_root / "pyproject.toml"
    if not pyproject.exists():
        return ""
    text = pyproject.read_text(encoding="utf-8")

    # Extract [project] dependencies, optional-dependencies, and [dependency-groups]
    sections: list[str] = []
    for pattern in (
        r"^dependencies\s*=\s*\[.*?\]",
        r"^\[project\.optional-dependencies\].*?(?=\n\[|\Z)",
        r"^\[dependency-groups\].*?(?=\n\[|\Z)",
    ):
        match = re.search(pattern, text, re.MULTILINE | re.DOTALL)
        if match:
            sections.append(match.group(0).strip())
    return "\n\n".join(sections)


ADR_ANALYSIS_PROMPT = """\
You are analyzing ADR-{adr_id:04d} for the Legion project. Your job is to compare this decision record against the actual codebase state and flag discrepancies.

## ADR Under Analysis

{adr_content}

{related_context}## Codebase Dependencies (pyproject.toml)

{dependency_specs}

## Instructions

Analyze concisely. Skip sections that have no findings.

### 1. Reality Check
Compare the ADR's claims to the codebase evidence above:
- Dependency ADRs: Is the package present? Does the version pin match? Is it in the correct group (runtime vs dev vs optional)?
- Architecture ADRs: Are the described patterns/files/locations consistent with what was decided?
- Status accuracy: Should PROPOSED be promoted to ACCEPTED? Should ACCEPTED be DEPRECATED?

### 2. Edge Cases & Risks
- Unstated assumptions or failure modes not covered by the decision
- Security implications not addressed in the ADR
- Version pin concerns (too loose, too tight, EOL risk)

### 3. Relationship Integrity
- Are referenced ADRs still valid (not deprecated/superseded)?
- Are there contradictions between this ADR and related ones?
- Are there missing references to ADRs that cover related concerns?

End with: **STATUS: CURRENT** (ADR matches reality) or **STATUS: DRIFT — {{summary of discrepancies}}**
"""


def build_adr_analysis_prompt(
    doc: AdrDocument,
    relationships: list[AdrRelationship],
    dependency_specs: str,
) -> str:
    """Assemble the analysis prompt for an ADR."""
    adr_content = doc.filepath.read_text(encoding="utf-8")

    related_context = ""
    if relationships:
        lines = ["## Related ADRs\n"]
        for rel in relationships:
            lines.append(f"- ADR-{rel.adr_id:04d}: {rel.title} [{rel.status}]")
        related_context = "\n".join(lines) + "\n\n"

    return ADR_ANALYSIS_PROMPT.format(
        adr_id=doc.adr_id,
        adr_content=adr_content,
        related_context=related_context,
        dependency_specs=dependency_specs or "(pyproject.toml not found)",
    )

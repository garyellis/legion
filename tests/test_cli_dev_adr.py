from __future__ import annotations

from pathlib import Path

from legion.internal.adr import (
    AdrDocument,
    build_adr_analysis_prompt,
    detect_next_id,
    extract_adr_references,
    find_adr_file,
    generate_template,
    parse_adr_document,
    parse_status_from_file,
    read_dependency_specs,
    resolve_relationships,
    slugify,
    title_from_filename,
)


# ---------------------------------------------------------------------------
# slugify
# ---------------------------------------------------------------------------


class TestSlugify:
    def test_basic(self) -> None:
        assert slugify("Add Redis Caching") == "add-redis-caching"

    def test_special_chars(self) -> None:
        assert slugify("mypy (type-checking)") == "mypy-type-checking"

    def test_extra_spaces(self) -> None:
        assert slugify("  lots   of   spaces  ") == "lots-of-spaces"

    def test_underscores(self) -> None:
        assert slugify("some_title_here") == "some-title-here"

    def test_already_slug(self) -> None:
        assert slugify("already-a-slug") == "already-a-slug"

    def test_empty(self) -> None:
        assert slugify("") == ""

    def test_numbers(self) -> None:
        assert slugify("pg18 upgrade") == "pg18-upgrade"


# ---------------------------------------------------------------------------
# detect_next_id
# ---------------------------------------------------------------------------


class TestDetectNextId:
    def test_empty_dir(self, tmp_path: Path) -> None:
        assert detect_next_id(tmp_path) == 0

    def test_with_existing(self, tmp_path: Path) -> None:
        (tmp_path / "0000-template.md").write_text("template")
        (tmp_path / "0001-first.md").write_text("first")
        (tmp_path / "0002-second.md").write_text("second")
        assert detect_next_id(tmp_path) == 3

    def test_gaps(self, tmp_path: Path) -> None:
        (tmp_path / "0000-template.md").write_text("template")
        (tmp_path / "0005-fifth.md").write_text("fifth")
        assert detect_next_id(tmp_path) == 6

    def test_non_adr_files_ignored(self, tmp_path: Path) -> None:
        (tmp_path / "README.md").write_text("readme")
        (tmp_path / "0001-adr.md").write_text("adr")
        assert detect_next_id(tmp_path) == 2


# ---------------------------------------------------------------------------
# generate_template
# ---------------------------------------------------------------------------


class TestGenerateTemplate:
    def test_without_dependency(self) -> None:
        content = generate_template(
            adr_id=9,
            title="Add Redis",
            status="PROPOSED",
            author="developer",
            adr_date="2026-04-04",
            include_dependency=False,
        )
        assert "# ADR-0009: Add Redis" in content
        assert "**Status**: PROPOSED" in content
        assert "**Date**: 2026-04-04" in content
        assert "**Author**: developer" in content
        assert "## Alternatives Considered" in content
        assert "## Dependency Details" not in content
        assert "Package" not in content

    def test_with_dependency(self) -> None:
        content = generate_template(
            adr_id=12,
            title="Add SQLAlchemy",
            status="ACCEPTED",
            author="gary",
            adr_date="2026-04-04",
            include_dependency=True,
        )
        assert "# ADR-0012: Add SQLAlchemy" in content
        assert "**Status**: ACCEPTED" in content
        assert "## Dependency Details" in content
        assert "| Package | `package-name` |" in content
        assert "| Known CVEs | None / list |" in content

    def test_id_zero_padded(self) -> None:
        content = generate_template(
            adr_id=3,
            title="Test",
            status="PROPOSED",
            author="dev",
            adr_date="2026-01-01",
            include_dependency=False,
        )
        assert "# ADR-0003: Test" in content


# ---------------------------------------------------------------------------
# parse_status_from_file
# ---------------------------------------------------------------------------


class TestParseStatus:
    def test_proposed(self, tmp_path: Path) -> None:
        f = tmp_path / "test.md"
        f.write_text("# ADR-0001: Test\n\n**Status**: PROPOSED\n**Date**: 2026-01-01\n")
        assert parse_status_from_file(f) == "PROPOSED"

    def test_accepted(self, tmp_path: Path) -> None:
        f = tmp_path / "test.md"
        f.write_text("# ADR-0002: Test\n\n**Status**: ACCEPTED\n**Date**: 2026-01-01\n")
        assert parse_status_from_file(f) == "ACCEPTED"

    def test_missing_status(self, tmp_path: Path) -> None:
        f = tmp_path / "test.md"
        f.write_text("# ADR-0003: Test\n\nNo status here.\n")
        assert parse_status_from_file(f) == "UNKNOWN"

    def test_nonexistent_file(self, tmp_path: Path) -> None:
        f = tmp_path / "nonexistent.md"
        assert parse_status_from_file(f) == "UNKNOWN"


# ---------------------------------------------------------------------------
# title_from_filename
# ---------------------------------------------------------------------------


class TestTitleFromFilename:
    def test_basic(self) -> None:
        assert title_from_filename("0001-mypy-type-checking.md") == "Mypy Type Checking"

    def test_single_word(self) -> None:
        assert title_from_filename("0002-vulture.md") == "Vulture"


# ---------------------------------------------------------------------------
# File creation (integration-style)
# ---------------------------------------------------------------------------


class TestFindAdrFile:
    def test_finds_existing_adr(self, tmp_path: Path) -> None:
        (tmp_path / "0001-first.md").write_text("first")
        (tmp_path / "0003-third.md").write_text("third")
        result = find_adr_file(tmp_path, 3)
        assert result is not None
        assert result.name == "0003-third.md"

    def test_returns_none_for_missing_id(self, tmp_path: Path) -> None:
        (tmp_path / "0001-first.md").write_text("first")
        assert find_adr_file(tmp_path, 99) is None

    def test_returns_none_in_empty_dir(self, tmp_path: Path) -> None:
        assert find_adr_file(tmp_path, 1) is None


# ---------------------------------------------------------------------------
# parse_adr_document
# ---------------------------------------------------------------------------


_SAMPLE_ADR = """\
# ADR-0005: Add Redis Caching

**Status**: ACCEPTED
**Date**: 2026-04-01
**Author**: gary

## Context

We need fast key-value lookups for session data.

## Decision

Use Redis as a caching layer.

```python
import redis
client = redis.Redis()
```

## Alternatives Considered

1. **Memcached** — fewer data structures
2. **stdlib dict** — not distributed

## Consequences

- Sub-millisecond reads
- Adds operational dependency

## References

- https://redis.io/docs
"""


class TestParseAdrDocument:
    def test_extracts_metadata(self, tmp_path: Path) -> None:
        f = tmp_path / "0005-add-redis-caching.md"
        f.write_text(_SAMPLE_ADR, encoding="utf-8")
        doc = parse_adr_document(f)
        assert doc.adr_id == 5
        assert doc.title == "Add Redis Caching"
        assert doc.status == "ACCEPTED"
        assert doc.date == "2026-04-01"
        assert doc.author == "gary"

    def test_extracts_sections(self, tmp_path: Path) -> None:
        f = tmp_path / "0005-add-redis-caching.md"
        f.write_text(_SAMPLE_ADR, encoding="utf-8")
        doc = parse_adr_document(f)
        assert "Context" in doc.sections
        assert "Decision" in doc.sections
        assert "Alternatives Considered" in doc.sections
        assert "Consequences" in doc.sections
        assert "References" in doc.sections

    def test_section_content_includes_code_blocks(self, tmp_path: Path) -> None:
        f = tmp_path / "0005-add-redis-caching.md"
        f.write_text(_SAMPLE_ADR, encoding="utf-8")
        doc = parse_adr_document(f)
        assert "```python" in doc.sections["Decision"]
        assert "redis.Redis()" in doc.sections["Decision"]

    def test_returns_dataclass(self, tmp_path: Path) -> None:
        f = tmp_path / "0005-add-redis-caching.md"
        f.write_text(_SAMPLE_ADR, encoding="utf-8")
        doc = parse_adr_document(f)
        assert isinstance(doc, AdrDocument)

    def test_filepath_stored(self, tmp_path: Path) -> None:
        f = tmp_path / "0005-add-redis-caching.md"
        f.write_text(_SAMPLE_ADR, encoding="utf-8")
        doc = parse_adr_document(f)
        assert doc.filepath == f

    def test_fallback_title_from_filename(self, tmp_path: Path) -> None:
        f = tmp_path / "0007-some-feature.md"
        f.write_text("**Status**: PROPOSED\n\n## Context\n\nSome context.\n", encoding="utf-8")
        doc = parse_adr_document(f)
        assert doc.title == "Some Feature"

    def test_missing_metadata_returns_empty(self, tmp_path: Path) -> None:
        f = tmp_path / "0099-bare.md"
        f.write_text("# ADR-0099: Bare\n\n## Context\n\nJust context.\n", encoding="utf-8")
        doc = parse_adr_document(f)
        assert doc.status == ""
        assert doc.date == ""
        assert doc.author == ""


# ---------------------------------------------------------------------------
# extract_adr_references
# ---------------------------------------------------------------------------


class TestExtractAdrReferences:
    def test_finds_references(self) -> None:
        text = "See ADR-0008 for registry. Also related to ADR-0001."
        assert extract_adr_references(text, self_id=9) == [1, 8]

    def test_excludes_self(self) -> None:
        text = "# ADR-0005: Something\nReferences ADR-0005 and ADR-0003."
        assert extract_adr_references(text, self_id=5) == [3]

    def test_no_references(self) -> None:
        assert extract_adr_references("No references here.", self_id=1) == []

    def test_deduplicates(self) -> None:
        text = "ADR-0002 is mentioned twice: ADR-0002."
        assert extract_adr_references(text, self_id=1) == [2]


# ---------------------------------------------------------------------------
# resolve_relationships
# ---------------------------------------------------------------------------


class TestResolveRelationships:
    def test_resolves_existing(self, tmp_path: Path) -> None:
        (tmp_path / "0001-first.md").write_text(
            "# ADR-0001: First\n\n**Status**: ACCEPTED\n"
        )
        rels = resolve_relationships([1], tmp_path)
        assert len(rels) == 1
        assert rels[0].adr_id == 1
        assert rels[0].title == "First"
        assert rels[0].status == "ACCEPTED"

    def test_missing_adr_marked_not_found(self, tmp_path: Path) -> None:
        rels = resolve_relationships([99], tmp_path)
        assert len(rels) == 1
        assert rels[0].adr_id == 99
        assert rels[0].title == "(not found)"

    def test_empty_refs(self, tmp_path: Path) -> None:
        assert resolve_relationships([], tmp_path) == []


# ---------------------------------------------------------------------------
# read_dependency_specs
# ---------------------------------------------------------------------------


class TestReadDependencySpecs:
    def test_reads_dependencies(self, tmp_path: Path) -> None:
        pyproject = tmp_path / "pyproject.toml"
        pyproject.write_text(
            '[project]\nname = "test"\n\n'
            'dependencies = [\n    "httpx>=0.27",\n]\n\n'
            "[dependency-groups]\n"
            'dev = [\n    "pytest>=9",\n]\n',
            encoding="utf-8",
        )
        result = read_dependency_specs(tmp_path)
        assert "httpx" in result
        assert "pytest" in result

    def test_missing_pyproject(self, tmp_path: Path) -> None:
        assert read_dependency_specs(tmp_path) == ""


# ---------------------------------------------------------------------------
# build_adr_analysis_prompt
# ---------------------------------------------------------------------------


class TestBuildAdrAnalysisPrompt:
    def test_includes_adr_content(self, tmp_path: Path) -> None:
        f = tmp_path / "0001-test.md"
        f.write_text("# ADR-0001: Test\n\n**Status**: ACCEPTED\n", encoding="utf-8")
        doc = parse_adr_document(f)
        prompt = build_adr_analysis_prompt(doc, [], "deps here")
        assert "ADR-0001" in prompt
        assert "deps here" in prompt

    def test_includes_related_adrs(self, tmp_path: Path) -> None:
        f = tmp_path / "0002-thing.md"
        f.write_text("# ADR-0002: Thing\n\n**Status**: PROPOSED\n", encoding="utf-8")
        doc = parse_adr_document(f)
        from legion.internal.adr import AdrRelationship

        rels = [AdrRelationship(1, "First", "ACCEPTED")]
        prompt = build_adr_analysis_prompt(doc, rels, "")
        assert "Related ADRs" in prompt
        assert "ADR-0001: First [ACCEPTED]" in prompt

    def test_no_related_section_when_empty(self, tmp_path: Path) -> None:
        f = tmp_path / "0003-solo.md"
        f.write_text("# ADR-0003: Solo\n\n**Status**: ACCEPTED\n", encoding="utf-8")
        doc = parse_adr_document(f)
        prompt = build_adr_analysis_prompt(doc, [], "deps")
        assert "Related ADRs" not in prompt

    def test_includes_reality_check_instructions(self, tmp_path: Path) -> None:
        f = tmp_path / "0001-test.md"
        f.write_text("# ADR-0001: Test\n\n**Status**: ACCEPTED\n", encoding="utf-8")
        doc = parse_adr_document(f)
        prompt = build_adr_analysis_prompt(doc, [], "")
        assert "Reality Check" in prompt
        assert "Edge Cases" in prompt
        assert "Relationship Integrity" in prompt
        assert "STATUS: CURRENT" in prompt
        assert "STATUS: DRIFT" in prompt


# ---------------------------------------------------------------------------
# File creation (integration-style)
# ---------------------------------------------------------------------------


class TestFileCreation:
    def test_creates_file_with_correct_name(self, tmp_path: Path) -> None:
        (tmp_path / "0000-template.md").write_text("template")
        (tmp_path / "0005-existing.md").write_text("existing")

        next_id = detect_next_id(tmp_path)
        slug = slugify("Add New Package")
        filename = f"{next_id:04d}-{slug}.md"
        filepath = tmp_path / filename

        content = generate_template(
            adr_id=next_id,
            title="Add New Package",
            status="PROPOSED",
            author="developer",
            adr_date="2026-04-04",
            include_dependency=True,
        )
        filepath.write_text(content, encoding="utf-8")

        assert filepath.exists()
        assert filepath.name == "0006-add-new-package.md"
        text = filepath.read_text()
        assert "# ADR-0006: Add New Package" in text
        assert "## Dependency Details" in text

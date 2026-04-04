from __future__ import annotations

from pathlib import Path

import pytest
import typer

from legion.cli_dev.commands.feature import feature_create, feature_handoff, feature_show
from legion.internal.feature import (
    build_feature_handoff_prompt,
    feature_docs_dir,
    feature_filepath,
    generate_feature_template,
    parse_feature_document,
    find_feature_file,
    title_from_filename,
    slugify_feature_title,
)


class TestSlugifyFeatureTitle:
    def test_basic(self) -> None:
        assert slugify_feature_title("Add Feature Briefs") == "add-feature-briefs"

    def test_special_chars(self) -> None:
        assert slugify_feature_title("Prompt Template (v1)") == "prompt-template-v1"

    def test_extra_spaces(self) -> None:
        assert slugify_feature_title("  lots   of   spaces  ") == "lots-of-spaces"


class TestFeaturePaths:
    def test_feature_docs_dir(self, tmp_path: Path) -> None:
        assert feature_docs_dir(tmp_path) == tmp_path / "docs" / "features"

    def test_feature_filepath(self, tmp_path: Path) -> None:
        assert feature_filepath(tmp_path, "Add Feature Briefs") == (
            tmp_path / "docs" / "features" / "add-feature-briefs.md"
        )

    def test_find_feature_file(self, tmp_path: Path) -> None:
        path = tmp_path / "docs" / "features" / "add-feature-briefs.md"
        path.parent.mkdir(parents=True)
        path.write_text("content", encoding="utf-8")
        assert find_feature_file(tmp_path, "Add Feature Briefs") == path

    def test_find_feature_file_missing(self, tmp_path: Path) -> None:
        assert find_feature_file(tmp_path, "Missing Brief") is None

    def test_title_from_filename(self) -> None:
        assert title_from_filename("add-feature-briefs.md") == "Add Feature Briefs"


class TestGenerateFeatureTemplate:
    def test_includes_required_sections(self) -> None:
        content = generate_feature_template(
            title="Add Feature Briefs",
            created_date="2026-04-04",
        )
        assert "# Feature Requirements Gate: Add Feature Briefs" in content
        assert "**Status**: DRAFT" in content
        assert "**Date**: 2026-04-04" in content
        assert "## Problem" in content
        assert "## Requirements Gate" in content
        assert "## Constraints" in content
        assert "## Interfaces And Data Shapes" in content
        assert "## Files And Ownership" in content
        assert "## Done Condition" in content
        assert "## Acceptance Criteria" in content
        assert "## Session Handoff" in content

    def test_includes_legion_specific_constraints(self) -> None:
        content = generate_feature_template(
            title="Add Feature Briefs",
            created_date="2026-04-04",
        )
        assert "Respect the Legion layer model" in content
        assert "Do not add dependencies without an ADR" in content
        assert "Prefer the smallest change that solves the problem" in content
        assert "usable as handoff context for a new session or sub-agent" in content


class TestParseFeatureDocument:
    def test_extracts_metadata_and_sections(self, tmp_path: Path) -> None:
        path = tmp_path / "docs" / "features" / "add-feature-briefs.md"
        path.parent.mkdir(parents=True)
        path.write_text(
            generate_feature_template(
                title="Add Feature Briefs",
                created_date="2026-04-04",
            ),
            encoding="utf-8",
        )
        doc = parse_feature_document(path)
        assert doc.title == "Add Feature Briefs"
        assert doc.status == "DRAFT"
        assert doc.date == "2026-04-04"
        assert "Problem" in doc.sections
        assert doc.filepath == path

    def test_fallback_title_from_filename(self, tmp_path: Path) -> None:
        path = tmp_path / "docs" / "features" / "some-feature.md"
        path.parent.mkdir(parents=True)
        path.write_text("**Status**: DRAFT\n**Date**: 2026-04-04\n", encoding="utf-8")
        doc = parse_feature_document(path)
        assert doc.title == "Some Feature"


class TestBuildFeatureHandoffPrompt:
    def test_includes_rules_and_brief(self, tmp_path: Path) -> None:
        path = tmp_path / "docs" / "features" / "add-feature-briefs.md"
        path.parent.mkdir(parents=True)
        path.write_text(
            generate_feature_template(
                title="Add Feature Briefs",
                created_date="2026-04-04",
            ),
            encoding="utf-8",
        )
        doc = parse_feature_document(path)
        prompt = build_feature_handoff_prompt(doc)
        assert "Use the brief below as the source of truth" in prompt
        assert "Feature: Add Feature Briefs" in prompt
        assert "uv run legion-dev architecture gate" in prompt
        assert "```markdown" in prompt


class TestFeatureCreate:
    def test_dry_run_creates_no_files(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(
            "legion.cli_dev.commands.feature._project_root", lambda: tmp_path
        )
        feature_create(title="Add Feature Briefs", dry_run=True)
        assert not (tmp_path / "docs" / "features").exists()

    def test_creates_feature_file(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(
            "legion.cli_dev.commands.feature._project_root", lambda: tmp_path
        )
        feature_create(title="Add Feature Briefs", dry_run=False)
        path = tmp_path / "docs" / "features" / "add-feature-briefs.md"
        assert path.exists()
        assert "# Feature Requirements Gate: Add Feature Briefs" in path.read_text(encoding="utf-8")

    def test_creates_parent_directory(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(
            "legion.cli_dev.commands.feature._project_root", lambda: tmp_path
        )
        feature_create(title="New Brief", dry_run=False)
        assert (tmp_path / "docs" / "features").is_dir()

    def test_refuses_overwrite(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(
            "legion.cli_dev.commands.feature._project_root", lambda: tmp_path
        )
        feature_create(title="Duplicate Brief", dry_run=False)
        with pytest.raises(typer.Exit):
            feature_create(title="Duplicate Brief", dry_run=False)


class TestFeatureShowAndHandoff:
    def test_show_renders_existing_brief(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(
            "legion.cli_dev.commands.feature._project_root", lambda: tmp_path
        )
        feature_create(title="Add Feature Briefs", dry_run=False)
        printed: list[str] = []
        raw: list[str] = []

        def fake_message(message: str, style: str = "") -> None:
            printed.append(message)

        def fake_print(*args, **kwargs) -> None:
            raw.append(str(args[0]))

        monkeypatch.setattr("legion.cli_dev.commands.feature.print_message", fake_message)
        monkeypatch.setattr("legion.cli_dev.commands.feature.console.print", fake_print)
        feature_show(title="Add Feature Briefs")

        assert "Add Feature Briefs" in printed[0]
        assert any("Status:" in line for line in printed)
        assert any("## Problem" in line for line in raw)

    def test_handoff_emits_prompt(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(
            "legion.cli_dev.commands.feature._project_root", lambda: tmp_path
        )
        feature_create(title="Add Feature Briefs", dry_run=False)
        captured: list[str] = []

        def fake_print(*args, **kwargs) -> None:
            captured.append(str(args[0]))

        monkeypatch.setattr("legion.cli_dev.commands.feature.console.print", fake_print)
        feature_handoff(title="Add Feature Briefs")

        assert len(captured) == 1
        assert "Use the brief below as the source of truth" in captured[0]
        assert "Feature: Add Feature Briefs" in captured[0]

    def test_show_missing_brief_errors(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(
            "legion.cli_dev.commands.feature._project_root", lambda: tmp_path
        )
        with pytest.raises(typer.Exit):
            feature_show(title="Missing Brief")

    def test_handoff_missing_brief_errors(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(
            "legion.cli_dev.commands.feature._project_root", lambda: tmp_path
        )
        with pytest.raises(typer.Exit):
            feature_handoff(title="Missing Brief")

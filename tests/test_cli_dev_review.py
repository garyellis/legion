from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest
import typer

from legion.cli_dev.commands.review import (
    _run_agent,
    find_git_root,
)
from legion.plumbing.subprocess import RunResult
from legion.internal.review import (
    build_review_prompt,
    read_claude_md,
)


class TestFindGitRoot:
    """Tests for git root detection."""

    def test_returns_path_on_success(self) -> None:
        with patch("legion.plumbing.subprocess.subprocess.run") as mock_run:
            mock_run.return_value.returncode = 0
            mock_run.return_value.stdout = "/home/user/repo\n"
            mock_run.return_value.stderr = ""
            result = find_git_root()
            assert result == Path("/home/user/repo")

    def test_returns_none_outside_git_repo(self) -> None:
        with patch("legion.plumbing.subprocess.subprocess.run") as mock_run:
            mock_run.return_value.returncode = 128
            mock_run.return_value.stdout = ""
            mock_run.return_value.stderr = ""
            result = find_git_root()
            assert result is None


class TestReadClaudeMd:
    """Tests for CLAUDE.md reading."""

    def test_reads_existing_file(self, tmp_path: Path) -> None:
        claude_md = tmp_path / "CLAUDE.md"
        claude_md.write_text("# Project Rules\nDo not break things.", encoding="utf-8")
        result = read_claude_md(tmp_path)
        assert "Project Rules" in result
        assert "Do not break things" in result

    def test_returns_empty_when_missing(self, tmp_path: Path) -> None:
        result = read_claude_md(tmp_path)
        assert result == ""


class TestBuildReviewPrompt:
    """Tests for prompt assembly."""

    def test_includes_rules(self) -> None:
        prompt = build_review_prompt(
            rules="No upward imports allowed.",
            diff="+ import legion.core.foo",
            diff_type="staged changes",
        )
        assert "No upward imports allowed." in prompt

    def test_includes_diff_content(self) -> None:
        diff = "+from legion.services import thing"
        prompt = build_review_prompt(
            rules="some rules",
            diff=diff,
            diff_type="staged changes",
        )
        assert diff in prompt

    def test_includes_diff_type(self) -> None:
        prompt = build_review_prompt(
            rules="rules",
            diff="some diff",
            diff_type="pull request (branch changes vs main)",
        )
        assert "pull request (branch changes vs main)" in prompt

    def test_includes_checklist_sections(self) -> None:
        prompt = build_review_prompt(rules="", diff="", diff_type="test")
        assert "## Architecture" in prompt
        assert "## Code Quality" in prompt
        assert "## Security" in prompt
        assert "## Testing" in prompt
        assert "VERDICT:" in prompt

    def test_includes_specific_checks(self) -> None:
        prompt = build_review_prompt(rules="", diff="", diff_type="test")
        assert "Layer violations" in prompt
        assert "from __future__ import annotations" in prompt
        assert "eval()/exec()/pickle.loads()" in prompt
        assert "Hardcoded credentials" in prompt


class TestRunAgent:
    """Tests for the AI agent CLI invocation wrapper."""

    def test_missing_agent_binary_exits(self) -> None:
        with patch("legion.plumbing.agents.find_on_path", return_value=None):
            with pytest.raises(typer.Exit) as exc_info:
                _run_agent("test prompt", "claude")
            assert exc_info.value.exit_code == 1

    def test_unknown_agent_exits(self) -> None:
        with pytest.raises(typer.Exit) as exc_info:
            _run_agent("test prompt", "nonexistent")
        assert exc_info.value.exit_code == 1

    def test_claude_agent_runs_correct_command(self) -> None:
        mock_result = RunResult(returncode=0, stdout="# Analysis\nLooks good.", stderr="")
        with (
            patch("legion.plumbing.agents.find_on_path", return_value="/usr/bin/claude"),
            patch("legion.plumbing.agents.run_capture_text", return_value=mock_result) as mock_run,
        ):
            _run_agent("test prompt", "claude")
            mock_run.assert_called_once_with(
                ["claude", "-p", "test prompt"],
            )

    def test_codex_agent_runs_correct_command(self) -> None:
        mock_result = RunResult(returncode=0, stdout="# Review\nAll clear.", stderr="")
        with (
            patch("legion.plumbing.agents.find_on_path", return_value="/usr/bin/codex"),
            patch("legion.plumbing.agents.run_capture_text", return_value=mock_result) as mock_run,
        ):
            _run_agent("test prompt", "codex")
            mock_run.assert_called_once_with(
                ["codex", "exec", "test prompt"],
            )

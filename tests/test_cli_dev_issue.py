from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import pytest
import typer
from rich.table import Table

from legion.cli_dev.commands.issue import (
    _build_issue_handoff_prompt,
    _feature_issue_import_from_path,
    issue_claim,
    issue_close,
    issue_comment,
    issue_create,
    issue_discover,
    issue_handoff,
    issue_import_features,
    issue_list,
    issue_show,
    issue_update,
    issue_validate,
)
from legion.core.github.issues import CreateGitHubIssue, GitHubIssue, GitHubIssueComment, GitHubIssueNotFoundError


def _issue(
    number: int,
    title: str,
    *,
    state: str = "open",
    assignees: tuple[str, ...] = (),
    labels: tuple[str, ...] = ("ready",),
    body: str | None = None,
) -> GitHubIssue:
    return GitHubIssue(
        number=number,
        title=title,
        body=body if body is not None else _valid_issue_body(title),
        state=state,
        html_url=f"https://github.com/acme/legion/issues/{number}",
        created_at="2026-04-25T00:00:00Z",
        updated_at="2026-04-25T00:00:00Z",
        labels=labels,
        assignees=assignees,
    )


@dataclass
class FakeIssuesClient:
    issues: list[GitHubIssue]
    comments: list[GitHubIssueComment] = field(default_factory=list)

    def create_issue(self, payload: CreateGitHubIssue) -> GitHubIssue:
        issue = GitHubIssue(
            number=len(self.issues) + 1,
            title=payload.title,
            body=payload.body,
            state="open",
            html_url=f"https://github.com/acme/legion/issues/{len(self.issues) + 1}",
            created_at="2026-04-25T00:00:00Z",
            updated_at="2026-04-25T00:00:00Z",
            labels=payload.labels,
            assignees=payload.assignees,
        )
        self.issues.append(issue)
        return issue

    def list_issues(
        self,
        *,
        state: str = "open",
        labels: tuple[str, ...] = (),
        limit: int = 100,
    ) -> tuple[GitHubIssue, ...]:
        return tuple(self.issues[:limit])

    def resolve_issue(
        self,
        reference: str,
        *,
        state: str = "open",
        labels: tuple[str, ...] = (),
    ) -> GitHubIssue:
        for issue in self.issues:
            if reference not in {str(issue.number), f"#{issue.number}", issue.title}:
                continue
            if labels and not all(label in issue.labels for label in labels):
                continue
            if state != "all" and issue.state != state:
                continue
            return issue
        raise GitHubIssueNotFoundError(f"GitHub issue not found: {reference}")

    def search_issues_by_title(
        self,
        title: str,
        *,
        state: str = "open",
        labels: tuple[str, ...] = (),
        limit: int = 100,
    ) -> tuple[GitHubIssue, ...]:
        words = title.lower().split()
        matches = []
        for issue in self.issues:
            if state != "all" and issue.state != state:
                continue
            if labels and not all(label in issue.labels for label in labels):
                continue
            issue_title = issue.title.lower()
            if all(word in issue_title for word in words):
                matches.append(issue)
        return tuple(matches[:limit])

    def update_issue(
        self,
        number: int,
        *,
        title: str | None = None,
        body: str | None = None,
        state: str | None = None,
        labels: tuple[str, ...] | None = None,
        assignees: tuple[str, ...] | None = None,
    ) -> GitHubIssue:
        issue = self.resolve_issue(str(number))
        updated = GitHubIssue(
            number=issue.number,
            title=title or issue.title,
            body=body if body is not None else issue.body,
            state=state or issue.state,
            html_url=issue.html_url,
            created_at=issue.created_at,
            updated_at=issue.updated_at,
            labels=labels if labels is not None else issue.labels,
            assignees=assignees if assignees is not None else issue.assignees,
        )
        self.issues = [updated if item.number == number else item for item in self.issues]
        return updated

    def add_comment(self, number: int, body: str) -> GitHubIssueComment:
        self.resolve_issue(str(number))
        comment = GitHubIssueComment(
            id=100 + number,
            body=body,
            html_url=f"https://github.com/acme/legion/issues/{number}#issuecomment-1",
            created_at="2026-04-25T00:00:00Z",
        )
        self.comments.append(comment)
        return comment

    def close_issue(self, number: int) -> GitHubIssue:
        return self.update_issue(number, state="closed")


def _valid_issue_body(title: str = "Work") -> str:
    return f"""# {title}

**Status**: READY
**Date**: 2026-04-25

## Problem

- Current behavior: Existing flow needs work.
- Impact: Agents need crisp scope.

## Target

- Behavior: The requested behavior is implemented.
- Non-goals: Broad refactors.

## Repo Context

- Files: `legion/cli_dev/commands/issue.py`.
- Constraints: Follow layer rules.
- Interfaces/data: CLI command behavior.

## Acceptance Criteria

- Issue command behavior is covered by tests.

## Verification Plan

- Targeted tests: `uv run pytest tests/test_cli_dev_issue.py`.
- Architecture gate: `uv run legion-dev architecture gate`.

## Open Questions

None.
"""


def test_issue_create_uses_github_client(monkeypatch: pytest.MonkeyPatch) -> None:
    client = FakeIssuesClient(issues=[])
    messages: list[str] = []
    monkeypatch.setattr("legion.cli_dev.commands.issue._issue_client", lambda: client)
    monkeypatch.setattr("legion.cli_dev.commands.issue.print_message", lambda message, style="": messages.append(message))

    issue_create(title="Add GitHub issue commands", body="body", label=["ready"], dry_run=False)

    assert client.issues[0].title == "Add GitHub issue commands"
    assert any("#1" in message for message in messages)


def test_issue_create_reads_body_file(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    client = FakeIssuesClient(issues=[])
    body_file = tmp_path / "issue.md"
    body_file.write_text("## Problem\n\nUse this body.\n", encoding="utf-8")
    monkeypatch.setattr("legion.cli_dev.commands.issue._issue_client", lambda: client)
    monkeypatch.setattr("legion.cli_dev.commands.issue.print_message", lambda message, style="": None)

    issue_create(title="Draft from file", body=None, body_file=body_file, label=["ready"], dry_run=False)

    assert client.issues[0].body == "## Problem\n\nUse this body.\n"
    assert client.issues[0].labels == ("ready",)


def test_issue_create_prints_template(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: list[str] = []
    monkeypatch.setattr("legion.cli_dev.commands.issue.console.print", lambda value, *args, **kwargs: captured.append(str(value)))

    issue_create(
        title="Shape issue flow",
        body=None,
        body_file=None,
        label=None,
        print_template=True,
        dry_run=False,
    )

    assert "# Shape issue flow" in captured[0]
    assert "## Target" in captured[0]
    assert "## Repo Context" in captured[0]
    assert "## Open Questions" in captured[0]


def test_issue_discover_creates_new_discovered_issue(monkeypatch: pytest.MonkeyPatch) -> None:
    client = FakeIssuesClient(issues=[])
    messages: list[str] = []
    monkeypatch.setattr("legion.cli_dev.commands.issue._issue_client", lambda: client)
    monkeypatch.setattr("legion.cli_dev.commands.issue.print_message", lambda message, style="": messages.append(message))

    issue_discover(
        title="Capture missing alert fixture",
        kind="bug",
        source="manual audit",
        blocks="#34",
        evidence=["Fixture crashes on empty alert"],
        file=["tests/test_cli_dev_issue.py"],
        label=["test-gap"],
        dry_run=False,
        allow_duplicate=False,
    )

    created = client.issues[0]
    assert created.title == "Capture missing alert fixture"
    assert created.labels == ("discovered-work", "kind:bug", "test-gap")
    assert "- Source: manual audit" in created.body
    assert "- Blocks: #34" in created.body
    assert "- Fixture crashes on empty alert" in created.body
    assert "- Files: `tests/test_cli_dev_issue.py`" in created.body
    assert any("Created discovered issue" in message for message in messages)


def test_issue_discover_reuses_open_duplicate(monkeypatch: pytest.MonkeyPatch) -> None:
    client = FakeIssuesClient(issues=[_issue(7, "Capture missing alert fixture")])
    messages: list[str] = []
    monkeypatch.setattr("legion.cli_dev.commands.issue._issue_client", lambda: client)
    monkeypatch.setattr("legion.cli_dev.commands.issue.print_message", lambda message, style="": messages.append(message))

    issue_discover(
        title="  capture   missing ALERT fixture ",
        kind="follow-up",
        source="#34",
        blocks="#40",
        evidence=["Observed while reviewing tests"],
        file=[],
        label=None,
        dry_run=False,
        allow_duplicate=False,
    )

    assert len(client.issues) == 1
    assert len(client.comments) == 1
    assert "Additional Discovery Context" in client.comments[0].body
    assert "- Source: #34" in client.comments[0].body
    assert "- Blocks: #40" in client.comments[0].body
    assert any("Reused existing issue" in message for message in messages)


def test_issue_discover_reports_closed_duplicate_without_creating(monkeypatch: pytest.MonkeyPatch) -> None:
    client = FakeIssuesClient(issues=[_issue(3, "Capture missing alert fixture", state="closed")])
    messages: list[str] = []
    monkeypatch.setattr("legion.cli_dev.commands.issue._issue_client", lambda: client)
    monkeypatch.setattr("legion.cli_dev.commands.issue.print_message", lambda message, style="": messages.append(message))

    issue_discover(
        title="Capture missing alert fixture",
        kind="cleanup",
        source="",
        blocks="",
        evidence=None,
        file=None,
        label=None,
        dry_run=False,
        allow_duplicate=False,
    )

    assert len(client.issues) == 1
    assert client.comments == []
    assert any("Closed duplicate found" in message for message in messages)


def test_issue_discover_dry_run_does_not_create_or_comment(monkeypatch: pytest.MonkeyPatch) -> None:
    client = FakeIssuesClient(issues=[_issue(1, "Source issue")])
    rendered: list[str] = []
    monkeypatch.setattr("legion.cli_dev.commands.issue._issue_client", lambda: client)
    monkeypatch.setattr("legion.cli_dev.commands.issue.print_message", lambda message, style="": rendered.append(message))
    monkeypatch.setattr("legion.cli_dev.commands.issue.console.print", lambda value, *args, **kwargs: rendered.append(str(value)))

    issue_discover(
        title="New dry-run discovery",
        kind="oversight",
        source="#1",
        blocks="",
        evidence=["Would otherwise create"],
        file=["legion/cli_dev/commands/issue.py"],
        label=["triage"],
        dry_run=True,
        allow_duplicate=False,
    )

    assert [issue.title for issue in client.issues] == ["Source issue"]
    assert client.comments == []
    assert any("Dry run" in item for item in rendered)
    assert any("New dry-run discovery" in item for item in rendered)


def test_issue_discover_comments_back_on_source_issue(monkeypatch: pytest.MonkeyPatch) -> None:
    client = FakeIssuesClient(issues=[_issue(1, "Source issue")])
    monkeypatch.setattr("legion.cli_dev.commands.issue._issue_client", lambda: client)
    monkeypatch.setattr("legion.cli_dev.commands.issue.print_message", lambda message, style="": None)

    issue_discover(
        title="Discovered from source",
        kind="follow-up",
        source="#1",
        blocks="",
        evidence=None,
        file=None,
        label=None,
        dry_run=False,
        allow_duplicate=False,
    )

    assert len(client.issues) == 2
    assert len(client.comments) == 1
    assert "Linked discovered issue: #2" in client.comments[0].body
    assert client.comments[0].html_url.startswith("https://github.com/acme/legion/issues/1")


def test_issue_import_features_creates_labeled_issues(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    root = tmp_path
    features_dir = root / "docs" / "features"
    features_dir.mkdir(parents=True)
    (features_dir / "first-feature.md").write_text(
        "# Feature Requirements Gate: First feature\n\n## Problem\n\nDo the thing.\n",
        encoding="utf-8",
    )
    (features_dir / ".gitkeep").write_text("", encoding="utf-8")
    client = FakeIssuesClient(issues=[])
    messages: list[str] = []
    monkeypatch.setattr("legion.cli_dev.commands.issue._project_root", lambda: root)
    monkeypatch.setattr("legion.cli_dev.commands.issue._issue_client", lambda: client)
    monkeypatch.setattr("legion.cli_dev.commands.issue.print_message", lambda message, style="": messages.append(message))

    issue_import_features(path=features_dir, label=["roadmap"], dry_run=False, allow_duplicates=False)

    assert client.issues[0].title == "First feature"
    assert client.issues[0].labels == ("legion-feature", "roadmap")
    assert "Do the thing." in client.issues[0].body
    assert "Imported from `docs/features/first-feature.md`." in client.issues[0].body
    assert any("Imported feature issues" in message for message in messages)


def test_issue_import_features_dry_run_renders_table(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    root = tmp_path
    features_dir = root / "docs" / "features"
    features_dir.mkdir(parents=True)
    (features_dir / "fallback-title.md").write_text("# Plain title\n\nBody\n", encoding="utf-8")
    captured: list[Table] = []
    monkeypatch.setattr("legion.cli_dev.commands.issue._project_root", lambda: root)
    monkeypatch.setattr("legion.cli_dev.commands.issue.console.print", lambda value, *args, **kwargs: captured.append(value))
    monkeypatch.setattr("legion.cli_dev.commands.issue.print_message", lambda message, style="": None)

    issue_import_features(path=features_dir, label=None, dry_run=True, allow_duplicates=False)

    table = captured[0]
    assert [column.header for column in table.columns] == ["Title", "Labels", "Source"]
    assert table.columns[0]._cells == ["Plain title"]
    assert table.columns[1]._cells == ["legion-feature"]
    assert table.columns[2]._cells == ["docs/features/fallback-title.md"]


def test_issue_import_features_skips_existing_imported_issues(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    root = tmp_path
    features_dir = root / "docs" / "features"
    features_dir.mkdir(parents=True)
    (features_dir / "first-feature.md").write_text(
        "# Feature Requirements Gate: First feature\n\nBody\n",
        encoding="utf-8",
    )
    client = FakeIssuesClient(issues=[_issue(9, "First feature", labels=("legion-feature",))])
    messages: list[str] = []
    monkeypatch.setattr("legion.cli_dev.commands.issue._project_root", lambda: root)
    monkeypatch.setattr("legion.cli_dev.commands.issue._issue_client", lambda: client)
    monkeypatch.setattr("legion.cli_dev.commands.issue.print_message", lambda message, style="": messages.append(message))

    issue_import_features(path=features_dir, label=None, dry_run=False, allow_duplicates=False)

    assert len(client.issues) == 1
    assert any("Skipped existing imported issues" in message for message in messages)


def test_feature_issue_import_uses_filename_when_markdown_has_no_title(tmp_path: Path) -> None:
    path = tmp_path / "docs" / "features" / "needs-title.md"
    path.parent.mkdir(parents=True)
    path.write_text("Body only\n", encoding="utf-8")

    item = _feature_issue_import_from_path(path, root=tmp_path, labels=("legion-feature",))

    assert item.title == "Needs Title"


def test_issue_list_renders_table(monkeypatch: pytest.MonkeyPatch) -> None:
    client = FakeIssuesClient(issues=[_issue(2, "Second"), _issue(1, "First")])
    captured: list[Table] = []
    monkeypatch.setattr("legion.cli_dev.commands.issue._issue_client", lambda: client)
    monkeypatch.setattr("legion.cli_dev.commands.issue.console.print", lambda value, *args, **kwargs: captured.append(value))

    issue_list(state="open", label=["ready"], limit=50)

    table = captured[0]
    assert [column.header for column in table.columns] == ["Number", "State", "Title", "Labels", "URL"]
    assert table.columns[0]._cells == ["#2", "#1"]
    assert table.columns[2]._cells == ["Second", "First"]


def test_issue_show_and_handoff(monkeypatch: pytest.MonkeyPatch) -> None:
    client = FakeIssuesClient(issues=[_issue(3, "Do work")])
    messages: list[str] = []
    raw: list[str] = []
    monkeypatch.setattr("legion.cli_dev.commands.issue._issue_client", lambda: client)
    monkeypatch.setattr("legion.cli_dev.commands.issue.print_message", lambda message, style="": messages.append(message))
    monkeypatch.setattr("legion.cli_dev.commands.issue.console.print", lambda value, *args, **kwargs: raw.append(str(value)))

    issue_show(reference="#3")
    issue_handoff(reference="Do work")

    assert any("Number:" in message for message in messages)
    assert any("Existing flow needs work." in value for value in raw)
    assert any("You are continuing Legion issue work" in value for value in raw)


def test_issue_validate_reports_ready_issue(monkeypatch: pytest.MonkeyPatch) -> None:
    client = FakeIssuesClient(issues=[_issue(8, "Ready")])
    messages: list[str] = []
    monkeypatch.setattr("legion.cli_dev.commands.issue._issue_client", lambda: client)
    monkeypatch.setattr("legion.cli_dev.commands.issue.print_message", lambda message, style="": messages.append(message))

    issue_validate(reference="#8")

    assert any("ready for handoff" in message for message in messages)


def test_issue_validate_fails_draft_template(monkeypatch: pytest.MonkeyPatch) -> None:
    client = FakeIssuesClient(issues=[_issue(8, "Draft", body="**Status**: DRAFT\n\n## Problem\n\n- Current behavior:")])
    monkeypatch.setattr("legion.cli_dev.commands.issue._issue_client", lambda: client)

    with pytest.raises(typer.Exit):
        issue_validate(reference="#8")


def test_issue_handoff_blocks_draft_without_override(monkeypatch: pytest.MonkeyPatch) -> None:
    client = FakeIssuesClient(issues=[_issue(8, "Draft", body="**Status**: DRAFT\n")])
    raw: list[str] = []
    monkeypatch.setattr("legion.cli_dev.commands.issue._issue_client", lambda: client)
    monkeypatch.setattr("legion.cli_dev.commands.issue.console.print", lambda value, *args, **kwargs: raw.append(str(value)))

    with pytest.raises(typer.Exit):
        issue_handoff(reference="#8", allow_draft=False)

    issue_handoff(reference="#8", allow_draft=True)
    assert any("You are continuing Legion issue work" in value for value in raw)


def test_issue_claim_comment_and_close(monkeypatch: pytest.MonkeyPatch) -> None:
    client = FakeIssuesClient(issues=[_issue(4, "Lifecycle", assignees=("alice",))])
    messages: list[str] = []
    monkeypatch.setenv("GITHUB_ACTOR", "gary")
    monkeypatch.setattr("legion.cli_dev.commands.issue._issue_client", lambda: client)
    monkeypatch.setattr("legion.cli_dev.commands.issue.print_message", lambda message, style="": messages.append(message))

    issue_claim(reference="#4", assignee="", label="in-progress")
    issue_comment(reference="#4", body="Taking this.")
    issue_close(reference="#4", verified="uv run pytest tests/test_cli_dev_issue.py passed", allow_unverified=False)

    updated = client.resolve_issue("#4", state="all")
    assert updated.state == "closed"
    assert updated.assignees == ("alice", "gary")
    assert "in-progress" in updated.labels
    assert client.comments[-1].body == "## Verification\n\nuv run pytest tests/test_cli_dev_issue.py passed"
    assert any("Added comment" in message for message in messages)


def test_issue_close_requires_verification(monkeypatch: pytest.MonkeyPatch) -> None:
    client = FakeIssuesClient(issues=[_issue(10, "Lifecycle")])
    monkeypatch.setattr("legion.cli_dev.commands.issue._issue_client", lambda: client)

    with pytest.raises(typer.Exit):
        issue_close(reference="#10", verified="", allow_unverified=False)

    issue_close(reference="#10", verified="", allow_unverified=True)
    assert client.resolve_issue("#10", state="all").state == "closed"


def test_issue_update_replaces_body_from_file(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    client = FakeIssuesClient(issues=[_issue(5, "Refine")])
    body_file = tmp_path / "issue.md"
    body_file.write_text("## Problem\n\nRefined body.\n", encoding="utf-8")
    messages: list[str] = []
    monkeypatch.setattr("legion.cli_dev.commands.issue._issue_client", lambda: client)
    monkeypatch.setattr("legion.cli_dev.commands.issue.print_message", lambda message, style="": messages.append(message))

    issue_update(reference="#5", body=None, body_file=body_file)

    updated = client.resolve_issue("#5")
    assert updated.body == "## Problem\n\nRefined body.\n"
    assert any("Updated issue" in message for message in messages)


def test_issue_update_requires_body_source(monkeypatch: pytest.MonkeyPatch) -> None:
    client = FakeIssuesClient(issues=[_issue(6, "Missing body")])
    monkeypatch.setattr("legion.cli_dev.commands.issue._issue_client", lambda: client)

    with pytest.raises(typer.Exit):
        issue_update(reference="#6", body=None, body_file=None)


def test_issue_missing_reference_exits(monkeypatch: pytest.MonkeyPatch) -> None:
    client = FakeIssuesClient(issues=[])
    monkeypatch.setattr("legion.cli_dev.commands.issue._issue_client", lambda: client)

    with pytest.raises(typer.Exit):
        issue_show(reference="Missing")


def test_handoff_prompt_contains_issue_context() -> None:
    prompt = _build_issue_handoff_prompt(_issue(7, "Implement thing"))
    assert "Issue: #7 Implement thing" in prompt
    assert "URL: https://github.com/acme/legion/issues/7" in prompt
    assert "```markdown" in prompt

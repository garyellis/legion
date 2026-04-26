from __future__ import annotations

import os
import re
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Annotated

import typer
from rich.table import Table

from legion.cli_dev.views import console, print_message, render_error
from legion.core.github.issues import (
    CreateGitHubIssue,
    GitHubIssue,
    GitHubIssueAmbiguousError,
    GitHubIssueConfigurationError,
    GitHubIssueError,
    GitHubIssueNotFoundError,
    GitHubIssuesClient,
    create_github_issues_client,
    resolve_github_repository,
)
from legion.plumbing.registry import register_command

DEFAULT_FEATURE_IMPORT_LABEL = "legion-feature"
DISCOVERED_WORK_LABEL = "discovered-work"
DISCOVERY_KINDS = ("bug", "follow-up", "dependency", "oversight", "cleanup")

REQUIRED_HANDOFF_SECTIONS = (
    "Problem",
    "Target",
    "Repo Context",
    "Acceptance Criteria",
    "Verification Plan",
    "Open Questions",
)

PLACEHOLDER_PHRASES = (
    "What is failing, missing, or inconsistent today?",
    "What observable behavior should exist when this is done?",
    "Implementation order, file targets, banned shortcuts, validation commands, and exact success criteria.",
)


@dataclass(frozen=True)
class FeatureIssueImport:
    """Feature markdown document prepared for GitHub issue creation."""

    title: str
    body: str
    labels: tuple[str, ...]
    source_path: Path


@dataclass(frozen=True)
class IssueValidationResult:
    """Readiness result for issue handoff and closure."""

    ok: bool
    failures: tuple[str, ...]
    warnings: tuple[str, ...] = ()


@dataclass(frozen=True)
class DiscoveryContext:
    """Structured context for deterministic discovered work intake."""

    title: str
    kind: str
    source: str
    blocks: str
    evidence: tuple[str, ...]
    files: tuple[str, ...]
    labels: tuple[str, ...]


def _project_root() -> Path:
    """Return the project root (parent of the 'legion' package directory)."""
    return Path(__file__).resolve().parent.parent.parent.parent


def _issue_client() -> GitHubIssuesClient:
    """Build the configured GitHub Issues client for CLI commands."""
    return create_github_issues_client(cwd=_project_root())


@register_command("issue", "create")
def issue_create(
    title: Annotated[str, typer.Argument(help="GitHub issue title")],
    body: Annotated[str | None, typer.Option("--body", "-b", help="GitHub issue body")] = None,
    body_file: Annotated[
        Path | None,
        typer.Option("--body-file", help="Read the GitHub issue body from this markdown file"),
    ] = None,
    label: Annotated[
        list[str] | None,
        typer.Option("--label", "-l", help="Label to add to the issue"),
    ] = None,
    print_template: Annotated[
        bool,
        typer.Option("--print-template", help="Print the structured issue template and exit"),
    ] = False,
    dry_run: Annotated[
        bool,
        typer.Option("--dry-run", help="Show what would be created without calling GitHub"),
    ] = False,
) -> None:
    """Create a GitHub issue."""
    if print_template:
        console.print(_generate_issue_body_template(title), markup=False, soft_wrap=True)
        return

    issue_body = _resolve_issue_body_or_exit(title=title, body=body, body_file=body_file)
    labels = tuple(label or ())
    if dry_run:
        _render_create_dry_run(title=title, body=issue_body, labels=labels)
        return

    try:
        issue = _issue_client().create_issue(CreateGitHubIssue(title=title, body=issue_body, labels=labels))
    except GitHubIssueError as exc:
        _render_issue_error(exc)
        raise typer.Exit(code=1) from exc

    print_message(f"[bold]Created issue:[/bold] [green]#{issue.number}[/green] {issue.html_url}")
    print_message(f"Next: `legion-dev issue handoff \"#{issue.number}\"`", style="dim")


@register_command("issue", "discover")
def issue_discover(
    title: Annotated[str, typer.Argument(help="Discovered work title")],
    kind: Annotated[
        str,
        typer.Option("--kind", help="Discovered work kind: bug, follow-up, dependency, oversight, cleanup"),
    ] = "follow-up",
    source: Annotated[
        str,
        typer.Option("--source", help="Source issue reference or context that discovered this work"),
    ] = "",
    blocks: Annotated[
        str,
        typer.Option("--blocks", help="Issue reference or work item blocked by this discovery"),
    ] = "",
    evidence: Annotated[
        list[str] | None,
        typer.Option("--evidence", help="Evidence supporting the discovered work"),
    ] = None,
    file: Annotated[
        list[str] | None,
        typer.Option("--file", help="Relevant repo file path"),
    ] = None,
    label: Annotated[
        list[str] | None,
        typer.Option("--label", "-l", help="Additional label to add to the issue"),
    ] = None,
    dry_run: Annotated[
        bool,
        typer.Option("--dry-run", help="Show what would happen without creating or commenting"),
    ] = False,
    allow_duplicate: Annotated[
        bool,
        typer.Option("--allow-duplicate", help="Create a new issue even when an exact closed duplicate exists"),
    ] = False,
) -> None:
    """Create or reuse a deterministic discovered-work issue."""
    normalized_kind = kind.strip().lower()
    if normalized_kind not in DISCOVERY_KINDS:
        render_error(
            f"Unsupported discovery kind: {kind}",
            hint=f"Use one of: {', '.join(DISCOVERY_KINDS)}.",
        )
        raise typer.Exit(code=1)

    context = DiscoveryContext(
        title=title,
        kind=normalized_kind,
        source=source.strip(),
        blocks=blocks.strip(),
        evidence=tuple(item.strip() for item in evidence or () if item.strip()),
        files=tuple(item.strip() for item in file or () if item.strip()),
        labels=_discovered_issue_labels(normalized_kind, label),
    )

    try:
        client = _issue_client()
        open_match, closed_match = _find_discovery_duplicates(client, title)
        if dry_run:
            _render_discovery_dry_run(
                context=context,
                open_match=open_match,
                closed_match=closed_match,
                allow_duplicate=allow_duplicate,
            )
            return

        if open_match is not None:
            comment = _discovery_reuse_comment(context)
            if comment:
                client.add_comment(open_match.number, comment)
            _comment_source_backlink(client, context.source, open_match)
            print_message(
                f"[bold]Reused existing issue:[/bold] [green]#{open_match.number}[/green] {open_match.html_url}"
            )
            return

        if closed_match is not None and not allow_duplicate:
            print_message(
                "[bold yellow]Closed duplicate found; no issue created:[/bold yellow] "
                f"#{closed_match.number} {closed_match.html_url}"
            )
            print_message("Pass --allow-duplicate to create a new discovered-work issue anyway.", style="dim")
            return

        issue = client.create_issue(
            CreateGitHubIssue(
                title=context.title,
                body=_generate_discovery_issue_body(context),
                labels=context.labels,
            )
        )
        _comment_source_backlink(client, context.source, issue)
    except GitHubIssueError as exc:
        _render_issue_error(exc)
        raise typer.Exit(code=1) from exc

    print_message(f"[bold]Created discovered issue:[/bold] [green]#{issue.number}[/green] {issue.html_url}")
    print_message(f"Next: `legion-dev issue handoff \"#{issue.number}\"`", style="dim")


@register_command("issue", "import-features")
def issue_import_features(
    path: Annotated[
        Path,
        typer.Option("--path", help="Directory containing feature markdown files"),
    ] = Path("docs/features"),
    label: Annotated[
        list[str] | None,
        typer.Option("--label", "-l", help="Additional label to add to imported issues"),
    ] = None,
    dry_run: Annotated[
        bool,
        typer.Option("--dry-run", help="Show issues that would be created without calling GitHub"),
    ] = False,
    allow_duplicates: Annotated[
        bool,
        typer.Option("--allow-duplicates", help="Create issues even when a matching imported issue already exists"),
    ] = False,
) -> None:
    """Import docs/features markdown briefs as GitHub issues."""
    root = _project_root()
    features_dir = path if path.is_absolute() else root / path
    imports = _load_feature_issue_imports(features_dir, root=root, labels=_feature_import_labels(label))

    if not imports:
        print_message(f"No feature markdown files found in {features_dir.relative_to(root)}.", style="yellow")
        return

    if dry_run:
        _render_feature_import_dry_run(imports, root=root)
        return

    client = _issue_client()
    created: list[GitHubIssue] = []
    skipped: list[GitHubIssue] = []
    try:
        for item in imports:
            if not allow_duplicates:
                existing = _find_existing_imported_issue(client, item.title)
                if existing is not None:
                    skipped.append(existing)
                    continue
            created.append(
                client.create_issue(
                    CreateGitHubIssue(title=item.title, body=item.body, labels=item.labels),
                )
            )
    except GitHubIssueError as exc:
        _render_issue_error(exc)
        raise typer.Exit(code=1) from exc

    print_message(f"[bold]Imported feature issues:[/bold] [green]{len(created)}[/green]")
    for issue in created:
        print_message(f"  [green]#{issue.number}[/green] {issue.title} {issue.html_url}")
    if skipped:
        print_message(f"[bold]Skipped existing imported issues:[/bold] [yellow]{len(skipped)}[/yellow]")
        for issue in skipped:
            print_message(f"  [yellow]#{issue.number}[/yellow] {issue.title} {issue.html_url}")


@register_command("issue", "list")
def issue_list(
    state: Annotated[str, typer.Option("--state", help="GitHub issue state")] = "open",
    label: Annotated[
        list[str] | None,
        typer.Option("--label", "-l", help="Filter by label"),
    ] = None,
    limit: Annotated[int, typer.Option("--limit", help="Maximum issues to show")] = 50,
) -> None:
    """List GitHub issues."""
    try:
        issues = _issue_client().list_issues(state=state, labels=tuple(label or ()), limit=limit)
    except GitHubIssueError as exc:
        _render_issue_error(exc)
        raise typer.Exit(code=1) from exc

    if not issues:
        print_message("No matching GitHub issues found.", style="yellow")
        return

    table = Table(title="GitHub Issues")
    table.add_column("Number", style="cyan")
    table.add_column("State", style="cyan")
    table.add_column("Title")
    table.add_column("Labels", style="dim")
    table.add_column("URL", style="dim")
    for issue in issues:
        table.add_row(
            f"#{issue.number}",
            issue.state,
            issue.title,
            ", ".join(issue.labels),
            issue.html_url,
        )
    console.print(table)


@register_command("issue", "show")
def issue_show(
    reference: Annotated[str, typer.Argument(help="Issue number, #number, or exact title")],
) -> None:
    """Show a GitHub issue."""
    issue = _resolve_issue_or_exit(reference)
    _render_issue(issue)


@register_command("issue", "claim")
def issue_claim(
    reference: Annotated[str, typer.Argument(help="Issue number, #number, or exact title")],
    assignee: Annotated[
        str,
        typer.Option("--assignee", "-a", help="GitHub login to assign; defaults to GITHUB_ACTOR"),
    ] = "",
    label: Annotated[str, typer.Option("--label", help="Claim label to apply")] = "in-progress",
) -> None:
    """Claim a GitHub issue by assigning and/or labeling it."""
    issue = _resolve_issue_or_exit(reference)
    assignee_login = (assignee or os.environ.get("GITHUB_ACTOR", "")).strip()
    assignees = tuple(dict.fromkeys((*issue.assignees, assignee_login))) if assignee_login else None
    labels = tuple(dict.fromkeys((*issue.labels, label)))
    try:
        updated = _issue_client().update_issue(
            issue.number,
            labels=labels,
            assignees=assignees,
        )
    except GitHubIssueError as exc:
        _render_issue_error(exc)
        raise typer.Exit(code=1) from exc
    print_message(f"[bold]Claimed issue:[/bold] [green]#{updated.number}[/green] {updated.html_url}")


@register_command("issue", "comment")
def issue_comment(
    reference: Annotated[str, typer.Argument(help="Issue number, #number, or exact title")],
    body: Annotated[str, typer.Argument(help="Comment body")],
) -> None:
    """Comment on a GitHub issue."""
    issue = _resolve_issue_or_exit(reference)
    try:
        comment = _issue_client().add_comment(issue.number, body)
    except GitHubIssueError as exc:
        _render_issue_error(exc)
        raise typer.Exit(code=1) from exc
    print_message(f"[bold]Added comment:[/bold] [green]{comment.html_url}[/green]")


@register_command("issue", "validate")
def issue_validate(
    reference: Annotated[str, typer.Argument(help="Issue number, #number, or exact title")],
) -> None:
    """Validate that a GitHub issue is ready for handoff."""
    issue = _resolve_issue_or_exit(reference)
    result = _validate_issue_body(issue.body)
    _render_validation_result(result)
    if not result.ok:
        raise typer.Exit(code=1)


@register_command("issue", "update")
def issue_update(
    reference: Annotated[str, typer.Argument(help="Issue number, #number, or exact title")],
    body: Annotated[
        str | None,
        typer.Option("--body", "-b", help="Replace the issue body with this text"),
    ] = None,
    body_file: Annotated[
        Path | None,
        typer.Option("--body-file", help="Replace the issue body with markdown from this file"),
    ] = None,
) -> None:
    """Update the canonical GitHub issue body."""
    if body is not None and body_file is not None:
        render_error("Use either --body or --body-file, not both.")
        raise typer.Exit(code=1)
    if body is None and body_file is None:
        render_error("Nothing to update.", hint="Pass --body or --body-file.")
        raise typer.Exit(code=1)

    issue = _resolve_issue_or_exit(reference)
    next_body = body if body is not None else _read_body_file_or_exit(body_file)
    try:
        updated = _issue_client().update_issue(issue.number, body=next_body)
    except GitHubIssueError as exc:
        _render_issue_error(exc)
        raise typer.Exit(code=1) from exc
    print_message(f"[bold]Updated issue:[/bold] [green]#{updated.number}[/green] {updated.html_url}")
    print_message(f"Next: `legion-dev issue handoff \"#{updated.number}\"`", style="dim")


@register_command("issue", "close")
def issue_close(
    reference: Annotated[str, typer.Argument(help="Issue number, #number, or exact title")],
    verified: Annotated[
        str,
        typer.Option("--verified", help="Verification evidence to add as the final issue comment"),
    ] = "",
    allow_unverified: Annotated[
        bool,
        typer.Option("--allow-unverified", help="Close without verification evidence"),
    ] = False,
) -> None:
    """Close a GitHub issue."""
    if not verified.strip() and not allow_unverified:
        render_error(
            "Verification evidence is required before closing.",
            hint="Pass --verified '<commands and results>' or --allow-unverified.",
        )
        raise typer.Exit(code=1)
    issue = _resolve_issue_or_exit(reference)
    client = _issue_client()
    try:
        if verified.strip():
            client.add_comment(issue.number, _verification_comment(verified.strip()))
        closed = client.close_issue(issue.number)
    except GitHubIssueError as exc:
        _render_issue_error(exc)
        raise typer.Exit(code=1) from exc
    print_message(f"[bold]Closed issue:[/bold] [green]#{closed.number}[/green] {closed.html_url}")


@register_command("issue", "handoff")
def issue_handoff(
    reference: Annotated[str, typer.Argument(help="Issue number, #number, or exact title")],
    allow_draft: Annotated[
        bool,
        typer.Option("--allow-draft", help="Print handoff even when readiness validation fails"),
    ] = False,
) -> None:
    """Print a deterministic implementation handoff prompt for a GitHub issue."""
    issue = _resolve_issue_or_exit(reference)
    result = _validate_issue_body(issue.body)
    if not result.ok and not allow_draft:
        _render_validation_result(result)
        render_error("Issue is not ready for handoff.", hint="Refine the body or pass --allow-draft.")
        raise typer.Exit(code=1)
    console.print(_build_issue_handoff_prompt(issue), markup=False, soft_wrap=True)


def _normalize_issue_title(title: str) -> str:
    return " ".join(title.casefold().split())


def _discovered_issue_labels(kind: str, labels: list[str] | None) -> tuple[str, ...]:
    return tuple(dict.fromkeys((DISCOVERED_WORK_LABEL, f"kind:{kind}", *(labels or ()))))


def _find_discovery_duplicates(
    client: GitHubIssuesClient,
    title: str,
) -> tuple[GitHubIssue | None, GitHubIssue | None]:
    normalized_title = _normalize_issue_title(title)
    matches = sorted(
        (
            issue
            for issue in client.search_issues_by_title(title, state="all", limit=100)
            if _normalize_issue_title(issue.title) == normalized_title
        ),
        key=lambda issue: issue.number,
    )
    open_match = next((issue for issue in matches if issue.state == "open"), None)
    closed_match = next((issue for issue in matches if issue.state == "closed"), None)
    return open_match, closed_match


def _generate_discovery_issue_body(context: DiscoveryContext) -> str:
    source = context.source or "None."
    blocks = context.blocks or "None."
    evidence = _markdown_bullets(context.evidence, empty="None.")
    files = _inline_markdown_list((f"`{item}`" for item in context.files), empty="None identified.")
    return "\n".join(
        [
            f"# {context.title}",
            "",
            "**Status**: READY",
            f"**Date**: {date.today().isoformat()}",
            "",
            "## Problem",
            "",
            f"- Current behavior: Discovered {context.kind} work requires follow-up.",
            "- Impact: Track the work explicitly so it is not lost during the current implementation.",
            f"- Source: {source}",
            f"- Blocks: {blocks}",
            "",
            "## Target",
            "",
            "- Behavior: The discovered work is investigated and resolved in a scoped change.",
            "- Non-goals: Broad refactors beyond the discovered work.",
            "",
            "## Repo Context",
            "",
            f"- Files: {files}",
            "- Constraints: Follow the Legion layer model and do not add dependencies without an ADR.",
            f"- Interfaces/data: Discovery kind `{context.kind}` with labels `{', '.join(context.labels)}`.",
            "",
            "## Evidence",
            "",
            evidence,
            "",
            "## Acceptance Criteria",
            "",
            "- The discovered work is either implemented or explicitly closed with a documented reason.",
            "- Relevant tests or verification evidence are added to the issue before closure.",
            "",
            "## Verification Plan",
            "",
            "- Targeted tests: Run the smallest test file that covers the changed behavior.",
            "- Architecture gate: `uv run legion-dev architecture gate`",
            "- Full suite when appropriate: `uv run pytest`",
            "",
            "## Open Questions",
            "",
            "None.",
            "",
        ]
    )


def _discovery_reuse_comment(context: DiscoveryContext) -> str:
    lines = ["## Additional Discovery Context", ""]
    if context.source:
        lines.append(f"- Source: {context.source}")
    if context.blocks:
        lines.append(f"- Blocks: {context.blocks}")
    for item in context.evidence:
        lines.append(f"- Evidence: {item}")
    for item in context.files:
        lines.append(f"- File: `{item}`")
    return "\n".join(lines) if len(lines) > 2 else ""


def _comment_source_backlink(
    client: GitHubIssuesClient,
    source: str,
    discovered_issue: GitHubIssue,
) -> None:
    if not source:
        return
    try:
        source_issue = client.resolve_issue(source, state="all")
    except GitHubIssueNotFoundError:
        return
    if source_issue.number == discovered_issue.number:
        return
    client.add_comment(
        source_issue.number,
        "## Discovered Work\n\n"
        f"Linked discovered issue: #{discovered_issue.number} {discovered_issue.html_url}",
    )


def _render_discovery_dry_run(
    *,
    context: DiscoveryContext,
    open_match: GitHubIssue | None,
    closed_match: GitHubIssue | None,
    allow_duplicate: bool,
) -> None:
    print_message("[bold]Dry run - discovered issue action:[/bold]")
    if open_match is not None:
        print_message(f"  Reuse open issue: #{open_match.number} {open_match.html_url}")
        comment = _discovery_reuse_comment(context)
        if comment:
            print_message("  Comment that would be added:")
            console.print(comment, markup=False, soft_wrap=True)
        return
    if closed_match is not None and not allow_duplicate:
        print_message(f"  Closed duplicate found; no issue would be created: #{closed_match.number} {closed_match.html_url}")
        return
    print_message("  Create new discovered issue")
    print_message(f"  Title: {context.title}")
    print_message(f"  Labels: {', '.join(context.labels)}")
    print_message("  Body:")
    console.print(_generate_discovery_issue_body(context), markup=False, soft_wrap=True)


def _markdown_bullets(items: Iterable[str], *, empty: str) -> str:
    values = tuple(str(item) for item in items if str(item).strip())
    if not values:
        return empty
    return "\n".join(f"- {item}" for item in values)


def _inline_markdown_list(items: Iterable[str], *, empty: str) -> str:
    values = tuple(str(item) for item in items if str(item).strip())
    return ", ".join(values) if values else empty


def _resolve_issue_or_exit(reference: str) -> GitHubIssue:
    try:
        return _issue_client().resolve_issue(reference)
    except (GitHubIssueNotFoundError, GitHubIssueAmbiguousError, GitHubIssueError) as exc:
        _render_issue_error(exc)
        raise typer.Exit(code=1) from exc


def _render_issue(issue: GitHubIssue) -> None:
    print_message(issue.title, style="bold")
    print_message(f"Number:    #{issue.number}", style="cyan")
    print_message(f"State:     {issue.state}", style="cyan")
    print_message(f"Labels:    {', '.join(issue.labels) or 'none'}", style="cyan")
    print_message(f"Assignees: {', '.join(issue.assignees) or 'none'}", style="cyan")
    print_message(f"URL:       {issue.html_url}", style="cyan")
    console.print(issue.body or "", markup=False, soft_wrap=True)


def _read_body_file_or_exit(body_file: Path | None) -> str:
    if body_file is None:
        render_error("Body file is required.")
        raise typer.Exit(code=1)
    try:
        return body_file.read_text(encoding="utf-8")
    except OSError as exc:
        render_error(f"Could not read body file: {body_file}", hint=str(exc))
        raise typer.Exit(code=1) from exc


def _resolve_issue_body_or_exit(
    *,
    title: str,
    body: str | None,
    body_file: Path | None,
) -> str:
    if body is not None and body_file is not None:
        render_error("Use either --body or --body-file, not both.")
        raise typer.Exit(code=1)
    if body_file is not None:
        return _read_body_file_or_exit(body_file)
    if body is not None:
        return body
    return _generate_issue_body_template(title)


def _validate_issue_body(body: str) -> IssueValidationResult:
    text = body.strip()
    failures: list[str] = []
    warnings: list[str] = []
    sections = _parse_markdown_sections(text)

    if not text:
        failures.append("Issue body is empty.")
        return IssueValidationResult(ok=False, failures=tuple(failures))

    status = _extract_markdown_meta(text, "Status")
    if not status:
        warnings.append("Missing **Status** metadata.")
    elif status.upper() == "DRAFT":
        failures.append("Status is DRAFT.")

    for section in REQUIRED_HANDOFF_SECTIONS:
        value = sections.get(section, "").strip()
        if not value:
            failures.append(f"Missing section content: {section}.")
            continue
        if _has_stub_line(value):
            failures.append(f"Section still contains unfilled stub bullets: {section}.")
        if _contains_placeholder(value):
            failures.append(f"Section still contains template placeholder text: {section}.")

    open_questions = sections.get("Open Questions", "").strip()
    if open_questions and not _open_questions_are_resolved(open_questions):
        failures.append("Open Questions must be resolved, marked None, or explicitly accepted.")

    return IssueValidationResult(ok=not failures, failures=tuple(failures), warnings=tuple(warnings))


def _render_validation_result(result: IssueValidationResult) -> None:
    if result.ok:
        print_message("[bold green]Issue is ready for handoff.[/bold green]")
        for warning in result.warnings:
            print_message(f"Warning: {warning}", style="yellow")
        return

    render_error("Issue readiness validation failed.")
    for failure in result.failures:
        print_message(f"- {failure}", style="red")
    for warning in result.warnings:
        print_message(f"- {warning}", style="yellow")


def _parse_markdown_sections(text: str) -> dict[str, str]:
    headings = list(re.finditer(r"^##\s+(.+?)\s*$", text, re.MULTILINE))
    sections: dict[str, str] = {}
    for index, heading in enumerate(headings):
        name = heading.group(1).strip()
        start = heading.end()
        end = headings[index + 1].start() if index + 1 < len(headings) else len(text)
        sections[name] = text[start:end].strip()
    return sections


def _extract_markdown_meta(text: str, field_name: str) -> str:
    match = re.search(rf"^\*\*{re.escape(field_name)}\*\*:\s*(.+?)\s*$", text, re.MULTILINE)
    return match.group(1).strip() if match else ""


def _contains_placeholder(text: str) -> bool:
    return any(phrase in text for phrase in PLACEHOLDER_PHRASES)


def _has_stub_line(text: str) -> bool:
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    if not lines:
        return True
    for line in lines:
        normalized = line.removeprefix("-").strip()
        if not normalized or normalized.endswith(":"):
            return True
    return False


def _open_questions_are_resolved(text: str) -> bool:
    normalized = re.sub(r"^[\s>*-]+", "", text.strip(), flags=re.MULTILINE).strip().lower()
    if normalized in {"none", "none.", "n/a", "not applicable"}:
        return True
    return "accepted:" in normalized or "explicitly accepted" in normalized


def _verification_comment(verified: str) -> str:
    return f"## Verification\n\n{verified}"


def _generate_issue_body_template(title: str) -> str:
    lines = [
        f"# {title}",
        "",
        "**Status**: DRAFT",
        f"**Date**: {date.today().isoformat()}",
        "",
        "<!--",
        "Keep this under 80 lines unless complexity requires more.",
        "Use bullets, not paragraphs. Name commands, files, states, and tests.",
        "Do not restate AGENTS.md or generic repo rules. Write None. where a section has no special content.",
        "Update this body when the contract changes. Use comments for discussion and progress.",
        "-->",
        "",
        "## Problem",
        "",
        "- Current behavior:",
        "- Impact:",
        "",
        "## Target",
        "",
        "- Behavior:",
        "- Non-goals:",
        "",
        "## Repo Context",
        "",
        "- Files:",
        "- Constraints:",
        "- Interfaces/data:",
        "",
        "## Acceptance Criteria",
        "",
        "-",
        "",
        "## Verification Plan",
        "",
        "- Targeted tests:",
        "- Architecture gate: `uv run legion-dev architecture gate`",
        "- Full suite when appropriate: `uv run pytest`",
        "",
        "## Open Questions",
        "",
        "None.",
        "",
    ]
    return "\n".join(lines)


def _render_create_dry_run(*, title: str, body: str, labels: tuple[str, ...]) -> None:
    print_message("[bold]Dry run - GitHub issue that would be created:[/bold]")
    try:
        repository = resolve_github_repository(os.environ, cwd=_project_root())
        print_message(f"  Repository: {repository.full_name}")
    except GitHubIssueConfigurationError:
        print_message("  Repository: UNKNOWN")
    print_message(f"  Title: {title}")
    print_message(f"  Labels: {', '.join(labels) or 'none'}")
    print_message("  Body:")
    console.print(body, markup=False, soft_wrap=True)


def _feature_import_labels(label: list[str] | None) -> tuple[str, ...]:
    return tuple(dict.fromkeys((DEFAULT_FEATURE_IMPORT_LABEL, *(label or ()))))


def _find_existing_imported_issue(client: GitHubIssuesClient, title: str) -> GitHubIssue | None:
    try:
        return client.resolve_issue(title, state="all", labels=(DEFAULT_FEATURE_IMPORT_LABEL,))
    except GitHubIssueNotFoundError:
        return None


def _load_feature_issue_imports(
    features_dir: Path,
    *,
    root: Path,
    labels: tuple[str, ...],
) -> tuple[FeatureIssueImport, ...]:
    if not features_dir.exists():
        return ()
    paths = sorted(
        path
        for path in features_dir.iterdir()
        if path.is_file() and path.suffix == ".md" and path.name != ".gitkeep"
    )
    return tuple(_feature_issue_import_from_path(path, root=root, labels=labels) for path in paths)


def _feature_issue_import_from_path(
    path: Path,
    *,
    root: Path,
    labels: tuple[str, ...],
) -> FeatureIssueImport:
    content = path.read_text(encoding="utf-8").rstrip()
    relative_path = path.relative_to(root)
    return FeatureIssueImport(
        title=_feature_issue_title(path, content),
        body=f"{content}\n\n---\n\nImported from `{relative_path.as_posix()}`.\n",
        labels=labels,
        source_path=relative_path,
    )


def _feature_issue_title(path: Path, content: str) -> str:
    feature_title_match = re.search(r"^#\s+Feature Requirements Gate:\s*(.+)$", content, re.MULTILINE)
    if feature_title_match:
        return feature_title_match.group(1).strip()

    title_match = re.search(r"^#\s+(.+)$", content, re.MULTILINE)
    if title_match:
        return title_match.group(1).strip()

    return path.stem.replace("-", " ").replace("_", " ").title()


def _render_feature_import_dry_run(imports: tuple[FeatureIssueImport, ...], *, root: Path) -> None:
    print_message("[bold]Dry run - GitHub issues that would be created:[/bold]")
    try:
        repository = resolve_github_repository(os.environ, cwd=root)
        print_message(f"  Repository: {repository.full_name}")
    except GitHubIssueConfigurationError:
        print_message("  Repository: UNKNOWN")

    table = Table(title="Feature Issue Imports")
    table.add_column("Title")
    table.add_column("Labels", style="cyan")
    table.add_column("Source", style="dim")
    for item in imports:
        table.add_row(item.title, ", ".join(item.labels), item.source_path.as_posix())
    console.print(table)


def _render_issue_error(exc: GitHubIssueError) -> None:
    hint = None
    if isinstance(exc, GitHubIssueConfigurationError):
        hint = "Set GITHUB_TOKEN or GH_TOKEN, and LEGION_ISSUES_GITHUB_REPO=owner/repo."
    render_error(str(exc), hint=hint)


def _build_issue_handoff_prompt(issue: GitHubIssue) -> str:
    return (
        "You are continuing Legion issue work.\n\n"
        "Use the GitHub issue below as the source of truth. Do not widen scope.\n"
        "If key information is missing, report it before changing code.\n\n"
        f"Issue: #{issue.number} {issue.title}\n"
        f"State: {issue.state}\n"
        f"Labels: {', '.join(issue.labels) or 'none'}\n"
        f"URL: {issue.html_url}\n\n"
        "Implementation rules:\n"
        "- Follow the Legion layer model.\n"
        "- Do not add dependencies without an ADR.\n"
        "- Prefer the smallest change that satisfies the issue.\n"
        "- Run `uv run pytest` and `uv run legion-dev architecture gate` before handing off.\n\n"
        "Issue body:\n"
        "```markdown\n"
        f"{issue.body}\n"
        "```\n"
    )

from __future__ import annotations

import httpx
import pytest

from legion.core.github.issues import (
    CreateGitHubIssue,
    GitHubIssueAmbiguousError,
    GitHubIssueConfigurationError,
    GitHubIssueNotFoundError,
    GitHubIssuesClient,
    GitHubRepository,
    parse_github_repository,
    parse_issue_number,
    resolve_github_repository,
    resolve_github_token,
)


def _issue_payload(number: int, title: str, *, state: str = "open") -> dict[str, object]:
    return {
        "number": number,
        "title": title,
        "body": f"body for {title}",
        "state": state,
        "html_url": f"https://github.com/acme/legion/issues/{number}",
        "created_at": "2026-04-25T00:00:00Z",
        "updated_at": "2026-04-25T00:00:00Z",
        "labels": [{"name": "ready"}],
        "assignees": [{"login": "gary"}],
    }


class TestGitHubIssueConfig:
    def test_resolves_token_from_github_token(self) -> None:
        assert resolve_github_token({"GITHUB_TOKEN": " token "}) == "token"

    def test_resolves_token_from_gh_token(self) -> None:
        assert resolve_github_token({"GH_TOKEN": " token "}) == "token"

    def test_missing_token_errors(self) -> None:
        with pytest.raises(GitHubIssueConfigurationError):
            resolve_github_token({})

    def test_resolves_repository_from_preferred_env(self) -> None:
        repo = resolve_github_repository({"LEGION_ISSUES_GITHUB_REPO": "acme/legion"})
        assert repo == GitHubRepository(owner="acme", name="legion")

    @pytest.mark.parametrize(
        ("value", "expected"),
        [
            ("acme/legion", GitHubRepository("acme", "legion")),
            ("https://github.com/acme/legion.git", GitHubRepository("acme", "legion")),
            ("git@github.com:acme/legion.git", GitHubRepository("acme", "legion")),
            ("ssh://git@github.com/acme/legion.git", GitHubRepository("acme", "legion")),
        ],
    )
    def test_parses_github_repository_formats(
        self,
        value: str,
        expected: GitHubRepository,
    ) -> None:
        assert parse_github_repository(value) == expected

    @pytest.mark.parametrize(("value", "expected"), [("#12", 12), ("12", 12), ("title", None)])
    def test_parse_issue_number(self, value: str, expected: int | None) -> None:
        assert parse_issue_number(value) == expected


class TestGitHubIssuesClient:
    def test_create_issue_posts_typed_payload(self) -> None:
        seen: list[httpx.Request] = []

        def handler(request: httpx.Request) -> httpx.Response:
            seen.append(request)
            assert request.method == "POST"
            assert request.url.path == "/repos/acme/legion/issues"
            assert request.headers["authorization"] == "Bearer secret"
            assert request.read() == (
                b'{"title":"New issue","body":"body","labels":["ready"],"assignees":["gary"]}'
            )
            return httpx.Response(201, json=_issue_payload(3, "New issue"))

        client = GitHubIssuesClient(
            repository=GitHubRepository("acme", "legion"),
            token="secret",
            client=httpx.Client(transport=httpx.MockTransport(handler), base_url="https://api.github.com"),
        )

        issue = client.create_issue(
            CreateGitHubIssue(
                title="New issue",
                body="body",
                labels=("ready",),
                assignees=("gary",),
            )
        )

        assert seen
        assert issue.number == 3
        assert issue.labels == ("ready",)
        assert issue.assignees == ("gary",)

    def test_list_issues_filters_by_state_label_and_limit(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            assert request.method == "GET"
            assert request.url.path == "/repos/acme/legion/issues"
            assert request.url.params["state"] == "open"
            assert request.url.params["labels"] == "ready,ai"
            assert request.url.params["per_page"] == "25"
            return httpx.Response(200, json=[_issue_payload(1, "First")])

        client = GitHubIssuesClient(
            repository=GitHubRepository("acme", "legion"),
            token="secret",
            client=httpx.Client(transport=httpx.MockTransport(handler), base_url="https://api.github.com"),
        )

        assert client.list_issues(labels=("ready", "ai"), limit=25)[0].title == "First"

    def test_list_issues_filters_pull_requests(self) -> None:
        def handler(_request: httpx.Request) -> httpx.Response:
            pr_payload = _issue_payload(2, "Pull request")
            pr_payload["pull_request"] = {"url": "https://api.github.com/repos/acme/legion/pulls/2"}
            return httpx.Response(200, json=[_issue_payload(1, "Issue"), pr_payload])

        client = GitHubIssuesClient(
            repository=GitHubRepository("acme", "legion"),
            token="secret",
            client=httpx.Client(transport=httpx.MockTransport(handler), base_url="https://api.github.com"),
        )

        issues = client.list_issues()

        assert [issue.title for issue in issues] == ["Issue"]

    def test_resolve_issue_by_number(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            assert request.method == "GET"
            assert request.url.path == "/repos/acme/legion/issues/4"
            return httpx.Response(200, json=_issue_payload(4, "Numbered"))

        client = GitHubIssuesClient(
            repository=GitHubRepository("acme", "legion"),
            token="secret",
            client=httpx.Client(transport=httpx.MockTransport(handler), base_url="https://api.github.com"),
        )

        assert client.resolve_issue("#4").title == "Numbered"

    def test_resolve_issue_by_title_uses_search_api(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            assert request.method == "GET"
            assert request.url.path == "/search/issues"
            query = request.url.params["q"]
            assert "repo:acme/legion" in query
            assert "is:issue" in query
            assert "in:title" in query
            assert "state:open" in query
            return httpx.Response(200, json={"items": [_issue_payload(9, "Search me")]})

        client = GitHubIssuesClient(
            repository=GitHubRepository("acme", "legion"),
            token="secret",
            client=httpx.Client(transport=httpx.MockTransport(handler), base_url="https://api.github.com"),
        )

        assert client.resolve_issue("Search me").number == 9

    def test_resolve_issue_by_title_errors_for_missing_and_ambiguous(self) -> None:
        def missing_handler(_request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json={"items": []})

        missing_client = GitHubIssuesClient(
            repository=GitHubRepository("acme", "legion"),
            token="secret",
            client=httpx.Client(
                transport=httpx.MockTransport(missing_handler),
                base_url="https://api.github.com",
            ),
        )
        with pytest.raises(GitHubIssueNotFoundError):
            missing_client.resolve_issue("Missing")

        def ambiguous_handler(_request: httpx.Request) -> httpx.Response:
            return httpx.Response(
                200,
                json={"items": [_issue_payload(1, "Same"), _issue_payload(2, "Same")]},
            )

        ambiguous_client = GitHubIssuesClient(
            repository=GitHubRepository("acme", "legion"),
            token="secret",
            client=httpx.Client(
                transport=httpx.MockTransport(ambiguous_handler),
                base_url="https://api.github.com",
            ),
        )
        with pytest.raises(GitHubIssueAmbiguousError):
            ambiguous_client.resolve_issue("Same")

    def test_close_issue_patches_state(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            assert request.method == "PATCH"
            assert request.url.path == "/repos/acme/legion/issues/5"
            assert request.read() == b'{"state":"closed"}'
            return httpx.Response(200, json=_issue_payload(5, "Close me", state="closed"))

        client = GitHubIssuesClient(
            repository=GitHubRepository("acme", "legion"),
            token="secret",
            client=httpx.Client(transport=httpx.MockTransport(handler), base_url="https://api.github.com"),
        )

        assert client.close_issue(5).state == "closed"

    def test_update_issue_patches_body(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            assert request.method == "PATCH"
            assert request.url.path == "/repos/acme/legion/issues/8"
            assert request.read() == b'{"body":"new body"}'
            payload = _issue_payload(8, "Refine")
            payload["body"] = "new body"
            return httpx.Response(200, json=payload)

        client = GitHubIssuesClient(
            repository=GitHubRepository("acme", "legion"),
            token="secret",
            client=httpx.Client(transport=httpx.MockTransport(handler), base_url="https://api.github.com"),
        )

        assert client.update_issue(8, body="new body").body == "new body"

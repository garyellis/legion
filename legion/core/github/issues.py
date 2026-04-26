from __future__ import annotations

import os
import re
import subprocess
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import httpx

from legion.plumbing.exceptions import CoreError

DEFAULT_API_URL = "https://api.github.com"
DEFAULT_USER_AGENT = "legion-dev-issue"


class GitHubIssueError(CoreError):
    """Raised when GitHub Issues access fails."""

    _serializable_fields: tuple[str, ...] = ("message", "retryable", "status_code", "detail")

    def __init__(self, message: str, *, status_code: int | None = None, detail: str = "") -> None:
        self.status_code = status_code
        self.detail = detail
        retryable = status_code in {429, 502, 503, 504} if status_code is not None else False
        super().__init__(message, retryable=retryable)


class GitHubIssueConfigurationError(GitHubIssueError):
    """Raised when GitHub issue client configuration is incomplete."""


class GitHubIssueNotFoundError(GitHubIssueError):
    """Raised when a GitHub issue reference cannot be resolved."""


class GitHubIssueAmbiguousError(GitHubIssueError):
    """Raised when a title resolves to multiple GitHub issues."""


@dataclass(frozen=True)
class GitHubRepository:
    """GitHub repository coordinates."""

    owner: str
    name: str

    @property
    def full_name(self) -> str:
        return f"{self.owner}/{self.name}"


@dataclass(frozen=True)
class GitHubIssue:
    """Typed GitHub issue payload used by developer tooling."""

    number: int
    title: str
    body: str
    state: str
    html_url: str
    created_at: str
    updated_at: str
    labels: tuple[str, ...] = field(default_factory=tuple)
    assignees: tuple[str, ...] = field(default_factory=tuple)


@dataclass(frozen=True)
class GitHubIssueComment:
    """Typed GitHub issue comment payload."""

    id: int
    body: str
    html_url: str
    created_at: str


@dataclass(frozen=True)
class CreateGitHubIssue:
    """Payload for creating a GitHub issue."""

    title: str
    body: str = ""
    labels: tuple[str, ...] = field(default_factory=tuple)
    assignees: tuple[str, ...] = field(default_factory=tuple)

    def to_json(self) -> dict[str, object]:
        payload: dict[str, object] = {"title": self.title, "body": self.body}
        if self.labels:
            payload["labels"] = list(self.labels)
        if self.assignees:
            payload["assignees"] = list(self.assignees)
        return payload


class GitHubIssuesClient:
    """Small GitHub Issues REST client."""

    def __init__(
        self,
        *,
        repository: GitHubRepository,
        token: str,
        api_url: str = DEFAULT_API_URL,
        client: httpx.Client | None = None,
    ) -> None:
        self.repository = repository
        self._token = token
        self._owns_client = client is None
        self._client = client or httpx.Client(
            base_url=api_url.rstrip("/"),
            timeout=20.0,
        )

    def create_issue(self, payload: CreateGitHubIssue) -> GitHubIssue:
        data = self._request("POST", self._issues_path(), json=payload.to_json())
        return _issue_from_mapping(_expect_mapping(data))

    def list_issues(
        self,
        *,
        state: str = "open",
        labels: Sequence[str] = (),
        limit: int = 100,
    ) -> tuple[GitHubIssue, ...]:
        params: dict[str, str | int] = {"state": state, "per_page": max(1, min(limit, 100))}
        if labels:
            params["labels"] = ",".join(labels)
        data = self._request("GET", self._issues_path(), params=params)
        if not isinstance(data, list):
            raise GitHubIssueError("GitHub returned an unexpected issue list response.")
        return tuple(
            _issue_from_mapping(item)
            for item in data
            if isinstance(item, Mapping) and "pull_request" not in item
        )

    def get_issue(self, number: int) -> GitHubIssue:
        data = self._request("GET", f"{self._issues_path()}/{number}")
        return _issue_from_mapping(_expect_mapping(data))

    def resolve_issue(
        self,
        reference: str,
        *,
        state: str = "open",
        labels: Sequence[str] = (),
    ) -> GitHubIssue:
        number = parse_issue_number(reference)
        if number is not None:
            return self.get_issue(number)

        matches = [
            issue
            for issue in self.search_issues_by_title(reference, state=state, labels=labels)
            if issue.title == reference
        ]
        if not matches:
            raise GitHubIssueNotFoundError(f"GitHub issue not found: {reference}")
        if len(matches) > 1:
            numbers = ", ".join(f"#{issue.number}" for issue in matches)
            raise GitHubIssueAmbiguousError(
                f"GitHub issue title is ambiguous: {reference}. Use one of: {numbers}"
            )
        return matches[0]

    def search_issues_by_title(
        self,
        title: str,
        *,
        state: str = "open",
        labels: Sequence[str] = (),
        limit: int = 100,
    ) -> tuple[GitHubIssue, ...]:
        """Search GitHub issues by title without being limited to the first list page."""
        terms = [f"repo:{self.repository.full_name}", "is:issue", "in:title", title]
        if state != "all":
            terms.append(f"state:{state}")
        terms.extend(f'label:"{label}"' for label in labels)
        params: dict[str, str | int] = {
            "q": " ".join(terms),
            "per_page": max(1, min(limit, 100)),
        }
        data = self._request("GET", "/search/issues", params=params)
        payload = _expect_mapping(data)
        items = payload.get("items", [])
        if not isinstance(items, list):
            raise GitHubIssueError("GitHub returned an unexpected issue search response.")
        return tuple(_issue_from_mapping(item) for item in items if isinstance(item, Mapping))

    def add_comment(self, number: int, body: str) -> GitHubIssueComment:
        data = self._request("POST", f"{self._issues_path()}/{number}/comments", json={"body": body})
        payload = _expect_mapping(data)
        return GitHubIssueComment(
            id=_payload_int(payload, "id"),
            body=_payload_str(payload, "body"),
            html_url=_payload_str(payload, "html_url"),
            created_at=_payload_str(payload, "created_at"),
        )

    def update_issue(
        self,
        number: int,
        *,
        title: str | None = None,
        body: str | None = None,
        state: str | None = None,
        labels: Sequence[str] | None = None,
        assignees: Sequence[str] | None = None,
    ) -> GitHubIssue:
        payload: dict[str, object] = {}
        if title is not None:
            payload["title"] = title
        if body is not None:
            payload["body"] = body
        if state is not None:
            payload["state"] = state
        if labels is not None:
            payload["labels"] = list(labels)
        if assignees is not None:
            payload["assignees"] = list(assignees)
        data = self._request("PATCH", f"{self._issues_path()}/{number}", json=payload)
        return _issue_from_mapping(_expect_mapping(data))

    def close_issue(self, number: int) -> GitHubIssue:
        return self.update_issue(number, state="closed")

    def _issues_path(self) -> str:
        return f"/repos/{self.repository.owner}/{self.repository.name}/issues"

    def _request(
        self,
        method: str,
        path: str,
        *,
        params: Mapping[str, str | int] | None = None,
        json: Mapping[str, object] | None = None,
    ) -> object:
        headers = {
            "Accept": "application/vnd.github+json",
            "Authorization": f"Bearer {self._token}",
            "User-Agent": DEFAULT_USER_AGENT,
            "X-GitHub-Api-Version": "2022-11-28",
        }
        try:
            response = self._client.request(method, path, headers=headers, params=params, json=json)
        except httpx.HTTPError as exc:
            raise GitHubIssueError(f"GitHub request failed: {exc}") from exc
        if response.is_success:
            return response.json()
        detail = _response_detail(response)
        raise GitHubIssueError(
            f"GitHub request failed with HTTP {response.status_code}: {detail}",
            status_code=response.status_code,
            detail=detail,
        )

    def close(self) -> None:
        if self._owns_client:
            self._client.close()

    def __enter__(self) -> GitHubIssuesClient:
        return self

    def __exit__(
        self,
        _exc_type: type[BaseException] | None,
        _exc_val: BaseException | None,
        _exc_tb: object,
    ) -> None:
        self.close()


def create_github_issues_client(
    *,
    environ: Mapping[str, str] | None = None,
    cwd: Path | None = None,
    client: httpx.Client | None = None,
) -> GitHubIssuesClient:
    """Create a GitHub Issues client from environment and git config."""
    env = os.environ if environ is None else environ
    token = resolve_github_token(env)
    repository = resolve_github_repository(env, cwd=cwd)
    api_url = env.get("GITHUB_API_URL", DEFAULT_API_URL).strip() or DEFAULT_API_URL
    return GitHubIssuesClient(repository=repository, token=token, api_url=api_url, client=client)


def resolve_github_token(environ: Mapping[str, str]) -> str:
    """Resolve a GitHub API token from environment."""
    token = environ.get("GITHUB_TOKEN", "").strip() or environ.get("GH_TOKEN", "").strip()
    if not token:
        raise GitHubIssueConfigurationError("GITHUB_TOKEN or GH_TOKEN is required.")
    return token


def resolve_github_repository(
    environ: Mapping[str, str],
    *,
    cwd: Path | None = None,
) -> GitHubRepository:
    """Resolve GitHub repo coordinates from env or git remote origin."""
    for key in ("LEGION_ISSUES_GITHUB_REPO", "GITHUB_REPOSITORY"):
        value = environ.get(key, "").strip()
        if value:
            repository = parse_github_repository(value)
            if repository is None:
                raise GitHubIssueConfigurationError(f"{key} must use the format 'owner/repo'.")
            return repository

    repository = parse_github_repository(_git_origin_url(cwd))
    if repository is None:
        raise GitHubIssueConfigurationError(
            "Could not determine GitHub repository. Set LEGION_ISSUES_GITHUB_REPO=owner/repo."
        )
    return repository


def parse_github_repository(value: str) -> GitHubRepository | None:
    """Parse owner/repo from common GitHub remote formats."""
    text = value.strip()
    if not text:
        return None

    direct = re.fullmatch(r"(?P<owner>[A-Za-z0-9_.-]+)/(?P<repo>[A-Za-z0-9_.-]+)", text)
    if direct:
        return GitHubRepository(direct.group("owner"), _strip_git_suffix(direct.group("repo")))

    ssh = re.fullmatch(
        r"git@github\.com:(?P<owner>[A-Za-z0-9_.-]+)/(?P<repo>[A-Za-z0-9_.-]+)(?:\.git)?",
        text,
    )
    if ssh:
        return GitHubRepository(ssh.group("owner"), _strip_git_suffix(ssh.group("repo")))

    parsed = urlparse(text)
    if (parsed.hostname or "").lower() != "github.com":
        return None
    parts = [part for part in parsed.path.split("/") if part]
    if len(parts) < 2:
        return None
    return GitHubRepository(parts[0], _strip_git_suffix(parts[1]))


def parse_issue_number(reference: str) -> int | None:
    """Parse '#123' or '123' into an issue number."""
    text = reference.strip().removeprefix("#")
    if text.isdecimal():
        return int(text)
    return None


def _git_origin_url(cwd: Path | None) -> str:
    try:
        result = subprocess.run(
            ("git", "config", "--get", "remote.origin.url"),
            cwd=str(cwd) if cwd is not None else None,
            check=False,
            capture_output=True,
            text=True,
        )
    except OSError:
        return ""
    return result.stdout.strip() if result.returncode == 0 else ""


def _issue_from_mapping(payload: Mapping[object, object]) -> GitHubIssue:
    return GitHubIssue(
        number=_payload_int(payload, "number"),
        title=_payload_str(payload, "title"),
        body=_payload_str(payload, "body"),
        state=_payload_str(payload, "state"),
        html_url=_payload_str(payload, "html_url"),
        created_at=_payload_str(payload, "created_at"),
        updated_at=_payload_str(payload, "updated_at"),
        labels=_labels_from_payload(payload.get("labels")),
        assignees=_assignees_from_payload(payload.get("assignees")),
    )


def _expect_mapping(data: object) -> Mapping[object, object]:
    if not isinstance(data, Mapping):
        raise GitHubIssueError("GitHub returned an unexpected response shape.")
    return data


def _labels_from_payload(value: object) -> tuple[str, ...]:
    if not isinstance(value, list):
        return ()
    labels: list[str] = []
    for item in value:
        if isinstance(item, Mapping):
            name = _payload_str(item, "name")
            if name:
                labels.append(name)
    return tuple(labels)


def _assignees_from_payload(value: object) -> tuple[str, ...]:
    if not isinstance(value, list):
        return ()
    assignees: list[str] = []
    for item in value:
        if isinstance(item, Mapping):
            login = _payload_str(item, "login")
            if login:
                assignees.append(login)
    return tuple(assignees)


def _payload_str(payload: Mapping[object, object], key: str) -> str:
    value = payload.get(key, "")
    return value if isinstance(value, str) else ""


def _payload_int(payload: Mapping[object, object], key: str) -> int:
    value = payload.get(key, 0)
    return value if isinstance(value, int) else 0


def _response_detail(response: httpx.Response) -> str:
    try:
        payload = response.json()
    except ValueError:
        return response.text
    if isinstance(payload, Mapping):
        message = payload.get("message")
        if isinstance(message, str):
            return message
    return response.text


def _strip_git_suffix(value: str) -> str:
    return value.removesuffix(".git")

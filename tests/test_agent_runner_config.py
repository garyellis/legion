"""Tests for agent runner configuration parsing."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from legion.agent_runner.config import AgentRunnerConfig


def _clear_runner_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in (
        "AGENT_RUNNER_API_URL",
        "AGENT_RUNNER_REGISTRATION_TOKEN",
        "AGENT_RUNNER_AGENT_NAME",
        "AGENT_RUNNER_CAPABILITIES",
        "AGENT_RUNNER_LOG_LEVEL",
        "AGENT_RUNNER_LOG_FORMAT",
    ):
        monkeypatch.delenv(name, raising=False)


class TestAgentRunnerConfig:
    def test_parses_comma_separated_capabilities(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _clear_runner_env(monkeypatch)
        monkeypatch.setenv("AGENT_RUNNER_REGISTRATION_TOKEN", "token-123")
        monkeypatch.setenv("AGENT_RUNNER_AGENT_NAME", "agent-01")
        monkeypatch.setenv(
            "AGENT_RUNNER_CAPABILITIES",
            " kubernetes, logs, , kubernetes ,shell ",
        )

        config = AgentRunnerConfig()

        assert config.capabilities == ["kubernetes", "logs", "shell"]

    def test_defaults_capabilities_to_empty(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _clear_runner_env(monkeypatch)
        monkeypatch.setenv("AGENT_RUNNER_REGISTRATION_TOKEN", "token-123")
        monkeypatch.setenv("AGENT_RUNNER_AGENT_NAME", "agent-01")

        config = AgentRunnerConfig()

        assert config.api_url == "http://127.0.0.1:8000"
        assert config.capabilities == []
        assert config.log_level == "INFO"
        assert config.log_format == "JSON"

    def test_normalizes_api_url(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _clear_runner_env(monkeypatch)
        monkeypatch.setenv("AGENT_RUNNER_REGISTRATION_TOKEN", "token-123")
        monkeypatch.setenv("AGENT_RUNNER_AGENT_NAME", "agent-01")
        monkeypatch.setenv("AGENT_RUNNER_API_URL", "http://127.0.0.1:9000/")

        config = AgentRunnerConfig()

        assert config.api_url == "http://127.0.0.1:9000"

    def test_requires_token_and_agent_name(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _clear_runner_env(monkeypatch)

        with pytest.raises(ValidationError):
            AgentRunnerConfig()

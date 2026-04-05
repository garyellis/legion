"""Configuration for the agent runner surface."""

from __future__ import annotations

from typing import Annotated, Any

from pydantic import Field, field_validator
from pydantic_settings import NoDecode, SettingsConfigDict

from legion.plumbing.config.base import LegionConfig


def _normalize_capabilities(value: str | list[str] | tuple[str, ...] | None) -> list[str]:
    if value is None:
        return []

    if isinstance(value, str):
        items = value.split(",")
    else:
        items = list(value)

    normalized: list[str] = []
    seen: set[str] = set()
    for item in items:
        capability = item.strip()
        if not capability or capability in seen:
            continue
        seen.add(capability)
        normalized.append(capability)
    return normalized


class AgentRunnerConfig(LegionConfig):
    """Configuration for the standalone agent runner process."""

    model_config = SettingsConfigDict(env_prefix="AGENT_RUNNER_")

    api_url: str = "http://127.0.0.1:8000"
    registration_token: str
    agent_name: str
    capabilities: Annotated[list[str], NoDecode] = Field(default_factory=list)
    log_level: str = "INFO"
    log_format: str = "JSON"

    @field_validator("api_url")
    @classmethod
    def normalize_api_url(cls, value: str) -> str:
        return value.rstrip("/")

    @field_validator("capabilities", mode="before")
    @classmethod
    def parse_capabilities(cls, value: Any) -> list[str]:
        if value == "":
            return []
        return _normalize_capabilities(value)

    @classmethod
    def from_env(cls) -> AgentRunnerConfig:
        """Load runner settings from the environment."""

        return cls()  # type: ignore[call-arg]

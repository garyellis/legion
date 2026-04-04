"""Configuration for the Fleet API client."""

from __future__ import annotations

from pydantic import SecretStr
from pydantic_settings import SettingsConfigDict

from legion.plumbing.config.base import LegionConfig


class FleetAPIConfig(LegionConfig):
    """Connection settings for the Legion Fleet API.

    Shared across surfaces — any CLI, Slack, or TUI command that needs
    the Fleet API reads from LEGION_FLEET_* environment variables.
    """

    model_config = SettingsConfigDict(env_prefix="LEGION_FLEET_")

    api_url: str = "http://127.0.0.1:8000"
    api_key: SecretStr = SecretStr("")

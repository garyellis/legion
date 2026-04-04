"""CLI configuration — loaded from LEGION_CLI_* environment variables."""

from __future__ import annotations

from pydantic_settings import SettingsConfigDict

from legion.plumbing.config.base import LegionConfig


class CLIConfig(LegionConfig):
    """Configuration for CLI-specific settings.

    Fleet API connection settings live in FleetAPIConfig (core/fleet_api/config.py).
    """

    model_config = SettingsConfigDict(env_prefix="LEGION_CLI_")

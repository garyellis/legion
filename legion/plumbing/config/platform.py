"""Platform-wide configuration (LEGION_* env vars)."""

from __future__ import annotations

from pydantic_settings import SettingsConfigDict

from legion.plumbing.config.base import LegionConfig


class PlatformConfig(LegionConfig):
    """Global platform settings loaded from LEGION_* environment variables."""

    model_config = SettingsConfigDict(env_prefix="LEGION_")

    log_level: str = "INFO"
    environment: str = "development"

"""Slack SDK configuration."""

from __future__ import annotations

from pydantic import SecretStr
from pydantic_settings import SettingsConfigDict

from legion.plumbing.config.base import LegionConfig


class SlackConfig(LegionConfig):
    """Configuration for the Slack integration (SLACK_* env vars)."""

    model_config = SettingsConfigDict(env_prefix="SLACK_")

    bot_token: SecretStr = SecretStr("")
    app_token: SecretStr = SecretStr("")
    stale_check_interval_seconds: int = 60
    log_format: str = "JSON"
    log_level: str = "INFO"

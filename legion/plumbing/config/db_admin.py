"""Operator-facing database migration configuration."""

from __future__ import annotations

from pydantic_settings import SettingsConfigDict

from legion.plumbing.config.base import LegionConfig


class DatabaseAdminConfig(LegionConfig):
    """Direct database connectivity for operator migration commands.

    These settings are intentionally separate from the API-backed CLI config so
    routine operator commands do not assume database reachability.
    """

    model_config = SettingsConfigDict(env_prefix="LEGION_DB_")

    url: str = "sqlite:///legion.db"
    pool_pre_ping: bool = True
    echo: bool = False

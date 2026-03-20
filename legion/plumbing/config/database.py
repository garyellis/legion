"""Database configuration."""

from __future__ import annotations

from pydantic_settings import SettingsConfigDict

from legion.plumbing.config.base import LegionConfig


class DatabaseConfig(LegionConfig):
    """Database connection settings.

    Env vars: DATABASE_URL, DATABASE_POOL_PRE_PING, DATABASE_ECHO.
    """

    model_config = SettingsConfigDict(env_prefix="DATABASE_")

    url: str = "sqlite:///legion.db"
    pool_pre_ping: bool = True
    echo: bool = False

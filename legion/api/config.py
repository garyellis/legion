"""API surface configuration."""

from __future__ import annotations

from pydantic_settings import SettingsConfigDict

from legion.plumbing.config.base import LegionConfig


class APIConfig(LegionConfig):
    """Configuration for the REST/WebSocket API (API_* env vars)."""

    model_config = SettingsConfigDict(env_prefix="API_")

    host: str = "127.0.0.1"
    port: int = 8000
    log_level: str = "INFO"
    log_format: str = "JSON"
    api_key: str = ""
    agent_session_token_ttl_seconds: int = 3600
    agent_heartbeat_interval_seconds: int = 30

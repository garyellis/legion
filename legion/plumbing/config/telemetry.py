"""Telemetry configuration (TELEMETRY_* env vars)."""

from __future__ import annotations

from pydantic_settings import SettingsConfigDict

from legion.plumbing.config.base import LegionConfig


class TelemetryConfig(LegionConfig):
    """Telemetry/observability settings."""

    model_config = SettingsConfigDict(env_prefix="TELEMETRY_")

    enabled: bool = False
    endpoint: str = ""
    service_name: str = "legion"

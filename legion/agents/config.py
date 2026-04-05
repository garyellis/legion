"""Agent configuration (AGENT_* env vars)."""

from __future__ import annotations

from pydantic import SecretStr
from pydantic_settings import SettingsConfigDict

from legion.plumbing.config.base import LegionConfig


class AgentConfig(LegionConfig):
    """Configuration for AI agent chains.

    Env vars: AGENT_OPENAI_API_KEY, AGENT_MODEL_NAME, AGENT_BASE_URL, etc.
    """

    model_config = SettingsConfigDict(env_prefix="AGENT_")

    openai_api_key: SecretStr = SecretStr("")
    anthropic_api_key: SecretStr = SecretStr("")
    model_name: str = "openai/gpt-oss-120b"
    model_base_url: str = ""
    max_completion_tokens: int = 4096
    max_job_tokens: int = 32_768
    temperature: float = 0.7
    max_iterations: int = 25
    auto_pir_enabled: bool = True

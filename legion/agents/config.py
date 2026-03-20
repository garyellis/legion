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
    model_name: str = "openai/gpt-oss-120b"
    #base_url: str = "http://192.168.1.214:8080/api/v1"
    model_base_url: str = ""
    max_completion_tokens: int = 4096
    temperature: float = 0.7
    auto_pir_enabled: bool = True

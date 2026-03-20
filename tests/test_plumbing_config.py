"""Tests for legion.plumbing.config."""

import os

import pytest
from pydantic import SecretStr

from legion.plumbing.config.base import LegionConfig
from legion.plumbing.config.platform import PlatformConfig


class TestLegionConfig:
    def test_is_available_all_defaults(self):
        """A config with only defaulted fields is available."""
        cfg = PlatformConfig()
        assert cfg.is_available() is True

    def test_is_available_missing_required(self):
        class RequiredConfig(LegionConfig):
            token: str

        # pydantic-settings will raise if required env var not set
        with pytest.raises(Exception):
            RequiredConfig()

    def test_to_redacted_dict_hides_secrets(self):
        class SecretConfig(LegionConfig):
            api_key: SecretStr = SecretStr("hunter2")
            name: str = "test"

        cfg = SecretConfig()
        d = cfg.to_redacted_dict()
        assert d["api_key"] == "***"
        assert d["name"] == "test"

    def test_to_redacted_dict_empty_secret(self):
        class SecretConfig(LegionConfig):
            api_key: SecretStr = SecretStr("")

        cfg = SecretConfig()
        d = cfg.to_redacted_dict()
        assert d["api_key"] == ""


class TestPlatformConfig:
    def test_defaults(self):
        cfg = PlatformConfig()
        assert cfg.log_level == "INFO"
        assert cfg.environment == "development"

    def test_env_override(self, monkeypatch):
        monkeypatch.setenv("LEGION_LOG_LEVEL", "DEBUG")
        monkeypatch.setenv("LEGION_ENVIRONMENT", "production")
        cfg = PlatformConfig()
        assert cfg.log_level == "DEBUG"
        assert cfg.environment == "production"

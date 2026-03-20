"""Base configuration class for the legion project.

Source of truth: CONFIG_MGMT_draft.md §3.2
"""

from __future__ import annotations

from typing import Any

from pydantic import SecretStr
from pydantic_settings import BaseSettings


class LegionConfig(BaseSettings):
    """Base for all legion config classes.

    Subclasses declare fields as class attributes; values are loaded from
    environment variables (with an optional ``model_config`` prefix).
    """

    def is_available(self) -> bool:
        """Return True if all required fields have non-empty values.

        Optional fields (those with defaults) are ignored.
        """
        for name, field_info in type(self).model_fields.items():
            if field_info.is_required():
                value = getattr(self, name)
                if value is None or value == "":
                    return False
                if isinstance(value, SecretStr) and value.get_secret_value() == "":
                    return False
        return True

    def to_redacted_dict(self) -> dict[str, Any]:
        """Return a dict with SecretStr values replaced by '***'."""
        result: dict[str, Any] = {}
        for name in type(self).model_fields:
            value = getattr(self, name)
            if isinstance(value, SecretStr):
                result[name] = "***" if value.get_secret_value() else ""
            else:
                result[name] = value
        return result

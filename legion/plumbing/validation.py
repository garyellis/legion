"""Shared validation utilities for domain models."""

from __future__ import annotations

from typing import Any


def ensure_json_compatible(value: Any, *, path: str) -> None:
    """Recursively verify that *value* contains only JSON-compatible types.

    Raises ``ValueError`` when a non-JSON type or a non-string dict key is
    encountered, with *path* included in the message for diagnostics.
    """
    if value is None or isinstance(value, str | int | float | bool):
        return
    if isinstance(value, list):
        for index, item in enumerate(value):
            ensure_json_compatible(item, path=f"{path}[{index}]")
        return
    if isinstance(value, dict):
        for key, item in value.items():
            if not isinstance(key, str):
                raise ValueError(f"{path} must use string keys")
            ensure_json_compatible(item, path=f"{path}.{key}")
        return
    raise ValueError(f"{path} must contain only JSON-compatible values")

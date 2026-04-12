"""Shared route helpers."""

from __future__ import annotations

from pydantic import BaseModel


def apply_partial_update(entity: object, update: BaseModel) -> None:
    """Apply non-None fields from an update DTO to a domain entity."""
    for field, value in update.model_dump(exclude_unset=True).items():
        setattr(entity, field, value)

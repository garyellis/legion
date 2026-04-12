"""Shared base for API response schemas."""

from __future__ import annotations

from typing import Any, ClassVar

from pydantic import BaseModel


class ResponseBase(BaseModel):
    """Base class for API response DTOs with automatic domain-model mapping."""

    _excluded_domain_fields: ClassVar[frozenset[str]] = frozenset()

    @classmethod
    def from_domain(cls, entity: Any) -> Any:
        """Construct a response DTO from a domain entity.

        Maps all fields declared on the response model from matching
        attributes on the domain entity.
        """
        return cls(**{f: getattr(entity, f) for f in cls.model_fields})

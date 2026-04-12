"""Pagination schemas for list endpoints."""

from __future__ import annotations

from typing import Generic, TypeVar

from pydantic import BaseModel

T = TypeVar("T")


class PaginationParams(BaseModel):
    """Query parameters for paginated list endpoints."""

    limit: int = 100
    offset: int = 0


class PaginatedResponse(BaseModel, Generic[T]):
    """Wrapper for paginated list responses."""

    items: list[T]
    total: int
    limit: int
    offset: int

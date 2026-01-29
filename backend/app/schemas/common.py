"""Common schemas."""
from typing import Any, Generic, Optional, TypeVar

from pydantic import BaseModel

T = TypeVar('T')


class APIResponse(BaseModel, Generic[T]):
    """Standard API response wrapper."""
    code: int = 0
    message: str = 'success'
    data: Optional[T] = None


class PaginatedResponse(BaseModel, Generic[T]):
    """Paginated response."""
    items: list[T]
    total: int
    limit: int
    offset: int

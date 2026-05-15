"""API Key schemas."""
from datetime import datetime
from typing import Optional
from uuid import UUID

from pydantic import BaseModel, Field


class APIKeyCreate(BaseModel):
    """Schema for creating an API key."""
    name: str = Field(..., min_length=1, max_length=100)
    expires_in_days: Optional[int] = Field(
        default=None,
        ge=1,
        le=365,
        description='Key expires after N days. Null = never expires.',
    )


class APIKeyResponse(BaseModel):
    """API key response (no secret)."""
    id: UUID
    name: str
    key_prefix: str
    expires_at: Optional[datetime] = None
    last_used: Optional[datetime] = None
    created_at: datetime

    class Config:
        from_attributes = True


class APIKeyCreatedResponse(APIKeyResponse):
    """Response after creating a key — includes the full key ONCE."""
    full_key: str


class APIKeyListResponse(BaseModel):
    """List of API keys."""
    items: list[APIKeyResponse]
    total: int

"""Environment schemas."""
from datetime import datetime
from typing import Any, Dict, List, Optional
from uuid import UUID

from pydantic import BaseModel, Field


class EnvironmentCreate(BaseModel):
    """Schema for creating an environment."""
    business_id: UUID
    name: str = Field(..., min_length=1, max_length=100)
    url: str = Field(..., min_length=1, max_length=500)
    browser_config: Optional[Dict[str, Any]] = None
    ignore_rules: Optional[Dict[str, Any]] = None
    auth_type: str = Field(default='none', pattern='^(none|sso|cookies)$')
    sso_username: Optional[str] = None
    sso_password: Optional[str] = None
    sso_env: str = Field(default='prod', pattern='^(prod|staging|dev)$')
    cookies: Optional[List[Dict[str, Any]]] = None


class EnvironmentUpdate(BaseModel):
    """Schema for updating an environment."""
    name: Optional[str] = Field(None, min_length=1, max_length=100)
    url: Optional[str] = Field(None, min_length=1, max_length=500)
    browser_config: Optional[Dict[str, Any]] = None
    ignore_rules: Optional[Dict[str, Any]] = None
    auth_type: Optional[str] = Field(None, pattern='^(none|sso|cookies)$')
    sso_username: Optional[str] = None
    sso_password: Optional[str] = None
    sso_env: Optional[str] = Field(None, pattern='^(prod|staging|dev)$')
    cookies: Optional[List[Dict[str, Any]]] = None


class EnvironmentResponse(BaseModel):
    """Environment response schema."""
    id: UUID
    business_id: UUID
    name: str
    url: str
    browser_config: Optional[Dict[str, Any]] = None
    ignore_rules: Optional[Dict[str, Any]] = None
    auth_type: str
    sso_username: Optional[str] = None
    sso_env: str = 'prod'
    # Note: sso_password is not returned for security
    cookies: Optional[List[Dict[str, Any]]] = None
    created_at: datetime

    class Config:
        from_attributes = True


class EnvironmentCookiesResponse(BaseModel):
    """Response schema for generated environment cookies."""
    cookies: List[Dict[str, Any]] = Field(default_factory=list)
    source: str = Field(default='none', pattern='^(sso|environment|none)$')

"""Business schemas."""
from datetime import datetime
from typing import Any, Dict, List, Optional
from uuid import UUID

from pydantic import BaseModel, Field


class EnvironmentInBusiness(BaseModel):
    """Environment schema for nested use in business."""
    id: Optional[UUID] = None
    name: str
    url: str
    browser_config: Optional[Dict[str, Any]] = None
    ignore_rules: Optional[Dict[str, Any]] = None
    auth_type: str = 'none'
    sso_username: Optional[str] = None
    sso_password: Optional[str] = None
    sso_env: str = 'prod'
    cookies: Optional[List[Dict[str, Any]]] = None


class BusinessCreate(BaseModel):
    """Schema for creating a business."""
    name: str = Field(..., min_length=1, max_length=100)
    description: Optional[str] = None
    environments: List[EnvironmentInBusiness] = Field(default_factory=list)


class BusinessUpdate(BaseModel):
    """Schema for updating a business."""
    name: Optional[str] = Field(None, min_length=1, max_length=100)
    description: Optional[str] = None
    environments: Optional[List[EnvironmentInBusiness]] = None


class EnvironmentResponse(BaseModel):
    """Environment response schema."""
    id: UUID
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


class BusinessResponse(BaseModel):
    """Business response schema."""
    id: UUID
    name: str
    description: Optional[str] = None
    created_at: datetime
    environments: List[EnvironmentResponse] = Field(default_factory=list)

    class Config:
        from_attributes = True


class BusinessListResponse(BaseModel):
    """Business list response."""
    items: List[BusinessResponse]
    total: int

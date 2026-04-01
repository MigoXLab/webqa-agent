"""Business schemas."""
from datetime import datetime
from typing import Any, Dict, List, Optional
from uuid import UUID

from pydantic import BaseModel, Field, model_validator

from app.schemas.environment import AccountEntryResponse


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
    accounts: Optional[List[Dict[str, Any]]] = None


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
    accounts: Optional[List[AccountEntryResponse]] = None
    created_at: datetime

    class Config:
        from_attributes = True

    @model_validator(mode='before')
    @classmethod
    def parse_accounts(cls, data: Any) -> Any:
        """Parse raw JSONB dicts into AccountEntryResponse objects."""
        if hasattr(data, '__dict__'):
            raw_accounts = getattr(data, 'accounts', None)
        elif isinstance(data, dict):
            raw_accounts = data.get('accounts')
        else:
            return data

        if raw_accounts:
            parsed = []
            for acc in raw_accounts:
                if isinstance(acc, dict):
                    acc_copy = {k: v for k, v in acc.items() if k != 'sso_password'}
                    acc_copy['has_password'] = bool(acc.get('sso_password'))
                    parsed.append(AccountEntryResponse(**acc_copy))
                else:
                    parsed.append(acc)
            if hasattr(data, '__dict__'):
                obj_dict = {
                    'id': data.id,
                    'name': data.name,
                    'url': data.url,
                    'browser_config': data.browser_config,
                    'ignore_rules': data.ignore_rules,
                    'auth_type': data.auth_type,
                    'sso_username': data.sso_username,
                    'sso_env': data.sso_env,
                    'cookies': data.cookies,
                    'accounts': parsed,
                    'created_at': data.created_at,
                }
                return obj_dict
            else:
                data['accounts'] = parsed
        return data


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

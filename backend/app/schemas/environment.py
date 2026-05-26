"""Environment schemas."""
from datetime import datetime
from typing import Any, Dict, List, Optional
from uuid import UUID

from pydantic import BaseModel, Field, model_validator


class AccountEntry(BaseModel):
    """Schema for an account entry (write/input)."""
    name: str = Field(..., min_length=1, max_length=100)
    role: Optional[str] = Field(None, max_length=50)
    is_default: bool = False
    # SSO fields
    sso_username: Optional[str] = None
    sso_password: Optional[str] = None
    sso_env: Optional[str] = Field(None, pattern='^(prod|staging|dev)$')
    # Cookies fields
    cookies: Optional[List[Dict[str, Any]]] = None


class AccountEntryResponse(BaseModel):
    """Schema for an account entry (read/output). sso_password is excluded."""
    name: str
    role: Optional[str] = None
    is_default: bool = False
    sso_username: Optional[str] = None
    sso_env: Optional[str] = None
    cookies: Optional[List[Dict[str, Any]]] = None
    has_password: bool = False
    # sso_password intentionally omitted


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
    accounts: Optional[List[Dict[str, Any]]] = None


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
    accounts: Optional[List[Dict[str, Any]]] = None


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
    accounts: Optional[List[AccountEntryResponse]] = None
    created_at: datetime

    class Config:
        from_attributes = True

    @model_validator(mode='before')
    @classmethod
    def parse_accounts(cls, data: Any) -> Any:
        """Parse raw JSONB dicts into AccountEntryResponse objects."""
        # Handle ORM objects via __dict__
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
                # For ORM objects, wrap into a dict for Pydantic
                obj_dict = {
                    'id': data.id,
                    'business_id': data.business_id,
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


class EnvironmentCookiesResponse(BaseModel):
    """Response schema for generated environment cookies."""
    cookies: List[Dict[str, Any]] = Field(default_factory=list)
    source: str = Field(default='none', pattern='^(sso|environment|none)$')

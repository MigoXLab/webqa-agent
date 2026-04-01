"""Scheduled Task schemas."""
from datetime import datetime
from typing import List, Optional
from uuid import UUID

from pydantic import BaseModel, Field, field_validator


class ScheduledTaskCreate(BaseModel):
    """Schema for creating a scheduled task."""
    business_id: UUID
    name: str = Field(..., min_length=1, max_length=200)
    description: Optional[str] = None
    environment_id: UUID
    test_case_ids: List[UUID] = Field(..., min_length=1)
    model: str
    workers: int = Field(default=1, ge=1, le=5)
    resolutions: Optional[List[str]] = None
    cron_expression: str = Field(..., min_length=1, max_length=100)
    enabled: bool = True
    webhook_url: Optional[str] = Field(None, max_length=500)
    feishu_notify_user_id: Optional[str] = Field(None, max_length=500)

    @field_validator('cron_expression')
    @classmethod
    def validate_cron_expression(cls, v: str) -> str:
        """Validate cron expression format."""
        from app.utils.cron_utils import validate_cron_expression

        is_valid, error = validate_cron_expression(v)
        if not is_valid:
            raise ValueError(f'Invalid cron expression: {error}')
        return v


class ScheduledTaskUpdate(BaseModel):
    """Schema for updating a scheduled task."""
    name: Optional[str] = Field(None, min_length=1, max_length=200)
    description: Optional[str] = None
    environment_id: Optional[UUID] = None
    test_case_ids: Optional[List[UUID]] = Field(None, min_length=1)
    model: Optional[str] = None
    workers: Optional[int] = Field(None, ge=1, le=5)
    resolutions: Optional[List[str]] = None
    cron_expression: Optional[str] = Field(None, min_length=1, max_length=100)
    enabled: Optional[bool] = None
    webhook_url: Optional[str] = Field(None, max_length=500)
    feishu_notify_user_id: Optional[str] = Field(None, max_length=500)

    @field_validator('cron_expression')
    @classmethod
    def validate_cron_expression(cls, v: Optional[str]) -> Optional[str]:
        """Validate cron expression format."""
        if v is None:
            return v

        from app.utils.cron_utils import validate_cron_expression

        is_valid, error = validate_cron_expression(v)
        if not is_valid:
            raise ValueError(f'Invalid cron expression: {error}')
        return v


class ScheduledTaskResponse(BaseModel):
    """Scheduled task response schema."""
    id: UUID
    business_id: UUID
    business_name: Optional[str] = None
    name: str
    description: Optional[str] = None
    environment_id: UUID
    environment_name: Optional[str] = None
    test_case_ids: List[str]
    model: str
    workers: int
    resolutions: Optional[List[str]] = None
    cron_expression: str
    enabled: bool
    webhook_url: Optional[str] = None
    feishu_notify_user_id: Optional[str] = None
    last_run_at: Optional[datetime] = None
    next_run_at: Optional[datetime] = None
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class ScheduledTaskListResponse(BaseModel):
    """Scheduled task list response."""
    items: List[ScheduledTaskResponse]
    total: int


class ScheduledTaskToggleRequest(BaseModel):
    """Request to toggle scheduled task enabled status."""
    enabled: bool


class CronValidationRequest(BaseModel):
    """Request to validate cron expression."""
    cron_expression: str


class CronValidationResponse(BaseModel):
    """Response for cron validation."""
    is_valid: bool
    error: Optional[str] = None
    next_run_times: Optional[List[datetime]] = None  # Next 5 run times in UTC+8

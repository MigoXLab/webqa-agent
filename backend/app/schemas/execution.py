"""Execution schemas."""
from datetime import datetime
from typing import Any, Dict, List, Optional
from uuid import UUID

from app.config import get_settings
from pydantic import BaseModel, Field, field_validator

settings = get_settings()


class ExecutionCreate(BaseModel):
    """Schema for creating an execution (manual or debug trigger)."""
    business_id: UUID
    environment_id: UUID
    test_case_ids: List[UUID] = Field(..., min_length=1)
    model: str = settings.LLM_DEFAULT_MODEL
    workers: int = Field(default=settings.DEFAULT_WORKERS, ge=1)
    trigger_type: str = Field(default='manual', pattern='^(manual|debug)$')

    @field_validator('workers')
    @classmethod
    def validate_workers(cls, v):
        if v > settings.MAX_WORKERS:
            raise ValueError(f'workers 不能超过 {settings.MAX_WORKERS}')
        return v


class ExecutionResponse(BaseModel):
    """Execution response schema."""
    id: UUID
    business_id: UUID
    business_name: Optional[str] = None
    environment_id: Optional[UUID] = None
    environment_name: Optional[str] = None
    trigger_type: str
    scheduled_task_id: Optional[UUID] = None
    model: str
    workers: int
    test_case_ids: List[str]
    status: str
    oss_report_url: Optional[str] = None
    local_report_path: Optional[str] = None
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    created_at: datetime
    error_message: Optional[str] = None
    result_count: Optional[Dict[str, Any]] = None

    class Config:
        from_attributes = True


class ExecutionListResponse(BaseModel):
    """Execution list response."""
    items: List[ExecutionResponse]
    total: int


class ExecutionStatusResponse(BaseModel):
    """Execution status response for polling."""
    id: UUID
    status: str
    oss_report_url: Optional[str] = None
    result_count: Optional[Dict[str, Any]] = None
    error_message: Optional[str] = None

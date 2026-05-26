"""Execution schemas."""
from datetime import datetime
from typing import Any, Dict, List, Optional
from uuid import UUID

from app.config import get_settings
from pydantic import BaseModel, Field, field_validator, model_validator

settings = get_settings()


class ExecutionCreate(BaseModel):
    """Schema for creating an execution (manual, debug, or gen trigger)."""
    business_id: Optional[UUID] = None
    environment_id: Optional[UUID] = None
    test_case_ids: Optional[List[UUID]] = Field(default=None)
    model: str = settings.LLM_DEFAULT_MODEL
    workers: int = Field(default=settings.DEFAULT_WORKERS, ge=1)
    resolutions: Optional[List[str]] = None
    trigger_type: str = Field(default='manual', pattern='^(manual|debug|gen|mcp_quick)$')
    # Debug mode: frontend passes case data directly; not persisted to DB
    # Format: {case_id_str: {login_required: bool, name: str, steps: [...], ...}}
    case_data: Optional[Dict[str, Any]] = None
    # Gen mode config (raw dict; api_key injected by executor)
    gen_config: Optional[Dict[str, Any]] = None

    @field_validator('workers')
    @classmethod
    def validate_workers(cls, v):
        if v > settings.MAX_WORKERS:
            raise ValueError(f'workers 不能超过 {settings.MAX_WORKERS}')
        return v

    @model_validator(mode='after')
    def validate_trigger_type_requirements(self):
        trigger_type = self.trigger_type
        test_case_ids = self.test_case_ids
        gen_config = self.gen_config
        business_id = self.business_id

        if trigger_type in ('manual', 'debug'):
            if not business_id:
                raise ValueError(f'{trigger_type} mode requires business_id')
            if not test_case_ids or len(test_case_ids) < 1:
                raise ValueError(f'{trigger_type} mode requires at least one test_case_id')
        elif trigger_type == 'gen':
            if not gen_config:
                raise ValueError('gen mode requires gen_config')
        elif trigger_type == 'mcp_quick':
            if not gen_config:
                raise ValueError('mcp_quick mode requires gen_config')
            if not gen_config.get('url'):
                raise ValueError('mcp_quick mode requires url in gen_config')
            if not gen_config.get('task'):
                raise ValueError('mcp_quick mode requires task in gen_config')

        return self


class ExecutionResponse(BaseModel):
    """Execution response schema."""
    id: UUID
    business_id: Optional[UUID] = None
    business_name: Optional[str] = None
    environment_id: Optional[UUID] = None
    environment_name: Optional[str] = None
    trigger_type: str
    scheduled_task_id: Optional[UUID] = None
    model: str
    workers: int
    resolutions: Optional[List[str]] = None
    test_case_ids: List[str]
    status: str
    oss_report_url: Optional[str] = None
    report_url: Optional[str] = None
    data_flow_report_url: Optional[str] = None
    local_report_path: Optional[str] = None
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    created_at: datetime
    error_message: Optional[str] = None
    result_count: Optional[Dict[str, Any]] = None
    config: Optional[Dict[str, Any]] = None

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
    report_url: Optional[str] = None
    data_flow_report_url: Optional[str] = None
    result_count: Optional[Dict[str, Any]] = None
    error_message: Optional[str] = None

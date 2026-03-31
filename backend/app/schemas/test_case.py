"""TestCase schemas."""
from datetime import datetime
from typing import Any, Dict, List, Optional, Union
from uuid import UUID

from pydantic import BaseModel, Field


class TestStepArgs(BaseModel):
    """Test step arguments."""
    # file_path supports single file (string) or multiple files (array)
    file_path: Optional[Union[str, List[str]]] = None
    use_context: Optional[bool] = None

    # Allow additional args
    class Config:
        extra = 'allow'


class TestStep(BaseModel):
    """Test step schema."""
    step_type: str = Field(..., pattern='^(action|verify|switch_account)$')
    description: Optional[str] = None  # For action type
    assertion: Optional[str] = None    # For verify type
    switch_account: Optional[str] = None  # Target account name for switch_account type
    args: Optional[Dict[str, Any]] = None


class TestCaseCreate(BaseModel):
    """Schema for creating a test case."""
    business_id: UUID
    name: str = Field(..., min_length=1, max_length=200)
    description: Optional[str] = None
    login_required: bool = False
    account: Optional[str] = Field(None, max_length=100)
    steps: List[TestStep] = Field(..., min_length=1)
    version: Optional[str] = Field(None, max_length=50)
    snapshot: Optional[str] = None
    use_snapshot: Optional[str] = None
    status: str = Field(default='active', pattern='^(active|draft|disabled)$')


class TestCaseUpdate(BaseModel):
    """Schema for updating a test case."""
    name: Optional[str] = Field(None, min_length=1, max_length=200)
    description: Optional[str] = None
    login_required: Optional[bool] = None
    account: Optional[str] = Field(None, max_length=100)
    steps: Optional[List[TestStep]] = None
    version: Optional[str] = Field(None, max_length=50)
    snapshot: Optional[str] = None
    use_snapshot: Optional[str] = None
    status: Optional[str] = Field(None, pattern='^(active|draft|disabled)$')
    sort_order: Optional[int] = None


class TestCaseResponse(BaseModel):
    """Test case response schema."""
    id: UUID
    business_id: UUID
    name: str
    description: Optional[str] = None
    login_required: bool
    account: Optional[str] = None
    steps: List[Dict[str, Any]]
    version: Optional[str] = None
    snapshot: Optional[str] = None
    use_snapshot: Optional[str] = None
    status: str
    sort_order: int = 0
    created_at: datetime

    class Config:
        from_attributes = True


class TestCaseListResponse(BaseModel):
    """Test case list response."""
    items: List[TestCaseResponse]
    total: int


# YAML Import/Export schemas
class YAMLTestStep(BaseModel):
    """YAML format test step."""
    action: Optional[str] = None
    verify: Optional[str] = None
    switch_account: Optional[str] = None
    args: Optional[Dict[str, Any]] = None


class YAMLTestCase(BaseModel):
    """YAML format test case."""
    name: str
    login_required: Optional[bool] = False
    account: Optional[str] = None
    steps: List[YAMLTestStep]
    version: Optional[str] = None
    snapshot: Optional[str] = None
    use_snapshot: Optional[str] = None


class TestCaseImport(BaseModel):
    """Schema for importing test cases from YAML."""
    yaml_content: str


class TestCaseExport(BaseModel):
    """Schema for exported YAML content."""
    yaml_content: str

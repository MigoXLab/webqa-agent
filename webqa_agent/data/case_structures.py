"""Case Mode Data Structures.

This module defines the data structures for YAML-defined test cases. Supports
action and verify steps with extensible arguments.
"""

from typing import Any, Dict, List, Optional, Union

from pydantic import BaseModel, ConfigDict, model_validator

from webqa_agent.data.test_structures import TestStatus

# ============================================================================
# Action Arguments
# ============================================================================

class ActionArgs(BaseModel):
    """Arguments for action step.

    Attributes:
        file_path: File path(s) for upload operations. Supports single path or list.
        timeout: Action timeout (milliseconds).
    """
    model_config = ConfigDict(extra='forbid')

    file_path: Optional[Union[str, List[str]]] = None
    timeout: Optional[int] = None


# ============================================================================
# Verify Arguments
# ============================================================================

class VerifyArgs(BaseModel):
    """Arguments for verify step.

    Attributes:
        use_context: Whether to use previous step's context (result + screenshots).
        context: Alias for use_context (backward compatible).
        timeout: Verification timeout (milliseconds).
    """
    model_config = ConfigDict(extra='forbid')

    use_context: Optional[bool] = False
    context: Optional[bool] = None  # Alias for use_context
    timeout: Optional[int] = None

    @property
    def should_use_context(self) -> bool:
        """Get whether to use context (supports both use_context and context
        fields)."""
        return self.use_context or self.context or False


# ============================================================================
# Step Definitions
# ============================================================================

class StepAction(BaseModel):
    """Action step configuration.

    Supports two formats in YAML:

    1. Simple string:
        - action: click login button

    2. Full object:
        - action:
            description: upload file 'sample.pdf'
            args:
              file_path: ./path/to/file.pdf
    """
    model_config = ConfigDict(extra='forbid')

    description: str
    args: Optional[ActionArgs] = None

    @model_validator(mode='before')
    @classmethod
    def parse_yaml_format(cls, data: Any) -> Dict[str, Any]:
        """Auto-convert string format to dict format."""
        if data is None:
            raise ValueError('Action step content cannot be empty. Check indentation?')
        if isinstance(data, str):
            return {'description': data}
        if isinstance(data, dict):
            # Backward compatible: 'case' -> 'description'
            if 'case' in data and 'description' not in data:
                data['description'] = data.pop('case')
        return data


class StepVerify(BaseModel):
    """Verify step configuration.

    Supports two formats in YAML:

    1. Simple string:
        - verify: verify page display correctly

    2. Full object:
        - verify:
            assertion: verify reference source popup display correctly
            args:
              use_context: true
    """
    model_config = ConfigDict(extra='forbid')

    assertion: str
    args: Optional[VerifyArgs] = None

    @model_validator(mode='before')
    @classmethod
    def parse_yaml_format(cls, data: Any) -> Dict[str, Any]:
        """Auto-convert string format to dict format."""
        if data is None:
            raise ValueError('Verify step content cannot be empty. Check indentation?')
        if isinstance(data, str):
            return {'assertion': data}
        return data


# ============================================================================
# Case Step
# ============================================================================

class CaseStep(BaseModel):
    """A single step in a test case (either action or verify).

    Example YAML:
        steps:
          - action: click login button
          - verify: verify page display correctly
    """
    model_config = ConfigDict(extra='forbid')

    step_type: str  # 'action' or 'verify'
    action: Optional[StepAction] = None
    verify: Optional[StepVerify] = None

    @model_validator(mode='before')
    @classmethod
    def parse_yaml_format(cls, data: Any) -> Dict[str, Any]:
        """Auto-detect step type and parse action/verify."""
        if not isinstance(data, dict):
            raise ValueError(f'Step must be a dict, got {type(data)}')

        if 'action' in data:
            # Check for extra fields in CaseStep
            extra_keys = set(data.keys()) - {'action'}
            if extra_keys:
                raise ValueError(f'Extra fields in action step: {extra_keys}. Check indentation?')
            
            return {
                'step_type': 'action',
                'action': data['action']  # StepAction will handle its own parsing
            }
        elif 'verify' in data:
            # Check for extra fields in CaseStep
            extra_keys = set(data.keys()) - {'verify'}
            if extra_keys:
                raise ValueError(f'Extra fields in verify step: {extra_keys}. Check indentation?')

            return {
                'step_type': 'verify',
                'verify': data['verify']  # StepVerify will handle its own parsing
            }
        else:
            raise ValueError(f'Step must contain "action" or "verify": {data}')


# ============================================================================
# Case Definition
# ============================================================================

class Case(BaseModel):
    """Test case configuration from YAML.

    Example YAML:
        cases:
          - name: login test
            steps:
              - action: input username
              - action: input password
              - action: click login button
              - verify: verify login successfully
    """
    model_config = ConfigDict(extra='forbid')

    name: str = 'Unnamed Case'
    steps: List[CaseStep] = []

    @classmethod
    def from_yaml_list(cls, cases_list: List[Dict[str, Any]]) -> List['Case']:
        """Parse multiple cases from YAML list."""
        return [cls(**case_dict) for case_dict in cases_list]


# ============================================================================
# Step Context (for verify with use_context)
# ============================================================================

class StepContext(BaseModel):
    """Context from previous step execution.

    Used when verify step has use_context=True to access previous step's
    execution result and screenshots.
    """
    description: str
    result: Optional[Dict[str, Any]] = None

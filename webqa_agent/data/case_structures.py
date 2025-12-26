"""Case Mode Data Structures for YAML-defined test cases."""

from typing import Any, Dict, List, Optional, Union

from pydantic import BaseModel, ConfigDict, model_validator


class ActionArgs(BaseModel):
    """Arguments for action step (file_path, timeout)."""
    model_config = ConfigDict(extra='forbid')

    file_path: Optional[Union[str, List[str]]] = None
    timeout: Optional[int] = None


class VerifyArgs(BaseModel):
    """Arguments for verify step (use_context, timeout)."""
    model_config = ConfigDict(extra='forbid')

    use_context: Optional[bool] = False
    context: Optional[bool] = None  # Alias for use_context
    timeout: Optional[int] = None

    @property
    def should_use_context(self) -> bool:
        """Check if context should be used (supports both field names)."""
        return self.use_context or self.context or False


def _parse_string_to_dict(data: Any, field_name: str) -> Dict[str, Any]:
    """Convert string format to dict format for action/verify steps."""
    if data is None:
        raise ValueError(f'{field_name.capitalize()} step content cannot be empty. Check indentation?')
    if isinstance(data, str):
        return {field_name: data}
    return data


class StepAction(BaseModel):
    """Action step configuration.

    Supports two formats in YAML:

    1. Simple string:
        - action: click login button

    2. Flat format with args as sibling:
        - action: upload file 'sample.pdf'
          args:
            file_path: ./path/to/file.pdf
    """
    model_config = ConfigDict(extra='forbid')

    description: str
    args: Optional[ActionArgs] = None

    @model_validator(mode='before')
    @classmethod
    def parse_yaml_format(cls, data: Any) -> Dict[str, Any]:
        return _parse_string_to_dict(data, 'description')


class StepVerify(BaseModel):
    """Verify step configuration.

    Supports two formats in YAML:

    1. Simple string:
        - verify: verify page display correctly

    2. Flat format with args as sibling:
        - verify: verify reference source popup display correctly
          args:
            use_context: true
    """
    model_config = ConfigDict(extra='forbid')

    assertion: str
    args: Optional[VerifyArgs] = None

    @model_validator(mode='before')
    @classmethod
    def parse_yaml_format(cls, data: Any) -> Dict[str, Any]:
        return _parse_string_to_dict(data, 'assertion')


def _merge_step_args(step_key: str, step_value: Any, args_value: Any, content_field: str) -> Dict[str, Any]:
    """Merge flat-format args into step value (action/verify + args)."""
    if args_value is not None:
        if not isinstance(step_value, str):
            raise ValueError(
                f'Invalid {step_key} format. Use flat format:\n'
                f'  - {step_key}: "description"\n'
                f'    args:\n'
                f'      file_path: ./test.jpg'
            )
        return {content_field: step_value, 'args': args_value}
    return step_value


class CaseStep(BaseModel):
    """A single step in a test case (either action or verify).

    use_context: true
    """
    model_config = ConfigDict(extra='forbid')

    step_type: str  # 'action' or 'verify'
    action: Optional[StepAction] = None
    verify: Optional[StepVerify] = None

    @model_validator(mode='before')
    @classmethod
    def parse_yaml_format(cls, data: Any) -> Dict[str, Any]:
        """Parse YAML step with flat format support (args as sibling)."""
        if not isinstance(data, dict):
            raise ValueError(f'Step must be a dict, got {type(data)}')

        # Determine step type
        step_key = 'action' if 'action' in data else 'verify' if 'verify' in data else None
        if not step_key:
            raise ValueError(f'Step must contain "action" or "verify": {data}')

        # Validate no extra fields
        extra_keys = set(data.keys()) - {step_key, 'args'}
        if extra_keys:
            raise ValueError(f'Extra fields in {step_key} step: {extra_keys}. Check indentation?')

        # Merge args if present (flat format)
        content_field = 'description' if step_key == 'action' else 'assertion'
        merged_value = _merge_step_args(step_key, data[step_key], data.get('args'), content_field)

        return {'step_type': step_key, step_key: merged_value}


class Case(BaseModel):
    """Test case with name and steps."""
    model_config = ConfigDict(extra='allow')

    name: str = 'Unnamed Case'
    steps: List[CaseStep] = []

    @classmethod
    def from_yaml_list(cls, cases_list: List[Dict[str, Any]]) -> List['Case']:
        """Parse multiple cases from YAML list."""
        return [cls(**case_dict) for case_dict in cases_list]


class StepContext(BaseModel):
    """Context from previous step execution (for use_context=True)."""
    description: str
    result: Optional[Dict[str, Any]] = None

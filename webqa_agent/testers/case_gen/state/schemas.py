import operator
from typing import Annotated, Any, List, Optional

from typing_extensions import TypedDict


class TestStep(TypedDict, total=False):
    """Test step structure (supports core and custom tools).

    Core step fields (backward compatible):
        action: Action instruction for browser interactions
        verify: Assertion instruction for functional verification
        ux_verify: UX verification instruction for visual quality checks

    Custom tool fields:
        type: Custom step type (e.g., 'custom_api_test')
        instruction: Custom tool instruction
    """

    # Core step fields (backward compatible)
    action: str
    verify: str
    ux_verify: str

    # Custom tool fields
    type: str  # Custom step type (e.g., 'custom_api_test')
    instruction: str  # Custom tool instruction


class MainGraphState(TypedDict):
    """Represents the overall state of the main testing workflow."""

    # Core configuration
    url: str
    business_objectives: Optional[str]
    language: Optional[str]
    cookies: Optional[str]

    # Test data
    test_cases: List[dict]
    completed_cases: Annotated[list, operator.add]
    recorded_cases: Annotated[list, operator.add]

    # Control flags
    generate_only: bool
    skip_reflection: bool
    dynamic_step_generation: dict

    # Infrastructure
    session_pool: Any                    # BrowserSessionPool instance
    llm_config: Optional[dict]           # LLM config for creating UITester

    # Output
    final_report: Optional[dict]

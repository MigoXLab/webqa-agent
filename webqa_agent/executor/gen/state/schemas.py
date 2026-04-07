import operator
from typing import Annotated, Any, List, Literal, Optional

from typing_extensions import TypedDict


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
    planning_mode: Optional[Literal['explore', 'focused']]
    max_replan_count: Optional[int]
    dynamic_step_generation: dict
    enabled_custom_tools: Optional[List[str]]  # List of enabled custom tool step_types

    # Infrastructure
    session_pool: Any                    # BrowserSessionPool instance
    llm_config: Optional[dict]           # LLM config for creating UITester
    report_config: Optional[dict]        # Report config
    browser_config: Optional[dict]       # Browser config
    test_file_library: Any               # TestFileLibrary instance (optional)

    # Output
    final_report: Optional[dict]
    planning_error: Optional[str]

import operator
from typing import Annotated, Any, List, Optional

from typing_extensions import TypedDict


class MainGraphState(TypedDict):
    """Represents the overall state of the main testing workflow."""

    url: str
    business_objectives: Optional[str]
    language: Optional[str]
    cookies: Optional[str]
    test_cases: List[dict]
    # To manage the loop
    current_test_case_index: int
    current_case: Optional[dict]
    completed_cases: Annotated[list, operator.add]
    reflection_history: Annotated[list, operator.add]
    generate_only: bool
    # For replanning logic
    is_replan: bool
    replan_count: int
    replanned_cases: Optional[List[dict]]
    remaining_objectives: Optional[str]
    ui_tester_instance: Any
    final_report: Optional[dict]
    # For critical failure handling
    skip_reflection: bool
    dynamic_step_generation: dict
    # For CentralCaseRecorder data storage
    recorded_cases: Annotated[list, operator.add]
    # For parallel execution with session pool
    session_pool: Any                    # BrowserSessionPool instance
    llm_config: Optional[dict]           # LLM config for creating UITester
    is_batch_complete: bool              # Batch sync flag

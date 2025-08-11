import operator
from typing import Annotated, Any, List, Optional

from typing_extensions import TypedDict


class MainGraphState(TypedDict):
    """Represents the overall state of the main testing workflow."""

    url: str
    business_objectives: Optional[str]
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

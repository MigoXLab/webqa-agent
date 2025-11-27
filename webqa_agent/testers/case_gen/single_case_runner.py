"""Single Case Runner for Parallel Execution.

This module provides a wrapper to execute a single test case through the
LangGraph agent_worker_node, enabling parallel case execution while preserving
all LangGraph logic (reflection, dynamic steps, etc.).
"""

import asyncio
import logging
from typing import Any, Dict, List, Optional

from webqa_agent.actions.action_handler import ActionHandler
from webqa_agent.testers.case_gen.agents.execute_agent import agent_worker_node
from webqa_agent.testers.function_tester import UITester
from webqa_agent.utils import Display


class SingleCaseRunner:
    """Executes a single test case through LangGraph's agent_worker_node.

    This runner provides a lightweight interface for executing individual cases
    in parallel, bypassing the full LangGraph orchestration while preserving
    all execution logic.
    """

    def __init__(self, llm_config: Dict[str, Any]):
        """Initialize the single case runner.

        Args:
            llm_config: LLM configuration dict
        """
        self.llm_config = llm_config

    async def execute_case(
        self,
        case: Dict[str, Any],
        session,  # BrowserSession
        url: str,
        cookies: Optional[list] = None,
        dynamic_step_generation: Optional[Dict] = None,
        language: str = 'en-US'
    ) -> Dict[str, Any]:
        """Execute a single test case using LangGraph's agent_worker_node.

        This method:
        1. Creates a UITester instance with the provided session
        2. Navigates to the target URL
        3. Calls agent_worker_node to execute the case
        4. Returns the case result with all recorded data

        Args:
            case: Test case dict from planner with structure:
                {
                    "name": str,
                    "objective": str,
                    "steps": List[dict],
                    "success_criteria": List[str],
                    "preamble_actions": List[str] (optional),
                    "reset_session": bool (optional),
                    "url": str
                }
            session: BrowserSession instance from pool
            url: Target URL to navigate to
            cookies: Optional cookies for session
            dynamic_step_generation: Config dict for dynamic step generation
            language: Language for UI display ('en-US' or 'zh-CN')

        Returns:
            Dict with execution results:
            {
                "case_result": {
                    "case_name": str,
                    "final_summary": str,
                    "status": "passed"|"failed"|"warning",
                    "failure_type": "critical"|"recoverable"|None
                },
                "recorded_case": {
                    "name": str,
                    "steps": List[dict],  # Full step data with screenshots
                    "status": str,
                    "final_summary": str
                },
                "modified_case": dict (if dynamic steps added)
            }
        """
        case_name = case.get("name", "Unnamed Case")
        cookies = cookies or []
        dynamic_step_config = dynamic_step_generation or {
            "enabled": True,
            "max_dynamic_steps": 5,
            "min_elements_threshold": 2
        }

        default_text = '智能功能测试' if language == 'zh-CN' else 'AI Function Test'

        # Record case start time
        from datetime import datetime
        case_start_time = datetime.now()

        try:
            with Display.display(f"{default_text} - {case_name}"):
                logging.info(f"[SingleCaseRunner] Executing case: {case_name}")

                # Create UITester instance with the session
                ui_tester = UITester(llm_config=self.llm_config, browser_session=session)
                await ui_tester.initialize(browser_session=session)

                # Handle session setup (navigation)
                await self._setup_case_session(
                    ui_tester=ui_tester,
                    case=case,
                    url=url,
                    cookies=cookies
                )

                # Prepare worker input state
                worker_input_state = {
                    "test_case": case,
                    "completed_cases": [],  # Empty for isolated case execution
                    "dynamic_step_generation": dynamic_step_config
                }

                # Execute case through agent_worker_node
                logging.debug(f"[SingleCaseRunner] Invoking agent_worker_node for case: {case_name}")
                result = await agent_worker_node(
                    worker_input_state,
                    config={"configurable": {"ui_tester_instance": ui_tester}}
                )

                # Extract results
                case_result = result.get("case_result")
                modified_case = result.get("modified_case")
                recorded_case = result.get("recorded_case")

                # Calculate case execution time
                case_end_time = datetime.now()
                case_duration = (case_end_time - case_start_time).total_seconds()

                if case_result:
                    status = case_result.get("status", "unknown")
                    logging.info(f"[SingleCaseRunner] Case '{case_name}' completed with status: {status}")

                    # Add timing information using helper method
                    case_result.update(self._format_timing_info(case_start_time, case_end_time))
                else:
                    logging.warning(f"[SingleCaseRunner] Case '{case_name}' returned no case_result")

                return {
                    "case_result": case_result,
                    "recorded_case": recorded_case,
                    "modified_case": modified_case,
                    "case_name": case_name
                }

        except asyncio.CancelledError:
            logging.warning(f"[SingleCaseRunner] Case '{case_name}' execution was cancelled")

            # Calculate execution time up to interruption
            case_end_time = datetime.now()
            case_duration = (case_end_time - case_start_time).total_seconds()

            # Extract planned steps from case definition
            planned_steps = case.get("steps", [])
            planned_total = len(planned_steps)

            # Try to extract partial execution data from recorder
            partial_case_data = None
            completed_steps = 0

            if hasattr(ui_tester, 'central_case_recorder') and ui_tester.central_case_recorder:
                try:
                    recorder = ui_tester.central_case_recorder
                    partial_case_data = recorder.get_case_data()
                    completed_steps = len(partial_case_data.get('steps', []))

                    # Add remaining unexecuted steps as placeholders
                    if planned_total > completed_steps:
                        for i in range(completed_steps, planned_total):
                            planned_step = planned_steps[i]
                            step_desc = self._format_planned_step_description(planned_step)

                            # Add placeholder for unexecuted step
                            unexecuted_step = {
                                "id": i + 1,
                                "number": i + 1,
                                "type": "planned",
                                "description": step_desc,
                                "screenshots": [],
                                "modelIO": "",
                                "actions": [],
                                "status": "not_executed",
                                "end_time": "",
                                "reason": "Interrupted before execution"
                            }
                            partial_case_data["steps"].append(unexecuted_step)

                    # Generate detailed progress summary using helper method
                    progress_summary = self._format_progress_summary(
                        planned_steps,
                        completed_steps,
                        prefix="Case execution was interrupted",
                        include_remaining=True
                    )

                    # Finalize with interrupted status
                    recorder.finish_case(
                        final_status="cancelled",
                        final_summary=progress_summary
                    )

                    # Get updated data after finalize
                    partial_case_data = recorder.get_case_data()

                    logging.info(
                        f"[SingleCaseRunner] Captured partial execution: {progress_summary}"
                    )
                except Exception as extract_error:
                    logging.error(f"Failed to extract partial data: {extract_error}")
                    progress_summary = f"Case execution was interrupted. {completed_steps} steps were completed before interruption."
            else:
                progress_summary = f"Case execution was interrupted. Unable to determine progress (no recorder available)."

            # Return cancelled result with partial data
            cancelled_result = {
                "status": "cancelled"
            }
            # Add timing information using helper method
            cancelled_result.update(self._format_timing_info(case_start_time, case_end_time))

            return {
                "case_result": cancelled_result,
                "recorded_case": partial_case_data,  # Include partial execution data with placeholders
                "modified_case": None,
                "case_name": case_name,
                "error": "Test was cancelled"
            }

        except Exception as e:
            logging.error(f"[SingleCaseRunner] Error executing case '{case_name}': {e}", exc_info=True)

            # Calculate execution time up to error
            case_end_time = datetime.now()
            case_duration = (case_end_time - case_start_time).total_seconds()

            # Extract planned steps for progress info
            planned_steps = case.get("steps", [])
            planned_total = len(planned_steps)

            # Try to extract partial execution data from recorder (same logic as CancelledError)
            partial_case_data = None
            completed_steps = 0

            if hasattr(ui_tester, 'central_case_recorder') and ui_tester.central_case_recorder:
                try:
                    recorder = ui_tester.central_case_recorder
                    partial_case_data = recorder.get_case_data()
                    completed_steps = len(partial_case_data.get('steps', []))

                    logging.info(
                        f"[SingleCaseRunner] Extracted {completed_steps} completed steps from recorder before error"
                    )
                except Exception as extract_error:
                    logging.error(f"Failed to extract partial data on error: {extract_error}")
            else:
                logging.warning(f"No recorder available to extract partial execution data")

            # Return error result
            error_result = {
                "status": "failed"
            }
            # Add timing information using helper method
            error_result.update(self._format_timing_info(case_start_time, case_end_time))

            return {
                "case_result": error_result,
                "recorded_case": partial_case_data,  # Now includes partial execution data if available
                "modified_case": None,
                "case_name": case_name,
                "error": str(e)
            }

    async def _setup_case_session(
        self,
        ui_tester: UITester,
        case: Dict,
        url: str,
        cookies: list
    ):
        """Set up browser session for case execution.

        Handles navigation and session reset based on case configuration.

        Args:
            ui_tester: UITester instance
            case: Test case dict
            url: Target URL
            cookies: Session cookies
        """
        case_name = case.get("name", "Unnamed")
        case_url = case.get("url", url)

        # Check if case requires session reset
        reset_session = case.get("reset_session", False)

        if reset_session:
            logging.debug(f"[SingleCaseRunner] Resetting session for case: {case_name}, navigating to {case_url}")
        else:
            logging.debug(f"[SingleCaseRunner] Using existing session for case: {case_name}")

        # Start session and navigate
        await ui_tester.start_session(case_url)
        page = await ui_tester.get_current_page()

        # Perform navigation with ActionHandler
        action_handler = ActionHandler()
        await action_handler.initialize(page=page, driver=ui_tester.driver)
        await action_handler.go_to_page(page, url, cookies=cookies)

        logging.debug(f"[SingleCaseRunner] Session setup complete for case: {case_name}")

    def _format_planned_step_description(self, planned_step: Dict) -> str:
        """Format a planned step into a human-readable description.

        Args:
            planned_step: Planned step dict from test case definition

        Returns:
            Formatted step description string
        """
        # Try to extract meaningful description from planned step
        if isinstance(planned_step, dict):
            if "action" in planned_step:
                return f"action: {planned_step['action']}"
            elif "verify" in planned_step:
                return f"verify: {planned_step['verify']}"
            elif "description" in planned_step:
                return planned_step["description"]
            else:
                # Fallback: use the step dict representation
                return str(planned_step)
        else:
            return str(planned_step)

    def _format_step_info(
        self,
        planned_total: int,
        completed_steps: int
    ) -> str:
        """Format step information with dynamic step handling.

        Args:
            planned_total: Total number of planned steps
            completed_steps: Number of steps actually completed

        Returns:
            Formatted step information string
        """
        if completed_steps > planned_total:
            # Dynamic steps were added during execution
            dynamic_count = completed_steps - planned_total
            return f"{completed_steps} steps completed ({planned_total} planned + {dynamic_count} dynamic)"
        else:
            # Normal or partial execution
            return f"{completed_steps}/{planned_total} steps completed"

    def _format_progress_summary(
        self,
        planned_steps: List,
        completed_steps: int,
        prefix: str = "",
        include_remaining: bool = True
    ) -> str:
        """Format complete progress summary with percentage.

        Args:
            planned_steps: List of planned steps
            completed_steps: Number of steps completed
            prefix: Optional prefix for summary (e.g., "Case execution was interrupted.")
            include_remaining: Whether to include remaining steps info

        Returns:
            Formatted progress summary string
        """
        planned_total = len(planned_steps)

        if planned_total == 0:
            return f"{prefix} Progress: {completed_steps} steps completed." if prefix else f"{completed_steps} steps completed."

        # Calculate progress percentage (cap at 100%)
        progress_pct = min(100, int((completed_steps / planned_total * 100)))

        # Format step information
        step_info = self._format_step_info(planned_total, completed_steps)

        # Build summary
        parts = []
        if prefix:
            parts.append(prefix)

        parts.append(f"Progress: {step_info} ({progress_pct}%)")

        # Add remaining steps info if requested and applicable
        if include_remaining and completed_steps < planned_total:
            remaining = planned_total - completed_steps
            parts.append(f"{remaining} steps were not executed")

        return ". ".join(parts) + "."

    def _format_timing_info(
        self,
        start_time,  # datetime
        end_time  # datetime
    ) -> Dict[str, Any]:
        """Format timing information for case execution.

        Args:
            start_time: Case start time (datetime object)
            end_time: Case end time (datetime object)

        Returns:
            Dict with formatted timing information:
            {
                "start_time": str,  # Formatted as "YYYY-MM-DD HH:MM:SS"
                "end_time": str,    # Formatted as "YYYY-MM-DD HH:MM:SS"
                "duration": float   # Duration in seconds
            }
        """
        return {
            "start_time": start_time.strftime("%Y-%m-%d %H:%M:%S"),
            "end_time": end_time.strftime("%Y-%m-%d %H:%M:%S"),
            "duration": (end_time - start_time).total_seconds()
        }


async def execute_single_case_standalone(
    case: Dict[str, Any],
    session,  # BrowserSession
    llm_config: Dict[str, Any],
    url: str,
    cookies: Optional[list] = None,
    dynamic_step_generation: Optional[Dict] = None,
    language: str = 'en-US'
) -> Dict[str, Any]:
    """Standalone function to execute a single case (convenience wrapper).

    This function provides a simple interface for parallel execution without
    needing to create a SingleCaseRunner instance.

    Args:
        case: Test case dict
        session: BrowserSession instance
        llm_config: LLM configuration dict
        url: Target URL
        cookies: Optional cookies
        dynamic_step_generation: Optional dynamic step config
        language: UI language

    Returns:
        Dict with execution results (see SingleCaseRunner.execute_case)
    """
    runner = SingleCaseRunner(llm_config=llm_config)
    return await runner.execute_case(
        case=case,
        session=session,
        url=url,
        cookies=cookies,
        dynamic_step_generation=dynamic_step_generation,
        language=language
    )

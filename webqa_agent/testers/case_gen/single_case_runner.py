"""Single Case Runner for Parallel Execution.

This module provides a wrapper to execute a single test case through the
LangGraph agent_worker_node, enabling parallel case execution while preserving
all LangGraph logic (reflection, dynamic steps, etc.).
"""

import logging
from typing import Any, Dict, Optional

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

                if case_result:
                    status = case_result.get("status", "unknown")
                    logging.info(f"[SingleCaseRunner] Case '{case_name}' completed with status: {status}")
                else:
                    logging.warning(f"[SingleCaseRunner] Case '{case_name}' returned no case_result")

                return {
                    "case_result": case_result,
                    "recorded_case": recorded_case,
                    "modified_case": modified_case,
                    "case_name": case_name
                }

        except Exception as e:
            logging.error(f"[SingleCaseRunner] Error executing case '{case_name}': {e}", exc_info=True)

            # Return error result
            return {
                "case_result": {
                    "case_name": case_name,
                    "final_summary": f"Case execution failed with error: {str(e)}",
                    "status": "failed",
                    "failure_type": "critical"
                },
                "recorded_case": None,
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

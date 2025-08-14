import asyncio
import json
import logging
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

from webqa_agent.actions.action_executor import ActionExecutor
from webqa_agent.actions.action_handler import ActionHandler
from webqa_agent.browser.check import ConsoleCheck, NetworkCheck
from webqa_agent.browser.session import BrowserSession
from webqa_agent.crawler.deep_crawler import DeepCrawler
from webqa_agent.llm.llm_api import LLMAPI
from webqa_agent.llm.prompt import LLMPrompt


class UITester:

    def __init__(self, llm_config: Dict[str, Any], browser_session: BrowserSession = None):
        self.llm_config = llm_config
        self.browser_session = browser_session
        self.page = None
        self.network_check = None
        self.console_check = None

        # Create component instances
        self._actions = ActionHandler()
        self._action_executor = ActionExecutor(self._actions)
        self.llm = LLMAPI(llm_config)

        # Execution status
        self.is_initialized = False
        self.test_results = []

        self.driver = None

        # Data storage related properties
        self.current_test_name: Optional[str] = None
        self.current_case_data: Optional[Dict[str, Any]] = None
        self.current_case_steps: List[Dict[str, Any]] = []
        self.all_cases_data: List[Dict[str, Any]] = []  # Store complete data for all cases
        self.step_counter: int = 0  # Used to generate step ID

    async def initialize(self, browser_session: BrowserSession = None):
        if browser_session:
            self.browser_session = browser_session

        if not self.browser_session:
            raise ValueError("Browser session is required")

        self.page = self.browser_session.get_page()
        self.driver = self.browser_session.driver

        await self._actions.initialize(page=self.page, driver=self.browser_session.driver)
        await self._action_executor.initialize()
        await self.llm.initialize()

        self.is_initialized = True
        return self

    async def start_session(self, url: str):
        if not self.is_initialized:
            raise RuntimeError("ParallelUITester not initialized")

        # # Simplify URL validation
        # if not url.startswith(("http://", "https://", "file://")):
        #     url = f"https://{url}"

        # Page navigation
        # await self._actions.go_to_page(self.page, url, cookies=cookies)
        await asyncio.sleep(2)  # Wait for page to load

        self.network_check = NetworkCheck(self.page)
        self.console_check = ConsoleCheck(self.page)

    async def action(self, test_step: str, file_path: str = None) -> Tuple[Dict[str, Any], Dict[str, Any]]:
        """Execute AI-driven test instructions and return (step_dict, summary_dict)

        Args:
            test_step: Test step description
            file_path: File path (for upload operations)

        Returns:
            Tuple (step_dict, summary_dict)
        """
        if not self.is_initialized:
            raise RuntimeError("ParallelUITester not initialized")

        start_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        try:
            logging.debug(f"Executing AI instruction: {test_step}")

            # Crawl current page state
            dp = DeepCrawler(self.page)
            _, id_map = await dp.crawl(highlight=True, viewport_only=True)
            await self._actions.update_element_buffer(id_map)
            logging.debug(f"action id_map: {id_map}")

            # Take screenshot
            marker_screenshot = await self._actions.b64_page_screenshot(file_name="marker")

            # Remove marker
            await dp.remove_marker()

            # Prepare LLM input
            user_prompt = self._prepare_prompt_action(test_step, id_map, LLMPrompt.planner_output_prompt)

            # Generate plan
            plan_json = await self._generate_plan(LLMPrompt.planner_system_prompt, user_prompt, marker_screenshot)

            logging.debug(f"Generated plan: {plan_json}")

            # Execute plan
            execution_steps, execution_result = await self._execute_plan(test_step, plan_json, file_path)

            end_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

            # Aggregate screenshots: first is page marker screenshot, rest are screenshots after each action
            screenshots_list = [{"type": "base64", "data": marker_screenshot}] + [
                {"type": "base64", "data": step.get("screenshot")} for step in execution_steps if step.get("screenshot")
            ]

            # Build structure for case step format
            status_str = "passed" if execution_result.get("success") else "failed"
            execution_steps_dict = {
                # id and number will be filled by outer process (e.g. LangGraph node)
                "description": f"action: {test_step}",
                "actions": execution_steps,  # All actions aggregated together
                "screenshots": screenshots_list,  # All screenshots aggregated together
                "modelIO": json.dumps(plan_json, indent=2, ensure_ascii=False) if isinstance(plan_json, dict) else "",
                "status": status_str,
                "start_time": start_time,
                "end_time": end_time,
            }

            # Automatically store step data
            self.add_step_data(execution_steps_dict, step_type="action")

            return execution_steps_dict, execution_result

        except Exception as e:
            error_msg = f"AI instruction failed: {str(e)}"
            logging.error(error_msg)

            end_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

            # Safely get possibly undefined variables
            safe_marker_screenshot = locals().get("marker_screenshot")
            safe_plan_json = locals().get("plan_json", {})

            # Build error case execution step dictionary structure
            error_screenshots = [{"type": "base64", "data": safe_marker_screenshot}] if safe_marker_screenshot else []

            error_execution_steps = {
                "description": f"action: {test_step}",
                "actions": [],
                "screenshots": error_screenshots,
                "modelIO": "",  # No valid model interaction output
                "status": "failed",
                "error": str(e),
                "start_time": start_time,
                "end_time": end_time,
            }

            # Automatically store error step data
            self.add_step_data(error_execution_steps, step_type="action")

            return error_execution_steps, {"success": False, "message": f"An exception occurred in action: {str(e)}"}

    async def verify(self, assertion: str) -> tuple[Dict[str, Any], Dict[str, Any]]:
        """Execute AI-driven assertion verification.

        Args:
            assertion: Assertion description

        Returns:
            Tuple (step_dict, model_output)
        """
        if not self.is_initialized:
            raise RuntimeError("ParallelUITester not initialized")

        start_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        try:
            logging.debug(f"Executing AI assertion: {assertion}")

            # Crawl current page
            dp = DeepCrawler(self.page)
            _, id_map = await dp.crawl(highlight=True, highlight_text=True, viewport_only=True)

            marker_screenshot = await self._actions.b64_page_screenshot(file_name="marker")
            await dp.remove_marker()

            screenshot = await self._actions.b64_page_screenshot(file_name="assert")

            # Get page structure
            await dp.crawl(highlight=False, highlight_text=True, viewport_only=True)
            page_structure = dp.get_text()

            # Prepare LLM input
            user_prompt = self._prepare_prompt_verify(
                f"assertion: {assertion}", LLMPrompt.verification_prompt, page_structure
            )

            result = await self.llm.get_llm_response(
                LLMPrompt.verification_system_prompt, user_prompt, images=[marker_screenshot, screenshot]
            )

            # Process result
            if isinstance(result, str):
                try:
                    model_output = json.loads(result)
                except json.JSONDecodeError:
                    model_output = {
                        "Validation Result": "Validation Failed",
                        "Details": f"LLM returned invalid JSON: {result}",
                    }
            elif isinstance(result, dict):
                model_output = result
            else:
                model_output = {
                    "Validation Result": "Validation Failed",
                    "Details": f"LLM returned unexpected type: {type(result)}",
                }

            # Determine status
            is_passed = model_output.get("Validation Result") == "Validation Passed"

            end_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

            # Build verification result
            status_str = "passed" if is_passed else "failed"
            verify_action_list = [{
                "description": "Verify",
                "success": is_passed,
                "index": 1,
            }]
            verification_step = {
                "description": f"verify: {assertion}",
                "actions": verify_action_list,  # Assertion steps usually don't contain actions
                "screenshots": [{"type": "base64", "data": marker_screenshot}, {"type": "base64", "data": screenshot}],
                "modelIO": result if isinstance(result, str) else json.dumps(result, ensure_ascii=False),
                "status": status_str,
                "start_time": start_time,
                "end_time": end_time,
            }

            # Automatically store assertion step data
            self.add_step_data(verification_step, step_type="assertion")

            return verification_step, model_output

        except Exception as e:
            error_msg = f"AI assertion failed: {str(e)}"
            logging.error(error_msg)

            # Try to get basic page information even if it fails
            try:
                basic_screenshot = await self._actions.b64_page_screenshot(file_name="error_assert")
            except:
                basic_screenshot = None

            end_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

            error_step = {
                "description": f"verify: {assertion}",
                "actions": [],
                "screenshots": [{"type": "base64", "data": basic_screenshot}] if basic_screenshot else [],
                "modelIO": "",
                "status": "failed",
                "error": str(e),
                "start_time": start_time,
                "end_time": end_time,
            }

            # Error assertion step data
            self.add_step_data(error_step, step_type="assertion")

            # Return error_step and a failed model output
            return error_step, {"Validation Result": "Validation Failed", "Details": error_msg}

    def _prepare_prompt_action(self, test_step: str, browser_elements: str, prompt_template: str) -> str:
        """Prepare LLM prompt."""
        return (
            f"test step: {test_step}\n"
            f"====================\n"
            f"pageDescription (interactive elements): {browser_elements}\n"
            f"====================\n"
            f"{prompt_template}"
        )

    def _prepare_prompt_verify(self, test_step: str, prompt_template: str, page_structure: str) -> str:
        """Prepare LLM prompt."""
        return (
            f"test step: {test_step}\n"
            f"====================\n"
            f"page_structure (full text content): {page_structure}\n"
            f"====================\n"
            f"{prompt_template}"
        )

    async def _generate_plan(self, system_prompt: str, prompt: str, browser_screenshot: str) -> Dict[str, Any]:
        """Generate test plan."""
        max_retries = 2

        for attempt in range(max_retries):
            try:
                # Get LLM response
                test_plan = await self.llm.get_llm_response(system_prompt, prompt, images=browser_screenshot)

                # Process API error
                if isinstance(test_plan, dict) and "error" in test_plan:
                    raise ValueError(f"LLM API error: {test_plan['error']}")

                # Verify response
                if not test_plan or not (isinstance(test_plan, str) and test_plan.strip()):
                    raise ValueError(f"Empty response from LLM: {test_plan}")

                try:
                    plan_json = json.loads(test_plan)
                except json.JSONDecodeError as je:
                    raise ValueError(f"Invalid JSON response: {str(je)}")

                if not plan_json.get("actions"):
                    raise ValueError("No valid actions found in plan")

                return plan_json

            except (ValueError, json.JSONDecodeError) as e:
                if attempt == max_retries - 1:
                    raise ValueError(f"Failed to generate valid plan after {max_retries} attempts: {str(e)}")

                logging.warning(f"Plan generation attempt {attempt + 1} failed: {str(e)}, retrying...")
                await asyncio.sleep(1)

    async def _execute_plan(self, user_case: str, plan_json: Dict[str, Any], file_path: str = None) -> Dict[str, Any]:
        """Execute test plan."""
        execute_results = []
        action_count = len(plan_json.get("actions", []))

        for index, action in enumerate(plan_json.get("actions", []), 1):
            action_desc = f"{action.get('type', 'Unknown')}"
            logging.debug(f"Executing step {index}/{action_count}: {action_desc}")

            try:
                # Execute action
                if action.get("type") == "Upload" and file_path:
                    execution_result = await self._action_executor._execute_upload(action, file_path)
                else:
                    execution_result = await self._action_executor.execute(action)

                # Process execution result
                if isinstance(execution_result, dict):
                    success = execution_result.get("success", False)
                    message = execution_result.get("message", "No message provided")
                else:
                    success = bool(execution_result)
                    message = "Legacy boolean result"

                # Wait for page to stabilize
                try:
                    await self.page.wait_for_load_state("networkidle", timeout=10000)
                    await asyncio.sleep(1.5)
                except Exception as e:
                    logging.warning(f"Page did not become network idle: {e}")
                    await asyncio.sleep(1)

                # Take screenshot
                post_action_ss = await self._actions.b64_page_screenshot(file_name=f"action_{action_desc}_{index}")

                action_result = {
                    "description": action_desc,
                    "success": success,
                    "message": message,
                    "screenshot": post_action_ss,
                    "index": index,
                }

                execute_results.append(action_result)

                if not success:
                    logging.error(f"Action {index} failed: {message}")
                    return execute_results, action_result

            except Exception as e:
                error_msg = f"Action {index} failed with error: {str(e)}"
                logging.error(error_msg)
                failure_result = {"success": False, "message": f"Exception occurred: {str(e)}", "screenshot": None}
                return execute_results, failure_result

        logging.debug("All actions executed successfully")
        post_action_ss = await self._actions.b64_page_screenshot(file_name="final_success")
        return execute_results, {
            "success": True,
            "message": "All actions executed successfully",
            "screenshot": post_action_ss,
        }

    def get_monitoring_results(self) -> Dict[str, Any]:
        """Get monitoring results."""
        results = {}

        if self.network_check:
            results["network"] = self.network_check.get_messages()

        if self.console_check:
            results["console"] = self.console_check.get_messages()

        return results

    async def end_session(self):
        """End session: close monitoring, recycle resources.

        This method **must not** propagate exceptions. Any errors during gathering
        monitoring data or listener cleanup are logged, and an (possibly empty)
        results dict is always returned so that callers don't need to wrap it in
        their own try/except blocks.
        """
        import sys

        results: dict = {}

        try:
            results = self.get_monitoring_results() or {}
        except BaseException as e:
            logging.warning(
                f"ParallelUITester end_session monitoring warning: {e!r} (type: {type(e)})"
            )

        for listener_name in ("console_check", "network_check"):
            listener = getattr(self, listener_name, None)
            if listener:
                try:
                    listener.remove_listeners()
                except BaseException as e:
                    logging.warning(
                        f"ParallelUITester end_session cleanup warning while removing {listener_name}: {e!r} (type: {type(e)})"
                    )

        return results

    async def cleanup(self):
        """Lightweight wrapper so external callers can always call
        cleanup()."""
        try:
            await self.end_session()
        except Exception as e:
            logging.warning(f"UITester.cleanup encountered an error: {e}")

    def set_current_test_name(self, name: str):
        """Set the current test case name (stub for compatibility with
        LangGraph workflow)."""
        self.current_test_name = name

    def start_case(self, case_name: str, case_data: Optional[Dict[str, Any]] = None):
        """Start a new test case."""
        # Set current_test_name to ensure compatibility
        self.current_test_name = case_name

        # If there is existing case data, finish it first
        if self.current_case_data:
            logging.warning(
                f"Starting new case '{case_name}' while previous case '{self.current_case_data.get('name')}' is still active. Finishing previous case."
            )
            self.finish_case("interrupted", "Case was interrupted by new case start")

        self.current_case_data = {
            "name": case_name,
            "start_time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "case_info": case_data or {},
            "steps": [],
            "status": "running",
            # "messages": {
            #     "console": [],
            #     "network": {
            #         "failed_requests": [],
            #         "responses": []
            #     }
            # },
            "report": [],
        }
        self.current_case_steps = []
        self.step_counter = 0  # Reset step counter
        logging.debug(f"Started tracking case: {case_name} (step counter reset)")

    def add_step_data(self, step_data: Dict[str, Any], step_type: str = "action"):
        """Add step data to current case."""
        if not self.current_case_data:
            logging.warning("No active case to add step data to")
            return

        self.step_counter += 1

        # Process actions data, remove screenshots
        original_actions = step_data.get("actions", [])
        cleaned_actions = []

        for action in original_actions:
            # Copy action data, but remove screenshot field
            cleaned_action = {}
            for key, value in action.items():
                if key != "screenshot":  # Remove screenshot field
                    cleaned_action[key] = value
            cleaned_actions.append(cleaned_action)

        # Convert to runner format step structure
        formatted_step = {
            "id": self.step_counter,
            "number": self.step_counter,
            "description": step_data.get("description", ""),
            "screenshots": step_data.get("screenshots", []),
            "modelIO": (
                step_data.get("modelIO", "")
                if isinstance(step_data.get("modelIO", ""), str)
                else json.dumps(step_data.get("modelIO", ""), ensure_ascii=False)
            ),
            "actions": cleaned_actions,  # Use cleaned actions
            "status": step_data.get("status", "passed"),
            "end_time": step_data.get("end_time", datetime.now().strftime("%Y-%m-%d %H:%M:%S")),
        }

        # If there is error information, add to step
        if "error" in step_data:
            formatted_step["error"] = step_data["error"]

        self.current_case_steps.append(formatted_step)
        self.current_case_data["steps"].append(formatted_step)
        logging.debug(f"Added step {formatted_step['id']} to case {self.current_test_name}")

    def finish_case(self, final_status: str = "completed", final_summary: Optional[str] = None):
        """Finish current case and save data."""
        if not self.current_case_data:
            logging.warning("No active case to finish")
            return

        case_name = self.current_case_data.get("name", "Unknown")
        steps_count = len(self.current_case_steps)

        # Get monitoring data
        # monitoring_data = self.get_monitoring_results()

        self.current_case_data.update(
            {
                "end_time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "status": final_status,
                "final_summary": final_summary or "",
                "total_steps": steps_count,
            }
        )

        # # Update monitoring data
        # if monitoring_data:
        #     if "network" in monitoring_data:
        #         self.current_case_data["messages"]["network"] = monitoring_data["network"]
        #         logging.debug(f"Added network monitoring data for case '{case_name}'")
        #     if "console" in monitoring_data:
        #         self.current_case_data["messages"]["console"] = monitoring_data["console"]
        #         logging.debug(f"Added console monitoring data for case '{case_name}'")

        # Verify steps data
        stored_steps = self.current_case_data.get("steps", [])
        if len(stored_steps) != steps_count:
            logging.error(
                f"Steps count mismatch for case '{case_name}': stored={len(stored_steps)}, tracked={steps_count}"
            )

        # Save to all cases data
        self.all_cases_data.append(self.current_case_data.copy())
        logging.debug(
            f"Finished case: '{case_name}' with status: {final_status}, {steps_count} steps, total cases: {len(self.all_cases_data)}"
        )

        # Clean up current case data
        self.current_case_data = None
        self.current_case_steps = []
        self.step_counter = 0

    def get_current_case_steps(self) -> List[Dict[str, Any]]:
        """Get all steps data for current case."""
        return self.current_case_steps.copy()

    def get_all_cases_data(self) -> List[Dict[str, Any]]:
        """Get all cases data."""
        return self.all_cases_data.copy()

    def get_case_summary(self) -> Dict[str, Any]:
        """Get summary information for test execution."""
        total_cases = len(self.all_cases_data)
        passed_cases = sum(1 for case in self.all_cases_data if case.get("status") == "passed")
        failed_cases = sum(1 for case in self.all_cases_data if case.get("status") == "failed")
        total_steps = sum(case.get("total_steps", 0) for case in self.all_cases_data)

        return {
            "total_cases": total_cases,
            "passed_cases": passed_cases,
            "failed_cases": failed_cases,
            "total_steps": total_steps,
            "success_rate": passed_cases / total_cases if total_cases > 0 else 0,
            "all_cases_data": self.all_cases_data,
        }

    def generate_runner_format_report(self, test_id: str = None, test_name: str = None) -> Dict[str, Any]:
        """Generate a complete test report in runner format."""
        import uuid
        from datetime import datetime

        if not self.all_cases_data:
            logging.warning("No case data available for report generation")
            return {}

        total_steps = 0
        for i, case in enumerate(self.all_cases_data):
            case_steps = case.get("steps", [])
            case_name = case.get("name", f"Case_{i}")
            total_steps += len(case_steps)
            logging.debug(
                f"Report validation - Case '{case_name}': {len(case_steps)} steps, status: {case.get('status', 'unknown')}"
            )

        logging.debug(f"Report generation - Total cases: {len(self.all_cases_data)}, Total steps: {total_steps}")

        # Calculate overall test time
        start_times = [case.get("start_time") for case in self.all_cases_data if case.get("start_time")]
        end_times = [case.get("end_time") for case in self.all_cases_data if case.get("end_time")]

        overall_start = min(start_times) if start_times else datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        overall_end = max(end_times) if end_times else datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        try:
            start_dt = datetime.strptime(overall_start, "%Y-%m-%d %H:%M:%S")
            end_dt = datetime.strptime(overall_end, "%Y-%m-%d %H:%M:%S")
            duration = (end_dt - start_dt).total_seconds()
        except:
            duration = 0.0

        # Determine overall status
        overall_status = "completed"
        if any(case.get("status") == "failed" for case in self.all_cases_data):
            overall_status = "failed"

        summary = self.get_case_summary()

        runner_format = {
            "test_id": test_id or str(uuid.uuid4()),
            "test_type": "UI_Agent",
            "test_name": test_name or "UI Agent Test Suite",
            "category": "function",
            "status": overall_status,
            "start_time": overall_start,
            "end_time": overall_end,
            "duration": duration,
            "results": {
                "total_cases": summary["total_cases"],
                "passed_cases": summary["passed_cases"],
                "failed_cases": summary["failed_cases"],
                "total_steps": summary["total_steps"],
                "success_rate": summary["success_rate"],
            },
            "sub_tests": self.all_cases_data,  # Here contains all formatted case data
            "logs": [],  # Can add logs if needed
            "traces": [],  # Can add traces if needed
            "error_message": "",
            "error_details": {},
            "metrics": {},
        }

        return runner_format

    async def get_current_page(self):
        try:
            if self.driver:
                return await self.driver.get_new_page()
        except Exception as e:
            logging.warning(f"UITester.get_current_page failed to detect new page: {e}")
        return self.driver.get_page()

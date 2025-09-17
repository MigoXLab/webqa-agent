"""This module defines the `execute_ui_action` tool for the LangGraph-based UI
testing application.

This tool allows the agent to interact with the web page.
"""

import datetime
import json
import logging
from typing import Any, Dict, Optional

from langchain_core.tools import BaseTool
from pydantic import Field

from webqa_agent.crawler.deep_crawler import DeepCrawler
from webqa_agent.testers.case_gen.prompts.tool_prompts import get_error_detection_prompt
from webqa_agent.testers.function_tester import UITester


class UITool(BaseTool):
    """A tool to interact with a UI via a UITester instance."""

    name: str = "execute_ui_action"
    description: str = "Executes a UI action using the UITester and returns a structured summary of the new page state."
    ui_tester_instance: UITester = Field(...)

    async def get_full_page_context(
        self, include_screenshot: bool = False, viewport_only: bool = True
    ) -> tuple[str, str | None]:
        """Helper to get a token-efficient summary of the page structure.

        Args:
            include_screenshot: 是否包含截图
            viewport_only: 是否只获取视窗内容，默认True（用于错误检测场景）
        """
        logging.debug(f"Retrieving page context for analysis (viewport_only={viewport_only})")
        page = self.ui_tester_instance.driver.get_page()
        dp = DeepCrawler(page)
        await dp.crawl(highlight=True, highlight_text=True, viewport_only=viewport_only)
        page_structure = dp.get_text()

        screenshot = None
        if include_screenshot:
            logging.debug("Capturing post-action screenshot")
            screenshot = await self.ui_tester_instance._actions.b64_page_screenshot(
                file_name="check_ui_error", save_to_log=False, full_page=not viewport_only
            )
            await dp.remove_marker()

        logging.debug(f"Page structure length: {len(page_structure)} characters")
        return page_structure, screenshot

    def _run(self, action: str, target: str, **kwargs) -> str:
        raise NotImplementedError("Use arun for asynchronous execution.")

    async def _arun(
        self, action: str, target: str, value: str = None, description: str = None, clear_before_type: bool = False
    ) -> str:
        """Executes a UI action using the UITester and returns a formatted
        summary of the result."""
        if not self.ui_tester_instance:
            error_msg = "UITester instance not provided for action execution"
            logging.error(error_msg)
            return f"[FAILURE] Error: {error_msg}"

        logging.debug(f"=== Executing UI Action: {action} ===")
        logging.debug(f"Target: {target}")
        logging.debug(f"Value: {value}")
        logging.debug(f"Description: {description}")
        logging.debug(f"Clear before type: {clear_before_type}")

        # Build the instruction for ui_tester.action()
        instruction_parts = []

        if description:
            instruction_parts.append(description)
            logging.debug(f"Using custom description: {description}")

        # Build the action phrase
        if action.lower() == "click":
            action_phrase = f"Click on the {target}"
        elif action.lower() == "type":
            if clear_before_type:
                action_phrase = f"Clear the {target} field and then type '{value}'"
                logging.debug("Using clear-before-type strategy")
            else:
                action_phrase = f"Type '{value}' in the {target}"
        elif action.lower() == "selectdropdown":
            action_phrase = f"From the {target}, select the option '{value}'"
        elif action.lower() == "scroll":
            action_phrase = f"Scroll {value or 'down'} on the page"
        elif action.lower() == "clear":
            action_phrase = f"Clear the content of {target}"
        else:
            action_phrase = f"{action} on {target}"
            if value:
                action_phrase += f" with value '{value}'"

        if not description:
            instruction_parts.append(action_phrase)
        else:
            instruction_parts.append(action_phrase)

        instruction = " - ".join(instruction_parts)
        logging.debug(f"Built instruction for UITester: {instruction}")

        try:
            logging.debug(f"Executing UI action: {instruction}")
            start_time = datetime.datetime.now()

            execution_steps, result = await self.ui_tester_instance.action(instruction)

            end_time = datetime.datetime.now()
            duration = (end_time - start_time).total_seconds()

            logging.debug(f"UI action completed in {duration:.2f} seconds")
            logging.debug(f"UI action result type: {type(result)}")

            # First, check for a hard failure from the action executor
            if not result.get("success"):
                error_message = (
                    f"Action '{action}' on '{target}' failed. Reason: {result.get('message', 'No details provided.')}"
                )
                if "available_options" in result:
                    options_str = ", ".join(result["available_options"])
                    error_message += f" Available options are: [{options_str}]."
                    logging.warning(f"Action failed with available options: {options_str}")
                else:
                    logging.warning(f"Action failed: {result.get('message', 'No details')}")
                return f"[FAILURE] {error_message}"

            logging.debug("Action execution successful, retrieving page context")
            page_structure, screenshot = await self.get_full_page_context(include_screenshot=True)

            if not isinstance(result, dict):
                error_msg = f"Action did not return a dictionary. Got: {type(result)}"
                logging.error(error_msg)
                return f"[FAILURE] Error: {error_msg}"

            # --- Success Response with Context ---
            logging.debug("Action completed successfully with no validation errors")
            success_response = f"[SUCCESS] Action '{action}' on '{target}' completed successfully."
            if description:
                success_response += f" ({description})"

            # Add contextual information about the current page state
            if result.get("message"):
                success_response += f" Status: {result['message']}"
                logging.debug(f"Action status message: {result['message']}")

            # Include DOM diff information for dynamic step generation
            dom_diff = result.get("dom_diff", {})
            if dom_diff:
                logging.debug(f"DOM diff detected with {len(dom_diff)} new/changed elements")
                success_response += f"\n\nDOM_DIFF_DETECTED: {json.dumps(dom_diff, ensure_ascii=False, separators=(',', ':'))}"

            # Include essential page structure information for next step planning
            context_preview = page_structure[:1500] + "..." if len(page_structure) > 1500 else page_structure
            success_response += f"\n\nCurrent Page State:\n{context_preview}"

            logging.debug("Returning success response with page context")
            return success_response

        except Exception as e:
            error_msg = f"Unexpected error during action execution: {str(e)}"
            logging.error(f"Exception in UI action execution: {error_msg}")
            logging.error(f"Exception type: {type(e).__name__}")
            return f"[FAILURE] {error_msg}"


class UIAssertTool(BaseTool):
    """A tool to perform UI assertions via a UITester instance."""

    name: str = "execute_ui_assertion"
    description: str = "Performs a UI assertion/validation using the UITester and returns the verification result."
    ui_tester_instance: UITester = Field(...)

    def _run(self, assertion: str) -> str:
        raise NotImplementedError("Use arun for asynchronous execution.")

    async def _arun(self, assertion: str) -> str:
        """Executes a UI assertion using the UITester and returns a formatted
        verification result."""
        if not self.ui_tester_instance:
            return "[FAILURE] Error: UITester instance not provided for assertion."

        logging.debug(f"Executing UI assertion: {assertion}")

        try:
            execution_steps, result = await self.ui_tester_instance.verify(assertion)

            if not isinstance(result, dict):
                return f"[FAILURE] Assertion error: Invalid response format from UITester.verify(). Expected dict, got {type(result)}"

            # Extract validation result from the response
            validation_result = result.get("Validation Result", "Unknown")
            details = result.get("Details", [])

            if validation_result == "Validation Passed":
                success_response = f"[SUCCESS] Assertion '{assertion}' PASSED."
                if details:
                    success_response += f" Verification Details: {'; '.join(details)}"
                return success_response

            elif validation_result == "Validation Failed":
                failure_response = f"[FAILURE] Assertion '{assertion}' FAILED."
                if details:
                    failure_response += f" Failure Details: {'; '.join(details)}"
                return failure_response

            else:
                return f"[FAILURE] Assertion '{assertion}' returned unexpected result: {validation_result}"

        except Exception as e:
            logging.error(f"Error executing UI assertion: {str(e)}")
            return f"[FAILURE] Unexpected error during assertion execution: {str(e)}"

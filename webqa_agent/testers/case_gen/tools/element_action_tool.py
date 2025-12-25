"""This module defines the `execute_ui_action` tool for the LangGraph-based UI
testing application.

This tool allows the agent to interact with the web page.
"""

import datetime
import json
import logging
from typing import Optional, Type

from langchain_core.tools import BaseTool
from pydantic import BaseModel, Field

from webqa_agent.actions.action_types import (
    ActionType,
    is_page_agnostic_action,
    get_action_default_phrase,
)
from webqa_agent.crawler.deep_crawler import DeepCrawler
from webqa_agent.testers.function_tester import UITester


class UIActionSchema(BaseModel):
    """Schema for UI action tool arguments."""

    action: str = Field(
        description=(
            "Type of UI action to perform. Supported actions: "
            "'Tap' - Click on an element; "
            "'Input' - Type text into an input field; "
            "'SelectDropdown' - Select an option from a dropdown menu (supports cascade selection with comma-separated paths); "
            "'Scroll' - Scroll the page with configurable modes ('once', 'untilBottom', 'untilTop') and optional distance; "
            "'Clear' - Clear the content of an input field; "
            "'Hover' - Hover over an element; "
            "'KeyboardPress' - Press a keyboard key; "
            "'Upload' - Upload a file; "
            "'Drag' - Drag an element to a target position; "
            "'GoToPage' - Navigate to a URL; "
            "'GoBack' - Navigate back to the previous page; "
            "'Sleep' - Wait for a specified duration; "
            "'Mouse' - Move mouse cursor or scroll mouse wheel."
        )
    )

    target: str = Field(
        description=(
            "Element identifier or selector to target. "
            "For most actions, this should be the element ID from the page description. "
            "For Scroll actions, this can be a scroll target description. "
            "For GoToPage action, this should be the URL."
        )
    )

    value: Optional[str] = Field(
        default=None,
        description=(
            "Value to use for the action. "
            "Required for 'Input' action (text to type), "
            "'SelectDropdown' action (option text or comma-separated cascade path like 'Category,Subcategory,Item'), "
            "'Scroll' action (direction 'up' or 'down', with optional scrollType and distance description), "
            "'KeyboardPress' action (key name like 'Enter', 'Tab', 'Escape', etc.), "
            "'Upload' action (file path), "
            "'Sleep' action (duration in milliseconds), "
            "'Mouse' action (operation specification in format 'move:x,y' for cursor positioning to coordinates (x,y) or 'wheel:deltaX,deltaY' for scrolling by delta values. Examples: 'move:100,200' moves cursor to (100,200), 'wheel:0,100' scrolls down by 100 pixels). "
            "Optional for 'Drag' action (target position description). "
            "Optional for other actions."
        )
    )

    description: Optional[str] = Field(
        default=None,
        description=(
            "Optional custom description of what this action is intended to do. "
            "Helps provide context for the action in test reports."
        )
    )

    clear_before_type: bool = Field(
        default=False,
        description=(
            "Whether to clear the input field before typing. "
            "Only applicable for 'Input' action. "
            "Set to True to clear existing content before typing new text."
        )
    )


class UITool(BaseTool):
    """A tool to interact with a UI via a UITester instance."""

    name: str = "execute_ui_action"
    description: str = "Executes a UI action using the UITester and returns a structured summary of the new page state."
    args_schema: Type[BaseModel] = UIActionSchema
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
        page = self.ui_tester_instance.browser_session.page
        dp = DeepCrawler(page)
        await dp.crawl(highlight=True, filter_text=True, viewport_only=viewport_only)
        page_structure = dp.get_text()

        screenshot = None
        if include_screenshot:
            logging.debug("Capturing post-action screenshot")
            screenshot = await self.ui_tester_instance._actions.b64_page_screenshot(
                full_page=not viewport_only,
                file_name="ui_error_check",
                context="error"
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
        if action == "Tap":
            action_phrase = f"Click on the {target}"
        elif action == "Input":
            if clear_before_type:
                action_phrase = f"Clear the {target} field and then type '{value}'"
                logging.debug("Using clear-before-type strategy")
            else:
                action_phrase = f"Type '{value}' in the {target}"
        elif action == "SelectDropdown":
            action_phrase = f"From the {target}, select the option '{value}'"
        elif action == "Scroll":
            action_phrase = f"Scroll to {target or 'the element'}"
        elif action == "Clear":
            action_phrase = f"Clear the content of {target}"
        elif action == "Hover":
            action_phrase = f"Hover over {target}"
        elif action == "KeyboardPress":
            action_phrase = f"Press the {value} key"
        elif action == "Upload":
            action_phrase = f"Upload file {value} to {target}"
        elif action == "Drag":
            action_phrase = f"Drag {target}"
            if value:
                action_phrase += f" to {value}"
        elif action == "GoToPage":
            action_phrase = f"Navigate to {target}"
        elif action == "GoBack":
            action_phrase = f"Navigate back to the previous page"
        elif action == "Sleep":
            action_phrase = f"Wait for {value or '1000'} milliseconds"
        elif action == "Mouse":
            if value and 'move:' in value.lower():
                # Extract coordinates from 'move:x,y' format
                action_phrase = f"Move mouse cursor to coordinates {value.split(':', 1)[1]} (specified as {target})"
            elif value and 'wheel:' in value.lower():
                # Extract delta values from 'wheel:deltaX,deltaY' format
                action_phrase = f"Scroll mouse wheel by {value.split(':', 1)[1]} (on {target})"
            else:
                action_phrase = f"Perform mouse action on {target} with value '{value}'"
        else:
            # Improved fallback logic to avoid malformed phrases like "action on "
            if target:
                action_phrase = f"{action} on {target}"
                if value:
                    action_phrase += f" with value '{value}'"
            else:
                # No target provided - just use action type
                action_phrase = action
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

            # Store execution context for verification (context-aware verification enhancement)
            self.ui_tester_instance.last_action_context = {
                "description": instruction,
                "action_type": action,
                "target": target,
                "value": value,
                "status": "success" if result.get("success") else "failed",
                "result": result,
                "dom_diff": result.get("dom_diff", {}),
                "timestamp": end_time.isoformat()
            }
            logging.debug("Stored action context for verification")

            # First, check for a hard failure from the action executor
            if not result.get("success"):
                # Check for unsupported page type (PDF, plugins, etc.) - CRITICAL ERROR
                if result.get("unsupported_page"):
                    page_type = result.get("page_type", "unknown")
                    error_message = f"""[CRITICAL_ERROR:UNSUPPORTED_PAGE] Operation navigated to unsupported page

**Page Type**: {page_type.upper()}
**Root Cause**: Operation navigated to {page_type} content which cannot be automated

**Impact**: Cannot execute subsequent actions, must abort current test case"""

                    logging.error(f"[CRITICAL] Detected unsupported page type: {page_type}")
                    return error_message

                # Check for enriched error details
                error_details = result.get("error_details", {})

                if error_details and error_details.get("error_type"):
                    # Format structured error message based on error type
                    error_type = error_details.get("error_type")
                    error_reason = error_details.get("error_reason", "Unknown reason")

                    if error_type == "scroll_failed":
                        error_message = f"""[FAILURE] Action '{action}' on '{target}' failed.

**Root Cause**: Element viewport positioning failed
**Details**: {error_reason}
**Strategies Attempted**: {', '.join(error_details.get('attempted_strategies', []))}

**Recovery Actions**:
1. Use Sleep action (2-3 seconds) to allow lazy-loaded content to appear
2. Try manual Scroll action to navigate the page closer to the element
3. Verify element ID is correct from current page state
4. Check if element is in a collapsed section that needs to be opened first"""

                    elif error_type == "scroll_timeout_lazy_loading":
                        error_message = f"""[FAILURE] Action '{action}' on '{target}' failed.

**Root Cause**: Page content unstable after scrolling (likely lazy-loading or infinite scroll)
**Details**: {error_reason}

**Recovery Actions**:
1. Use Sleep action with longer duration (3-5 seconds) to allow content to stabilize
2. Try the action again - content may have loaded by now
3. Use manual Scroll action to trigger additional content loading
4. Verify the element ID from the current page state in case it changed"""

                    elif error_type == "element_not_found":
                        error_message = f"""[FAILURE] Action '{action}' on '{target}' failed.

**Root Cause**: Element does not exist on current page
**Element ID**: {error_details.get('element_info', {}).get('element_id', target)}

**Recovery Actions**:
1. Review current page structure - element may have a different ID now
2. Check if navigation to the correct page is needed
3. Verify element is not hidden behind authentication or modal dialog
4. Use Sleep action if element loads dynamically after page interaction"""

                    elif error_type == "element_not_clickable":
                        error_message = f"""[FAILURE] Action '{action}' on '{target}' failed.

**Root Cause**: Element exists but cannot be clicked
**Details**: {error_reason}

**Recovery Actions**:
1. Check if element is obscured by modal/overlay - close it first using Tap action
2. Try Hover action over the element before clicking
3. Check if element is disabled - may need to enable it through other actions
4. Verify correct element ID - similar but different elements may exist"""

                    elif error_type == "element_not_typeable":
                        error_message = f"""[FAILURE] Action '{action}' on '{target}' failed.

**Root Cause**: Element cannot accept text input
**Details**: {error_reason}

**Recovery Actions**:
1. Verify the element is actually an input field or contenteditable element
2. Try Clear action first, then Input action
3. Check if element is disabled or read-only
4. Use Tap action to focus the element before typing"""

                    elif error_type == "file_upload_failed":
                        error_message = f"""[FAILURE] Action '{action}' on '{target}' failed.

**Root Cause**: File upload operation failed
**Details**: {error_reason}

**Recovery Actions**:
1. Verify the file path exists and is accessible
2. Check if the file format is accepted by the input element
3. Ensure the file size is within acceptable limits
4. Verify file input element is present and enabled on the page
5. Check file permissions and ensure the file is readable"""

                    elif error_type == "playwright_error":
                        error_message = f"""[FAILURE] Action '{action}' on '{target}' failed.

**Root Cause**: Browser interaction error
**Technical Details**: {error_details.get('playwright_error', 'Unknown error')}

**Recovery Actions**:
1. Retry the action after a short Sleep (1-2 seconds)
2. Check if page has navigated unexpectedly
3. Verify element still exists on current page
4. Check browser console for JavaScript errors that might interfere"""

                    else:
                        # Unknown error type, use generic format
                        error_message = f"""[FAILURE] Action '{action}' on '{target}' failed.

**Error Type**: {error_type}
**Details**: {error_reason}

**Recovery Actions**:
1. Review the error details carefully
2. Check current page state
3. Try alternative action strategies
4. Use Sleep action to allow page to stabilize"""

                    logging.warning(f"Action failed with structured error: {error_type}")
                    return error_message

                # Fallback: Use existing error handling for errors without enriched details
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


class UIAssertionSchema(BaseModel):
    """Schema for UI assertion tool arguments."""

    assertion: str = Field(
        description=(
            "The assertion or validation to perform on the current page state. "
            "Should be a clear, specific statement of what to verify. "
            "Examples: "
            "'The login button should be visible', "
            "'The error message should contain the text \"Invalid credentials\"', "
            "'The page title should be \"Dashboard\"', "
            "'There should be 5 items in the shopping cart'."
        )
    )

    focus_region: Optional[str] = Field(
        default=None,
        description=(
            "Optional page region to focus verification on. "
            "When specified, directs the LLM to pay primary attention to elements within this region. "
            "Use semantic region descriptions that match visual layout. "
            "Examples: "
            "'header navigation bar', "
            "'main content area', "
            "'sidebar widgets', "
            "'shopping cart summary', "
            "'login form section', "
            "'footer links'. "
            "If not specified, verification considers the entire visible page."
        )
    )


class UIAssertTool(BaseTool):
    """A tool to perform functional UI assertions via a UITester instance."""

    name: str = "execute_ui_assertion"
    description: str = (
        "Performs FUNCTIONAL verification: validates UI behaviors, element states, data accuracy, "
        "and business logic. Use for testing WHAT works (functionality). "
        "Examples: element presence, button enabled state, form submission success, navigation results, data values."
    )
    args_schema: Type[BaseModel] = UIAssertionSchema
    ui_tester_instance: UITester = Field(...)

    def _run(self, assertion: str) -> str:
        raise NotImplementedError("Use arun for asynchronous execution.")

    async def _arun(self, assertion: str, focus_region: Optional[str] = None) -> str:
        """Executes a UI assertion using the UITester and returns a formatted
        verification result.

        Args:
            assertion: The assertion statement to verify
            focus_region: Optional page region to focus verification on
        """
        if not self.ui_tester_instance:
            return "[FAILURE] Error: UITester instance not provided for assertion."

        logging.debug(f"Executing UI assertion: {assertion}")
        if focus_region:
            logging.debug(f"Focus region specified: {focus_region}")

        try:
            # Build execution context from instance state (context-aware verification)
            execution_context = None
            if self.ui_tester_instance.last_action_context:
                # Build complete execution context with all 5 expected fields
                execution_context = {
                    "last_action": self.ui_tester_instance.last_action_context,
                    "test_objective": self.ui_tester_instance.current_test_objective,
                    "success_criteria": self.ui_tester_instance.current_success_criteria,
                    "completed_steps": [
                        h for h in self.ui_tester_instance.execution_history
                        if h.get("success") is True  # Use strict comparison to avoid None misclassification
                    ],
                    "failed_steps": [
                        h for h in self.ui_tester_instance.execution_history
                        if h.get("success") is False  # Use strict comparison to avoid None misclassification
                    ]
                }
                logging.debug("Passing execution context to verify()")

            execution_steps, result = await self.ui_tester_instance.verify(
                assertion,
                execution_context,
                focus_region=focus_region
            )

            if not isinstance(result, dict):
                return f"[FAILURE] Assertion error: Invalid response format from UITester.verify(). Expected dict, got {type(result)}"

            # Extract validation result from the response
            validation_result = result.get("Validation Result", "Unknown")
            details = result.get("Details", [])
            failure_type = result.get("Failure Type")
            recommendation = result.get("Recommendation")

            if validation_result == "Validation Passed":
                success_response = f"[SUCCESS] Assertion '{assertion}' PASSED."
                if details:
                    success_response += f" Verification Details: {'; '.join(details)}"
                return success_response

            elif validation_result == "Cannot Verify":
                # Action execution failure - cannot perform verification
                cannot_verify_response = f"[CANNOT_VERIFY] Assertion '{assertion}' cannot be verified (prerequisite action failed)."
                if failure_type:
                    cannot_verify_response += f" Failure Type: {failure_type}."
                if details:
                    cannot_verify_response += f" Details: {'; '.join(details)}"
                if recommendation:
                    cannot_verify_response += f" Recommendation: {recommendation}"
                return cannot_verify_response

            elif validation_result == "Validation Failed":
                failure_response = f"[FAILURE] Assertion '{assertion}' FAILED."
                if failure_type:
                    failure_response += f" Failure Type: {failure_type}."
                if details:
                    failure_response += f" Failure Details: {'; '.join(details)}"
                if recommendation:
                    failure_response += f" Recommendation: {recommendation}"
                return failure_response

            else:
                return f"[FAILURE] Assertion '{assertion}' returned unexpected result: {validation_result}"

        except Exception as e:
            logging.error(f"Error executing UI assertion: {str(e)}")
            return f"[FAILURE] Unexpected error during assertion execution: {str(e)}"

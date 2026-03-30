"""This module defines the `execute_ui_assertion` tool for the LangGraph-based
UI testing application.

This tool allows the agent to perform functional UI assertions and
verification.
"""

import datetime
import logging
import time
from typing import Any, Optional, Type

from langchain_core.tools import BaseTool
from pydantic import BaseModel, Field

from webqa_agent.executor.gen.utils.case_recorder import CentralCaseRecorder
from webqa_agent.tools.core.ui_driver import UITester
from webqa_agent.utils.timing_breakdown import record_tool_timing


class UIAssertionSchema(BaseModel):
    """Schema for UI assertion tool arguments."""

    assertion: str = Field(
        description=(
            'The assertion or validation to perform on the current page state. '
            'Should be a clear, specific statement of what to verify. '
            'Examples: '
            "'The login button should be visible', "
            "'The error message should contain the text \"Invalid credentials\"', "
            "'The page title should be \"Dashboard\"', "
            "'There should be 5 items in the shopping cart'."
        )
    )

    focus_region: Optional[str] = Field(
        default=None,
        description=(
            'Optional page region to focus verification on. '
            'When specified, directs the LLM to pay primary attention to elements within this region. '
            'Use semantic region descriptions that match visual layout. '
            'Examples: '
            "'header navigation bar', "
            "'main content area', "
            "'sidebar widgets', "
            "'shopping cart summary', "
            "'login form section', "
            "'footer links'. "
            'If not specified, verification considers the entire visible page.'
        )
    )


class UIAssertTool(BaseTool):
    """A tool to perform functional UI assertions via a UITester instance."""

    name: str = 'execute_ui_assertion'
    description: str = (
        'Performs FUNCTIONAL verification: validates UI behaviors, element states, data accuracy, '
        'and business logic. Use for testing WHAT works (functionality). '
        'Examples: element presence, button enabled state, form submission success, navigation results, data values.'
    )
    args_schema: Type[BaseModel] = UIAssertionSchema
    ui_tester_instance: UITester = Field(...)
    case_recorder: Any | None = Field(default=None, description='Optional CentralCaseRecorder to record verify steps')

    def _run(self, assertion: str) -> str:
        raise NotImplementedError('Use arun for asynchronous execution.')

    async def _arun(self, assertion: str, focus_region: Optional[str] = None) -> str:
        """Executes a UI assertion using the UITester and returns a formatted
        verification result.

        Args:
            assertion: The assertion statement to verify
            focus_region: Optional page region to focus verification on
        """
        if not self.ui_tester_instance:
            return '[FAILURE] Error: UITester instance not provided for assertion.'
        tool_started = time.perf_counter()

        logging.debug(f'Executing UI assertion: {assertion}')
        if focus_region:
            logging.debug(f'Focus region specified: {focus_region}')

        try:
            # Build execution context from instance state (context-aware verification)
            execution_context = None
            if self.ui_tester_instance.last_action_context:
                # Build complete execution context with all 5 expected fields
                execution_context = {
                    'last_action': self.ui_tester_instance.last_action_context,
                    'test_objective': self.ui_tester_instance.current_test_objective,
                    'success_criteria': self.ui_tester_instance.current_success_criteria,
                    'completed_steps': [
                        h for h in self.ui_tester_instance.execution_history
                        if h.get('success') is True  # Use strict comparison to avoid None misclassification
                    ],
                    'failed_steps': [
                        h for h in self.ui_tester_instance.execution_history
                        if h.get('success') is False  # Use strict comparison to avoid None misclassification
                    ]
                }
                logging.debug('Passing execution context to verify()')

            execution_steps, result = await self.ui_tester_instance.verify(
                assertion,
                execution_context,
                focus_region=focus_region
            )
            end_time = datetime.datetime.now()

            # Record verify step to CentralCaseRecorder if available
            recorder: CentralCaseRecorder | None = self.case_recorder
            if recorder and execution_steps:
                # execution_steps is a dict with structure: {"actions": [...], "screenshots": [...], "status": "...", ...}
                # Extract screenshots and actions from the dict
                screenshots = execution_steps.get('screenshots', [])
                screenshots_paths = execution_steps.get('screenshots_paths', [])
                actions = execution_steps.get('actions', [])
                step_status = execution_steps.get('status', 'passed')
                model_io = execution_steps.get('modelIO', '')

                # Record the verify step
                recorder.add_step(
                    description=f'verify: {assertion}',
                    screenshots=screenshots,
                    screenshots_paths=screenshots_paths,
                    model_io=model_io,
                    actions=actions,
                    status=step_status,
                    step_type='verify',
                    timestamp=end_time.strftime('%Y-%m-%dT%H:%M:%S')  # ISO 8601 format
                )
                logging.debug(f'Recorded verify step to CentralCaseRecorder: {assertion[:60]}...')

            if not isinstance(result, dict):
                return f'[FAILURE] Assertion error: Invalid response format from UITester.verify(). Expected dict, got {type(result)}'

            # Extract validation result from the response
            validation_result = result.get('Validation Result', 'Unknown')
            details = result.get('Details', [])
            failure_type = result.get('Failure Type')
            recommendation = result.get('Recommendation')

            if validation_result == 'Validation Passed':
                success_response = f"[SUCCESS] Assertion '{assertion}' PASSED."
                if details:
                    success_response += f" Verification Details: {'; '.join(details)}"
                return success_response

            elif validation_result == 'Cannot Verify':
                # Action execution failure - cannot perform verification
                cannot_verify_response = f"[CANNOT_VERIFY] Assertion '{assertion}' cannot be verified (prerequisite action failed)."
                if failure_type:
                    cannot_verify_response += f' Failure Type: {failure_type}.'
                if details:
                    cannot_verify_response += f" Details: {'; '.join(details)}"
                if recommendation:
                    cannot_verify_response += f' Recommendation: {recommendation}'
                return cannot_verify_response

            elif validation_result == 'Validation Failed':
                failure_response = f"[FAILURE] Assertion '{assertion}' FAILED."
                if failure_type:
                    failure_response += f' Failure Type: {failure_type}.'
                if details:
                    failure_response += f" Failure Details: {'; '.join(details)}"
                if recommendation:
                    failure_response += f' Recommendation: {recommendation}'
                return failure_response

            else:
                return f"[FAILURE] Assertion '{assertion}' returned unexpected result: {validation_result}"

        except Exception as e:
            logging.error(f'Error executing UI assertion: {str(e)}')
            return f'[FAILURE] Unexpected error during assertion execution: {str(e)}'
        finally:
            elapsed = time.perf_counter() - tool_started
            record_tool_timing(self.name, elapsed)

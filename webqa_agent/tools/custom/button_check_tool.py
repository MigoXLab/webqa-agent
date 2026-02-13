"""Page button traversal testing tool for WebQA Agent.

This tool performs comprehensive clickable element testing by:
- Extracting all clickable elements from the current page
- Clicking each element and capturing screenshots
- Validating click results and tracking failures
- Generating detailed test reports

Key Features:
- Reuses PageButtonTest for consistency with existing test infrastructure
- Tracks click history and validates business success
- Records screenshots for each click action
- Returns comprehensive test results with pass/fail statistics

Usage in test plans:
    LLM autonomously chooses when to invoke this tool based on:
    - Test objectives mentioning comprehensive UI testing
    - Need to verify all clickable elements work correctly
    - Regression testing scenarios

Example test step:
    {"action": "traverse_clickable_elements", "params": {}}
"""
import logging
from datetime import datetime
from typing import Any, Dict, Type

from pydantic import BaseModel, Field

from webqa_agent.data.gen_structures import TestStatus
from webqa_agent.tools.base import WebQABaseTool, WebQAToolMetadata
from webqa_agent.tools.core.web_checks import PageButtonTest
from webqa_agent.tools.registry import register_tool

logger = logging.getLogger(__name__)


class ButtonCheckToolSchema(BaseModel):
    """Schema for button check tool arguments.

    LLM uses these Field descriptions to understand parameter usage.
    """

    pass  # No parameters needed - tests all clickable elements automatically


@register_tool  # Automatically registers to global registry on import
class ButtonCheckTool(WebQABaseTool):
    """Tool for comprehensive clickable element testing.

    This action-category tool traverses all clickable elements on a page,
    clicks each one, and validates the results. It provides comprehensive
    coverage for UI interaction testing.

    Architecture:
    - Category: 'custom' - Custom user-defined tool
    - Trigger: Explicit step_type for LLM planning prompt inclusion
    - Browser Access: Requires ui_tester_instance for page interaction
    - Test Implementation: Reuses PageButtonTest for consistency

    Performance:
    - Processes up to 50 clickable elements by default
    - Captures screenshots for each click
    - Brief pause between clicks for stability
    """

    name: str = 'traverse_clickable_elements'
    description: str = (
        'Performs comprehensive testing of all clickable elements on the page. '
        'Clicks each element, captures screenshots, and validates results.'
    )
    args_schema: Type[BaseModel] = ButtonCheckToolSchema

    # Requires browser access via ui_tester_instance
    ui_tester_instance: Any = Field(
        ...,
        description='UITester instance for accessing browser page and context'
    )

    # Requires case_recorder for step recording
    case_recorder: Any | None = Field(
        default=None,
        description='Optional CentralCaseRecorder to record test steps'
    )

    # Optional llm_config for report configuration
    llm_config: Dict = Field(
        default_factory=dict,
        description='LLM configuration including report settings'
    )

    @classmethod
    def get_metadata(cls) -> WebQAToolMetadata:
        """Return tool metadata for registration and prompt generation."""
        return WebQAToolMetadata(
            name='traverse_clickable_elements',
            category='custom',  # Custom tool - marks as user-defined
            step_type='traverse_clickable_elements',  # Explicit step type for planning
            description_short='Comprehensive testing of all clickable elements',
            description_long=(
                'Performs exhaustive testing of all clickable elements on the current page. '
                'For each element:\n'
                '  - Clicks the element and waits for response\n'
                '  - Captures screenshots after click\n'
                '  - Validates business success (no errors, navigation successful)\n'
                '  - Returns to original page for next test\n\n'
                'Features:\n'
                '  - Automatic element extraction using DOM analysis\n'
                '  - Screenshot capture for visual validation\n'
                '  - Business logic success validation\n'
                '  - Detailed pass/fail statistics\n\n'
                'Returns:\n'
                '  - Total elements tested\n'
                '  - Number of failures\n'
                '  - Detailed error information for failed elements'
            ),
            examples=[
                '{{"action": "traverse_clickable_elements", "params": {{}}}}',
            ],
            use_when=[
                # Comprehensive UI testing scenarios
                'Performing comprehensive UI regression testing',
                'Validating all interactive elements work correctly',
                'Testing navigation menu and dropdown functionality',
                'Verifying form submission buttons and links',
                'During smoke testing to catch broken UI interactions',

                # Specific testing needs
                'After major UI refactoring to ensure nothing broke',
                'Testing single-page applications (SPAs) with dynamic routing',
                'Validating e-commerce product pages with multiple CTAs',
                'Testing dashboard interfaces with many interactive widgets',
                'During accessibility audits to verify all clickable elements function',

                # Quality assurance workflows
                'As part of automated test suite for continuous integration',
                'Before major releases to catch last-minute UI issues',
                'When manual testing is too time-consuming due to many elements',
            ],
            dont_use_when=[
                # Performance and safety considerations
                'On pages with hundreds of clickable elements (use sampling instead)',
                'During performance testing (adds significant overhead)',
                'Too frequently (execution time: 10-30 seconds depending on element count)',
                'On every page navigation (use once per page for regression testing)',
                'On production environments without proper sandboxing',
                'When testing destructive actions (delete, payment submission)',

                # Inappropriate scenarios
                'After every single navigation (too frequent, use targeted testing)',
                'On pages with infinite scroll or dynamically loaded elements',
                'When only specific elements need testing (use targeted click instead)',
                'On login/authentication forms (may trigger rate limiting)',
            ],
            priority=35,  # Lower than link detection (45) but higher than experimental tools
            dependencies=[]  # No external dependencies, uses built-in modules
        )

    @classmethod
    def get_required_params(cls) -> Dict[str, str]:
        """Specify required initialization parameters.

        This tool requires:
        - ui_tester_instance: For browser access
        - case_recorder: For recording test steps to test report
        - llm_config: For report configuration
        """
        return {
            'ui_tester_instance': 'ui_tester_instance',
            'case_recorder': 'case_recorder',
            'llm_config': 'llm_config',
        }

    def _build_failure_info(self, step: Any, error_details: Dict[str, Any]) -> str:
        """Build detailed failure information string for a failed test step.

        Args:
            step: Failed test step with description and ID
            error_details: Error details from ActionHandler context

        Returns:
            Formatted failure information string
        """
        error_type = error_details.get('error_type', 'unknown')
        error_reason = error_details.get('error_reason', getattr(step, 'errors', 'Unknown error'))

        failure_info = f'  - {step.description} (ID: {step.id}): {error_type}'

        if error_reason:
            failure_info += f' - {error_reason}'

        # Add attempted strategies if available
        attempted = error_details.get('attempted_strategies', [])
        if attempted:
            failure_info += f"\n    Attempted: {', '.join(attempted)}"

        # Add scroll info if relevant
        scroll_attempts = error_details.get('scroll_attempts', 0)
        if scroll_attempts > 0:
            max_attempts = error_details.get('max_scroll_attempts', 0)
            failure_info += f' (scroll: {scroll_attempts}/{max_attempts} attempts)'

        return failure_info

    async def _arun(self) -> str:
        """Execute comprehensive button testing.

        Workflow:
        1. Get current page and URL
        2. Extract all clickable elements
        3. Run PageButtonTest on extracted elements
        4. Analyze results and format response
        5. Update context with test results

        Returns:
            Formatted response with test results and statistics
        """
        try:
            # Step 1: Get current page
            page = await self.ui_tester_instance.get_current_page()
            if not page:
                return self.format_critical_error(
                    'PAGE_CRASHED',
                    'Cannot get current page for button traversal testing'
                )

            url = page.url
            logger.info(f'Button Test Tool: Starting traversal test on {url}')

            # Step 2: Extract clickable elements using DeepCrawler
            from webqa_agent.crawler.deep_crawler import DeepCrawler

            # Use DeepCrawler to extract all interactive elements
            dp = DeepCrawler(page)
            crawl_result = await dp.crawl(highlight=False, viewport_only=False)

            # Get clickable elements as dictionary (format expected by PageButtonTest)
            clickable_elements = crawl_result.raw_dict()

            if not clickable_elements:
                # No clickable elements found - record as success (using safe_record_step helper)
                self.safe_record_step(
                    description='Traverse clickable elements (no elements found)',
                    model_io_data={'message': 'No clickable elements found on page'},
                    status='passed',
                )

                return self.format_success(
                    'No clickable elements found on page',
                    page_state=f'URL: {url}'
                )

            logger.info(f'Button Test Tool: Found {len(clickable_elements)} clickable elements')

            # Step 3: Run PageButtonTest
            report_config = self.llm_config.get('report_config', {'language': 'en-US'})
            button_test = PageButtonTest(report_config=report_config)

            result = await button_test.run(
                url=url,
                page=page,
                clickable_elements=clickable_elements
            )

            # Step 4: Analyze results
            total_elements = len(clickable_elements)
            failed_count = sum(
                1 for step in result.steps
                if step.status == TestStatus.FAILED
            )
            passed_count = total_elements - failed_count

            logger.info(
                f'Button Test Tool: Completed. '
                f'Total: {total_elements}, Passed: {passed_count}, Failed: {failed_count}'
            )

            # Step 5: Update context for downstream tools
            self.update_action_context(
                self.ui_tester_instance,
                {
                    'description': f'Traverse clickable elements (tested {total_elements})',
                    'action_type': 'ButtonTraversal',
                    'status': 'success' if result.status == TestStatus.PASSED else 'failed',
                    'result': {
                        'message': (
                            f'Tested {total_elements} clickable elements: '
                            f'{passed_count} passed, {failed_count} failed'
                        ),
                        'total_elements': total_elements,
                        'passed_count': passed_count,
                        'failed_count': failed_count,
                        'test_status': result.status.value,
                    },
                    'timestamp': datetime.now().isoformat(),
                }
            )

            # Step 6: Record to case_recorder (using safe_record_step helper)
            # Extract failure details for logging
            failures = [
                {
                    'element_id': step.id,
                    'description': step.description,
                    'error': step.errors if hasattr(step, 'errors') and step.errors else 'Unknown error'
                }
                for step in result.steps
                if step.status == TestStatus.FAILED
            ]

            self.safe_record_step(
                description=f'Traverse clickable elements (tested {total_elements})',
                model_io_data={
                    'total_elements': total_elements,
                    'passed': passed_count,
                    'failed': failed_count,
                    'failures': failures[:10],  # Limit to first 10 failures
                },
                status='passed' if result.status == TestStatus.PASSED else 'failed',
            )

            # Step 7: Format response with detailed error context
            if result.status == TestStatus.PASSED:
                return self.format_success(
                    f'All {total_elements} clickable elements passed testing',
                    page_state=f'Tested buttons/links on {url}'
                )
            else:
                # Categorize failures by error type
                error_stats = {}
                detailed_failures = []

                for step in result.steps:
                    if step.status == TestStatus.FAILED:
                        # Extract error details from ActionHandler context
                        error_details = {}
                        if hasattr(step, 'error_details') and step.error_details:
                            error_details = step.error_details

                        error_type = error_details.get('error_type', 'unknown')

                        # Count by error type
                        error_stats[error_type] = error_stats.get(error_type, 0) + 1

                        # Build detailed failure info using helper
                        failure_info = self._build_failure_info(step, error_details)
                        detailed_failures.append(failure_info)

                # Build error summary by type
                error_summary_parts = []
                for error_type, count in sorted(error_stats.items(), key=lambda x: x[1], reverse=True):
                    error_summary_parts.append(f'  - {error_type}: {count} elements')
                error_summary = '\n'.join(error_summary_parts)

                # Show first 5 detailed failures
                failure_summary = '\n'.join(detailed_failures[:5])
                if failed_count > 5:
                    failure_summary += f'\n  ... and {failed_count - 5} more failures'

                # Build full message
                message = (
                    f'{failed_count} of {total_elements} elements failed:\n\n'
                    f'{failure_summary}\n\n'
                    f'Summary by failure type:\n{error_summary}'
                )

                # Generate targeted recovery hints based on error types
                recovery_hints = []
                if 'scroll_timeout' in error_stats or 'scroll_timeout_lazy_loading' in error_stats:
                    recovery_hints.append('For scroll timeouts: Increase wait time or check lazy-loading implementation')
                if 'element_not_found' in error_stats:
                    recovery_hints.append('For not found errors: Verify element selectors are correct and elements exist')
                if 'element_not_clickable' in error_stats:
                    recovery_hints.append('For not clickable errors: Check if elements are obscured by overlays or z-index issues')
                if 'element_obscured' in error_stats:
                    recovery_hints.append('For obscured elements: Check for modal dialogs, fixed headers, or overlapping elements')
                if 'playwright_error' in error_stats:
                    recovery_hints.append('For Playwright errors: Review page structure and Playwright locator strategies')

                # Add general hints if no specific ones
                if not recovery_hints:
                    recovery_hints = [
                        'Review failed elements for broken functionality',
                        'Check if elements require authentication or permissions',
                        'Verify browser session is still active'
                    ]

                return self.format_failure(message, recovery_hints=recovery_hints)

        except Exception as e:
            # Record failed step (using safe_record_step helper)
            self.safe_record_step(
                description='Traverse clickable elements (failed)',
                model_io_data={
                    'error': str(e),
                    'error_type': type(e).__name__
                },
                status='failed',
            )

            # Update context to indicate failure
            self.update_action_context(
                self.ui_tester_instance,
                {
                    'description': 'Traverse clickable elements (failed)',
                    'action_type': 'ButtonTraversal',
                    'status': 'failed',
                    'result': {
                        'message': f'Button traversal failed: {str(e)}',
                        'error_details': {
                            'error_type': type(e).__name__,
                        }
                    },
                    'timestamp': datetime.now().isoformat(),
                }
            )

            logger.error(f'Button Test Tool: Unexpected error: {e}', exc_info=True)
            return self.format_failure(
                f'Button traversal test failed: {str(e)}',
                recovery_hints=[
                    'Ensure the page has finished loading',
                    'Check if the page is accessible (not PDF/plugin)',
                    'Verify browser session is still active',
                    'Try testing specific elements individually instead'
                ]
            )

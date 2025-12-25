"""Example action-category custom tool for capturing screenshots.

This demonstrates how to create an action-category tool that:
1. Uses ui_tester_instance to access the browser
2. Updates last_action_context for assertion tools
3. Is part of the action execution chain

Unlike standalone tools (like api_tool.py), action-category tools:
- Require browser access via ui_tester_instance
- Must call update_action_context() after execution
- Can be used by subsequent assertion tools for context-aware verification
"""
import datetime
from typing import Any, Type

from pydantic import BaseModel, Field

from webqa_agent.testers.case_gen.tools.base import (WebQABaseTool,
                                                     WebQAToolMetadata)
from webqa_agent.testers.case_gen.tools.registry import register_tool


class ScreenshotSchema(BaseModel):
    """Schema for screenshot tool arguments."""

    filename: str = Field(
        default='screenshot',
        description="Screenshot filename without extension (e.g., 'login_page')"
    )
    full_page: bool = Field(
        default=False,
        description='Capture full scrollable page (True) or just viewport (False)'
    )
    description: str = Field(
        default='',
        description='Optional description of why this screenshot is being captured'
    )


@register_tool
class ScreenshotTool(WebQABaseTool):
    """Tool for capturing screenshots of the current page state.

    This is an action-category tool that demonstrates:
    - Accessing browser via ui_tester_instance
    - Updating last_action_context for assertion chain
    - Proper error handling with format helpers

    Design Note: This tool uses an explicit step_type to appear in LLM planning
    prompts. The LLM can choose to use this tool when generating test plans
    (e.g., for visual documentation, debugging). See api_tool.py for reference.
    """

    name: str = 'capture_screenshot'
    description: str = (
        'Captures a screenshot of the current page state. '
        'Useful for visual documentation, debugging, and evidence capture.'
    )
    args_schema: Type[BaseModel] = ScreenshotSchema

    # This field is required - the registry injects it during instantiation
    ui_tester_instance: Any = Field(
        default=None,
        description='UITester instance for browser access'
    )

    @classmethod
    def get_metadata(cls) -> WebQAToolMetadata:
        """Return tool metadata for registration."""
        return WebQAToolMetadata(
            name='capture_screenshot',
            category='custom',  # Custom tool - marks as user-defined
            step_type='capture_screenshot',  # Explicit step type for planning
            description_short='Captures a screenshot of the current page.',
            description_long=(
                'Captures a screenshot of the current browser viewport or full page. '
                'The screenshot is saved to the test results directory.\n'
                'Parameters:\n'
                '  - filename: Screenshot filename without extension\n'
                '  - full_page: True for full page, False for viewport only\n'
                '  - description: Optional description for logging'
            ),
            examples=[
                "capture_screenshot(filename='checkout_page', full_page=True)",
                "capture_screenshot(filename='error_state', description='Captured after form validation failed')"
            ],
            use_when=[
                'visual documentation',
                'debugging',
                'evidence capture',
                'state recording'
            ],
            dont_use_when=[
                'functional verification (use execute_ui_assertion)',
                'text content checking',
                'element interaction'
            ],
            priority=30,  # Lower priority than core tools
            dependencies=[]  # No direct imports; browser access via ui_tester_instance
        )

    @classmethod
    def get_required_params(cls) -> dict:
        """Specify that this tool requires ui_tester_instance."""
        return {'ui_tester_instance': 'ui_tester_instance'}

    async def _arun(
        self,
        filename: str = 'screenshot',
        full_page: bool = False,
        description: str = ''
    ) -> str:
        """Execute screenshot capture.

        Action-category tools MUST update the action context for assertion
        tools.
        """
        if not self.ui_tester_instance:
            return self.format_failure(
                'UITester instance not provided',
                recovery_hints=['Ensure tool is instantiated with ui_tester_instance']
            )

        try:
            # Access the browser page
            page = self.ui_tester_instance.browser_session.page

            # Generate unique filename with timestamp
            timestamp = datetime.datetime.now().strftime('%Y%m%d_%H%M%S')
            full_filename = f'{filename}_{timestamp}.png'

            # Capture screenshot
            screenshot_bytes = await page.screenshot(full_page=full_page)

            # Get current URL for context
            current_url = page.url

            # Action-category tools MUST update context for assertion chain
            self.update_action_context(
                self.ui_tester_instance,
                {
                    'description': f'Captured screenshot: {full_filename}',
                    'action_type': 'Screenshot',
                    'target': current_url,
                    'value': f'full_page={full_page}',
                    'status': 'success',
                    'timestamp': datetime.datetime.now().isoformat(),
                    # Additional context for assertions
                    'screenshot_size': len(screenshot_bytes),
                    'screenshot_filename': full_filename,
                }
            )

            # Return success with context
            return self.format_success(
                f'Screenshot captured: {full_filename}',
                page_state=(
                    f'Screenshot saved ({len(screenshot_bytes)} bytes). '
                    f'Current URL: {current_url}'
                )
            )

        except AttributeError as e:
            return self.format_critical_error(
                'SESSION_EXPIRED',
                f'Browser session not available: {str(e)}'
            )
        except Exception as e:
            return self.format_failure(
                f'Screenshot capture failed: {str(e)}',
                recovery_hints=[
                    'Check if the page is fully loaded',
                    'Verify browser session is active',
                    'Try again after a short delay'
                ]
            )

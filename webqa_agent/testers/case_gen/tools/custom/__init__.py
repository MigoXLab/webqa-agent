"""Custom tools directory for WebQA Agent.

Place your custom tool implementations here. Tools using @register_tool
decorator are automatically discovered and registered when the package is imported.

Quick Start:
    1. Create a new file in this directory (e.g., my_tool.py)
    2. Implement your tool class extending WebQABaseTool
    3. Use @register_tool decorator for automatic registration
    4. The tool is now available in the test execution system

Example:
    from webqa_agent.testers.case_gen.tools.registry import register_tool
    from webqa_agent.testers.case_gen.tools.base import (
        WebQABaseTool,
        WebQAToolMetadata,
    )
    from typing import Any, Dict
    from pydantic import Field

    @register_tool
    class MyCustomTool(WebQABaseTool):
        name: str = "my_custom_tool"
        description: str = "Description of what the tool does"

        # Required: Browser access
        ui_tester_instance: Any = Field(
            ...,
            description="UITester instance for browser interaction"
        )

        # Optional: Step recording (recommended for all tools)
        case_recorder: Any | None = Field(
            default=None,
            description="Optional CentralCaseRecorder to record steps"
        )

        @classmethod
        def get_metadata(cls) -> WebQAToolMetadata:
            return WebQAToolMetadata(
                name="my_custom_tool",
                category="custom",
                step_type="custom_my_tool",  # Optional: for forced tool selection
                description_short="Short description for prompts",
            )

        @classmethod
        def get_required_params(cls) -> Dict[str, str]:
            # Declare required initialization parameters
            return {
                'ui_tester_instance': 'ui_tester_instance',
                'case_recorder': 'case_recorder',  # Include recorder
            }

        async def _arun(self, **kwargs) -> str:
            # Your tool logic here
            result = "operation completed"

            # Record step to test report (recommended)
            if self.case_recorder:
                self.case_recorder.add_step(
                    description="My custom operation",
                    screenshots=[],  # Add if capturing screenshots
                    model_io=result,  # Tool output or analysis
                    actions=[],  # Browser actions if any
                    status='passed',  # 'passed' | 'failed' | 'warning'
                    step_type='action',  # 'action' | 'verify' | 'ux_verify'
                )

            return self.format_success(result)

Notes:
    - Files starting with underscore (_) are skipped during auto-discovery
    - Use format_success(), format_failure(), format_critical_error() helpers
    - Category 'custom' tools appear in the Additional Custom Tools section
    - Category 'action' tools should call update_action_context() after execution
    - See link_detection_tool.py for a complete implementation example

Case Recorder Integration:
    All custom tools SHOULD integrate case_recorder to enable step recording
    in test reports. This provides visibility into tool execution and helps
    with debugging.

    When to record steps:
    - **Always**: For tools that perform user actions (clicks, input, navigation)
    - **Always**: For tools that perform verifications (assertions, checks)
    - **Recommended**: For tools that analyze page state (link detection, accessibility)
    - **Optional**: For pure utility tools that don't interact with the page

    How to record steps:
    1. Declare case_recorder Field: case_recorder: Any | None = Field(default=None, ...)
    2. Include in get_required_params: {'case_recorder': 'case_recorder'}
    3. Check and record in _arun: if self.case_recorder: recorder.add_step(...)

    Step types:
    - 'action': User interactions (click, input, scroll)
    - 'verify': Verification operations (assert state, check UI)
    - 'ux_verify': UX analysis (typo check, layout, accessibility)

    See link_detection_tool.py for a complete implementation example.
"""

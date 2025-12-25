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

    @register_tool
    class MyCustomTool(WebQABaseTool):
        name: str = "my_custom_tool"
        description: str = "Description of what the tool does"

        @classmethod
        def get_metadata(cls) -> WebQAToolMetadata:
            return WebQAToolMetadata(
                name="my_custom_tool",
                category="custom",
                step_type="custom_my_tool",  # Optional: for forced tool selection
                description_short="Short description for prompts",
            )

        async def _arun(self, **kwargs) -> str:
            # Implementation here
            return self.format_success("Operation completed")

Notes:
    - Files starting with underscore (_) are skipped during auto-discovery
    - Use format_success(), format_failure(), format_critical_error() helpers
    - Category 'custom' tools appear in the Additional Custom Tools section
    - Category 'action' tools should call update_action_context() after execution
    - See api_tool.py and screenshot_tool.py for complete examples
"""

"""Example custom tool for API testing.

This demonstrates how to create a custom tool that:
1. Uses WebQABaseTool for proper response formatting
2. Uses @register_tool for automatic discovery
3. Declares dependencies for auto-checking
4. Follows the response tag contract
5. Uses custom step_type for forced tool selection

Usage in test plans:
    {"type": "custom_api_test", "description": "Test the /api/health endpoint"}
    → System automatically calls execute_api_test tool
"""
from typing import Type

from pydantic import BaseModel, Field

from webqa_agent.testers.case_gen.tools.base import (WebQABaseTool,
                                                     WebQAToolMetadata)
from webqa_agent.testers.case_gen.tools.registry import register_tool


class APITestSchema(BaseModel):
    """Schema for API test tool arguments.

    LLM uses these Field descriptions to understand parameter usage.
    """

    endpoint: str = Field(
        description=(
            "API endpoint URL to test. Can be relative (e.g., '/api/users') "
            "or absolute (e.g., 'https://api.example.com/health')"
        )
    )
    method: str = Field(
        default='GET',
        description='HTTP method: GET, POST, PUT, DELETE, PATCH, HEAD, OPTIONS'
    )
    expected_status: int = Field(
        default=200,
        description='Expected HTTP status code (e.g., 200, 201, 404)'
    )
    timeout: int = Field(
        default=30,
        description='Request timeout in seconds'
    )


@register_tool  # Automatically registers to global registry on import
class APITestTool(WebQABaseTool):
    """Tool for testing API endpoints.

    This is a standalone custom tool that doesn't require browser access.
    It demonstrates:
    - Using format_success/format_failure/format_critical_error helpers
    - Declaring dependencies for auto-checking
    - Proper metadata for prompt generation and step_type mapping
    """

    name: str = 'execute_api_test'
    description: str = (
        'Tests an API endpoint and validates the response status code. '
        'Use this tool to verify backend health or API availability during UI tests.'
    )
    args_schema: Type[BaseModel] = APITestSchema

    # This tool doesn't need ui_tester_instance (standalone tool)
    # If browser access is needed, add: ui_tester_instance: Any = Field(...)

    @classmethod
    def get_metadata(cls) -> WebQAToolMetadata:
        """Return tool metadata for registration and prompt generation."""
        return WebQAToolMetadata(
            name='execute_api_test',
            category='custom',  # Custom category - appears in Additional Custom Tools
            step_type='custom_api_test',  # Maps step_type to this tool for forced selection
            description_short='Tests API endpoints and validates HTTP responses.',
            description_long=(
                'Performs HTTP requests to API endpoints and validates response status codes. '
                'Useful for verifying backend health or API availability during UI tests.\n'
                'Parameters:\n'
                '  - endpoint: API endpoint URL (relative or absolute)\n'
                '  - method: HTTP method (GET, POST, PUT, DELETE, etc.)\n'
                '  - expected_status: Expected HTTP status code\n'
                '  - timeout: Request timeout in seconds'
            ),
            examples=[
                '{{"action": "execute_api_test", "params": {"endpoint": "/api/health", "method": "GET", "expected_status": 200}}}',
                '{{"action": "execute_api_test", "params": {"endpoint": "/api/users", "method": "POST", "expected_status": 201}}}',
                '{{"action": "execute_api_test", "params": {"endpoint": "/api/config", "expected_status": 200}}}'
            ],
            use_when=[
                'API health checks',
                'backend validation',
                'pre-condition verification',
                'integration testing'
            ],
            dont_use_when=[
                'UI interaction',
                'visual testing',
                'DOM manipulation'
            ],
            priority=40,  # Lower than core tools (UITool=90, UIAssertTool=80)
            dependencies=['aiohttp']  # Automatically checked during registration
        )

    @classmethod
    def get_required_params(cls) -> dict:
        """Specify required initialization parameters.

        This tool doesn't require any context parameters - it's standalone.
        Override this method if your tool needs ui_tester_instance, llm_config, etc.
        """
        return {}  # No dependencies

    async def _arun(
        self,
        endpoint: str,
        method: str = 'GET',
        expected_status: int = 200,
        timeout: int = 30
    ) -> str:
        """Execute API test.

        Uses base class response helpers for proper control flow formatting.
        """
        try:
            import aiohttp
        except ImportError:
            # Use base class failure helper with recovery hints
            return self.format_failure(
                'aiohttp package not installed',
                recovery_hints=['Run: pip install aiohttp']
            )

        try:
            async with aiohttp.ClientSession() as session:
                async with session.request(
                    method,
                    endpoint,
                    timeout=aiohttp.ClientTimeout(total=timeout)
                ) as response:
                    actual_status = response.status
                    response_text = await response.text()

                    if actual_status == expected_status:
                        # Success: use format_success helper
                        return self.format_success(
                            f'API test passed: {method} {endpoint} returned {actual_status}',
                            # Optional: include response preview in page_state
                            page_state=f'Response preview: {response_text[:200]}...'
                            if len(response_text) > 200 else f'Response: {response_text}'
                        )
                    else:
                        # Failure: use format_failure helper with recovery hints
                        return self.format_failure(
                            f'API test failed: {method} {endpoint}',
                            recovery_hints=[
                                f'Expected status {expected_status}, got {actual_status}',
                                f'Response: {response_text[:200]}...',
                                'Check if the API endpoint is correct',
                                'Verify authentication if required',
                                'Check server logs for error details'
                            ]
                        )

        except aiohttp.ClientError as e:
            # Network error: use format_critical_error helper
            return self.format_critical_error(
                'NETWORK_ERROR',
                f'Cannot connect to {endpoint}: {str(e)}'
            )
        except Exception as e:
            return self.format_failure(f'Unexpected error: {str(e)}')

"""WebQA Agent tools system.

This package provides the tools system for WebQA Agent, including:
- Base classes for tool development (WebQABaseTool, WebQAToolMetadata)
- Tool registry for automatic discovery and instantiation
- Core tools (action, assertion, ux verification)
- Custom tools (performance, security, link detection, etc.)

Tool Registration:
    All tools use the @register_tool decorator for automatic registration.
    Custom tools are imported explicitly below to trigger registration on package import.

Usage:
    from webqa_agent.tools import get_registry

    registry = get_registry()
    tools = registry.get_tools(
        ui_tester_instance=tester,
        enabled_custom_tools=['lighthouse', 'nuclei']
    )
"""

from webqa_agent.tools.base import (ActionTypes, ResponseTags, WebQABaseTool,
                                    WebQAToolMetadata)
# ============================================================================
# Custom Tools Registration
# ============================================================================
# Import custom tool modules to trigger @register_tool decorator execution.
# This ensures custom tools are registered in the global ToolRegistry when
# the package is imported.
#
# Architecture:
# - Each custom tool uses @register_tool decorator (auto-registration pattern)
# - Decorator executes only when module is imported (Python behavior)
# - Explicit imports ensure deterministic registration order
# - New custom tools must be added here to be discovered by the registry
#
# Why explicit imports (not auto-discovery)?
# - ✅ Clear and readable (follows "Explicit is better than implicit")
# - ✅ IDE can track imports and provide autocomplete
# - ✅ Easy to debug and understand execution flow
# - ✅ Prevents accidental import of test files or temporary modules
# - ✅ Deterministic behavior (no surprises from filesystem changes)
# ============================================================================
from webqa_agent.tools.custom import \
    button_check_tool  # traverse_clickable_elements tool
from webqa_agent.tools.custom import \
    lighthouse_tool  # execute_lighthouse_test tool
from webqa_agent.tools.custom import \
    link_check_tool  # detect_dynamic_links tool
from webqa_agent.tools.custom import nuclei_tool  # execute_nuclei_scan tool
from webqa_agent.tools.registry import get_registry, register_tool

__all__ = [
    # Base classes
    'ActionTypes',
    'ResponseTags',
    'WebQABaseTool',
    'WebQAToolMetadata',
    # Registry
    'get_registry',
    'register_tool',
]

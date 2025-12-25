"""WebQA Agent Tools Package.

This package provides tools for the WebQA Agent test execution system.

Tools are automatically registered when imported through the ToolRegistry.
Custom tools placed in the 'custom/' directory are auto-discovered.

Usage:
    # Import registry and base classes
    from webqa_agent.testers.case_gen.tools import (
        get_registry,
        register_tool,
        WebQABaseTool,
        WebQAToolMetadata,
    )

    # Access built-in tools
    from webqa_agent.testers.case_gen.tools import (
        UITool,
        UIAssertTool,
        UIUXViewportTool,
    )

    # Get all registered tools
    registry = get_registry()
    tools = registry.get_tools(ui_tester_instance=tester)

Custom Tool Development:
    1. Create a file in tools/custom/ (e.g., tools/custom/my_tool.py)
    2. Use @register_tool decorator on your tool class
    3. Extend WebQABaseTool and implement get_metadata() and _arun()
    4. Tools are automatically discovered and registered on import
"""
import importlib
import logging
import pkgutil
from pathlib import Path

logger = logging.getLogger(__name__)

from .base import ActionTypes, ResponseTags, WebQABaseTool, WebQAToolMetadata
# ============================================================================
# Import built-in tool classes
# ============================================================================
from .element_action_tool import UIAssertTool, UITool
# ============================================================================
# Import registry and base classes first (no dependencies on tool classes)
# ============================================================================
from .registry import ToolRegistry, get_registry, register_tool
from .ux_tool import UIUXViewportTool

# ============================================================================
# Register built-in tools with the global registry
# ============================================================================
_registry = get_registry()
_registry.register(UITool)
_registry.register(UIAssertTool)
_registry.register(UIUXViewportTool)


# ============================================================================
# Auto-discover and register custom tools from custom/ directory
# ============================================================================
def _discover_custom_tools() -> None:
    """Discover and register tools from custom/ directory.

    Scans the custom/ subdirectory for Python modules and imports them. Modules
    starting with underscore are skipped.

    Tools using @register_tool decorator are auto-registered during import.
    """
    custom_dir = Path(__file__).parent / 'custom'
    if not custom_dir.exists():
        logger.debug('Custom tools directory does not exist: %s', custom_dir)
        return

    logger.debug('Scanning for custom tools in: %s', custom_dir)

    for _, module_name, _ in pkgutil.iter_modules([str(custom_dir)]):
        # Skip private modules (starting with underscore)
        if module_name.startswith('_'):
            continue

        try:
            # Import the module - @register_tool decorators will fire
            module = importlib.import_module(
                f'.custom.{module_name}',
                package=__name__
            )
            logger.debug(f'Loaded custom tool module: {module_name}')
        except ImportError as e:
            logger.warning(f"Failed to import custom tool module '{module_name}': {e}")
        except Exception as e:
            logger.debug(f"Failed to load custom tool module '{module_name}': {e}")


# Run auto-discovery on module import
_discover_custom_tools()


# ============================================================================
# Public API
# ============================================================================
__all__ = [
    # Registry functions
    'get_registry',
    'register_tool',
    'ToolRegistry',

    # Base classes for custom tools
    'WebQABaseTool',
    'WebQAToolMetadata',
    'ResponseTags',
    'ActionTypes',

    # Built-in tools
    'UITool',
    'UIAssertTool',
    'UIUXViewportTool',
]

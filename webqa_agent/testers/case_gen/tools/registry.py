"""Tool registry for dynamic tool loading and management.

This module provides:
1. ToolRegistry - Central registry for tool discovery and instantiation
2. get_registry() - Get the global registry singleton
3. register_tool - Decorator for automatic tool registration

Usage:
    # Register a tool using decorator
    from webqa_agent.testers.case_gen.tools.registry import register_tool

    @register_tool
    class MyTool(WebQABaseTool):
        ...

    # Get tools from registry
    from webqa_agent.testers.case_gen.tools.registry import get_registry

    registry = get_registry()
    tools = registry.get_tools(
        ui_tester_instance=tester,
        llm_config=config,
        case_recorder=recorder
    )
"""
import importlib.util
import logging
from typing import Any, Dict, List, Optional, Type

from langchain_core.tools import BaseTool

logger = logging.getLogger(__name__)

# Forward declaration to avoid circular import
WebQABaseTool = None
WebQAToolMetadata = None


def _lazy_import_base():
    """Lazy import base classes to avoid circular imports."""
    global WebQABaseTool, WebQAToolMetadata
    if WebQABaseTool is None:
        from .base import WebQABaseTool as _WebQABaseTool
        from .base import WebQAToolMetadata as _WebQAToolMetadata
        WebQABaseTool = _WebQABaseTool
        WebQAToolMetadata = _WebQAToolMetadata


class ToolRegistry:
    """Central registry for WebQA Agent tools.

    Provides:
    - Automatic tool discovery and registration
    - Dynamic tool instantiation with context injection
    - Tool metadata access and lookup

    The registry is a singleton to ensure consistent tool registration
    across the application.

    Usage:
        # Register tools
        registry = ToolRegistry()
        registry.register(UITool)
        registry.register(UIAssertTool)

        # Get instances with context
        tools = registry.get_tools(
            ui_tester_instance=tester,
            llm_config=config,
            case_recorder=recorder
        )

        # Get tool names and metadata
        tool_names = registry.get_tool_names()
        metadata = registry.get_metadata('execute_ui_action')
    """

    _instance: Optional['ToolRegistry'] = None

    def __new__(cls) -> 'ToolRegistry':
        """Singleton pattern for global registry access."""
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._tools: Dict[str, Type] = {}
            cls._instance._metadata_cache: Dict[str, Any] = {}
            cls._instance._step_type_mapping: Dict[str, str] = {}
        return cls._instance

    def register(self, tool_class: Type) -> None:
        """Register a tool class.

        The tool class can be either:
        - WebQABaseTool subclass with get_metadata()
        - Legacy BaseTool subclass without get_metadata()

        Args:
            tool_class: Tool class to register

        Raises:
            TypeError: If tool_class doesn't inherit from BaseTool
        """
        _lazy_import_base()

        if not issubclass(tool_class, BaseTool):
            raise TypeError(
                f'{tool_class.__name__} must inherit from BaseTool or WebQABaseTool'
            )

        # Get metadata if available
        if hasattr(tool_class, 'get_metadata'):
            try:
                metadata = tool_class.get_metadata()
                name = metadata.name
                self._metadata_cache[name] = metadata

                # Register step_type mapping for documentation and action registration
                # This mapping serves TWO purposes:
                # 1. Planning prompts: Provides tool documentation with step_type labels
                # 2. Action registration: Auto-registers custom tools to ActionTypes
                # Note: LLM tool selection is NOT restricted - entirely based on descriptions.
                # Future enhancement: Tool masking feature is not yet implemented.
                if metadata.step_type:
                    self._step_type_mapping[metadata.step_type] = name
                    logger.debug(f'Registered step_type mapping: {metadata.step_type} -> {name}')

                    # Auto-register custom tools to ActionTypes for planning prompts
                    # This ensures custom tool names appear in action_types_str automatically
                    if hasattr(metadata, 'category') and metadata.category == 'custom':
                        from .base import ActionTypes
                        ActionTypes.register_action(metadata.step_type)
                        logger.debug(f'Registered custom action type: {metadata.step_type}')

                # Check dependencies
                if metadata.dependencies:
                    self._check_dependencies(metadata)

            except Exception as e:
                logger.warning(f'Failed to get metadata from {tool_class.__name__}: {e}')
                name = getattr(tool_class, 'name', tool_class.__name__)
        else:
            # Fallback for legacy tools (BaseTool without get_metadata)
            name = getattr(tool_class, 'name', tool_class.__name__)

        self._tools[name] = tool_class
        logger.debug(f'Registered tool: {name}')

    def _check_dependencies(self, metadata: Any) -> bool:
        """Check if tool dependencies are installed.

        Args:
            metadata: WebQAToolMetadata instance

        Returns:
            True if all dependencies are installed, False otherwise
        """
        all_installed = True
        for dep in metadata.dependencies:
            if importlib.util.find_spec(dep) is None:
                logger.warning(
                    f"Tool '{metadata.name}' requires '{dep}' but it's not installed. "
                    f'Install with: pip install {dep}'
                )
                all_installed = False
        return all_installed

    def register_all(self, tool_classes: List[Type]) -> None:
        """Register multiple tool classes.

        Args:
            tool_classes: List of tool classes to register
        """
        for tool_class in tool_classes:
            self.register(tool_class)

    def unregister(self, name: str) -> None:
        """Unregister a tool by name.

        Args:
            name: Tool name to unregister
        """
        if name in self._tools:
            del self._tools[name]

            # Clean up metadata cache
            if name in self._metadata_cache:
                metadata = self._metadata_cache[name]
                if hasattr(metadata, 'step_type') and metadata.step_type:
                    self._step_type_mapping.pop(metadata.step_type, None)
                del self._metadata_cache[name]

            logger.debug(f'Unregistered tool: {name}')

    def get_tools(
        self,
        ui_tester_instance: Any = None,
        llm_config: Optional[Dict] = None,
        case_recorder: Any = None,
        categories: Optional[List[str]] = None,
        **extra_params
    ) -> List[BaseTool]:
        """Instantiate and return all registered tools.

        Creates new instances of all registered tools with the provided
        context parameters. Tools are filtered by category if specified
        and sorted by priority.

        Args:
            ui_tester_instance: UITester instance for browser access
            llm_config: LLM configuration dict
            case_recorder: CentralCaseRecorder instance
            categories: Optional filter by category (e.g., ['action', 'assertion'])
            **extra_params: Additional parameters for custom tools

        Returns:
            List of instantiated tool objects, sorted by priority (high to low)
        """
        tools = []
        context = {
            'ui_tester_instance': ui_tester_instance,
            'llm_config': llm_config,
            'case_recorder': case_recorder,
            **extra_params
        }

        for name, tool_class in self._tools.items():
            # Filter by category if specified
            if categories:
                metadata = self._metadata_cache.get(name)
                if metadata and hasattr(metadata, 'category'):
                    if metadata.category not in categories:
                        continue

            try:
                # Get required params for this tool
                if hasattr(tool_class, 'get_required_params'):
                    required = tool_class.get_required_params()
                else:
                    # Default: only ui_tester_instance
                    required = {'ui_tester_instance': 'ui_tester_instance'}

                # Build kwargs for instantiation
                kwargs = {}
                for param_name, source in required.items():
                    if source in context and context[source] is not None:
                        kwargs[param_name] = context[source]

                # Instantiate tool
                tool = tool_class(**kwargs)
                tools.append(tool)

            except Exception as e:
                logger.warning(f'Failed to instantiate tool {name}: {e}')

        # Sort by priority if metadata available
        def get_priority(tool):
            tool_name = getattr(tool, 'name', '')
            metadata = self._metadata_cache.get(tool_name)
            if metadata and hasattr(metadata, 'priority'):
                return metadata.priority
            return 50  # Default priority

        tools.sort(key=get_priority, reverse=True)

        return tools

    def get_tool_names(self) -> List[str]:
        """Return list of registered tool names.

        Returns:
            List of tool names (e.g., ['execute_ui_action', 'execute_api_test'])
        """
        return list(self._tools.keys())

    def get_metadata(self, tool_name: str) -> Optional[Any]:
        """Get metadata for a specific tool.

        Args:
            tool_name: Tool name to lookup

        Returns:
            WebQAToolMetadata instance or None if not found
        """
        return self._metadata_cache.get(tool_name)

    def clear(self) -> None:
        """Clear all registered tools (mainly for testing)."""
        self._tools.clear()
        self._metadata_cache.clear()
        self._step_type_mapping.clear()


# ============================================================================
# Global Registry Instance
# ============================================================================
_global_registry: Optional[ToolRegistry] = None


def get_registry() -> ToolRegistry:
    """Get the global tool registry instance.

    Returns:
        The singleton ToolRegistry instance
    """
    global _global_registry
    if _global_registry is None:
        _global_registry = ToolRegistry()
    return _global_registry


def register_tool(tool_class: Type) -> Type:
    """Decorator to register a tool class.

    Use this decorator on tool classes to automatically register them
    with the global registry when the module is imported.

    Usage:
        @register_tool
        class MyCustomTool(WebQABaseTool):
            name: str = "my_custom_tool"
            ...

    Args:
        tool_class: Tool class to register

    Returns:
        The same tool class (unchanged)
    """
    get_registry().register(tool_class)
    return tool_class

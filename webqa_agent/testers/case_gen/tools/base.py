"""Base class for all WebQA Agent tools.

This module provides:
1. ResponseTags - Structured response tags that drive agent control flow
2. ActionTypes - Extensible action types for planning phase
3. WebQAToolMetadata - Tool metadata for registration and prompt generation
4. WebQABaseTool - Abstract base class with response formatting and context management

Usage:
    from webqa_agent.testers.case_gen.tools.base import (
        WebQABaseTool,
        WebQAToolMetadata,
        ResponseTags,
        ActionTypes,
    )

    class MyTool(WebQABaseTool):
        name = "my_tool"

        @classmethod
        def get_metadata(cls):
            return WebQAToolMetadata(
                name="my_tool",
                category="custom",
                description_short="My custom tool",
            )

        async def _arun(self, **kwargs) -> str:
            return self.format_success("Done!")
"""
import logging
from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional

from langchain_core.tools import BaseTool
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)


# ============================================================================
# Response Tag Constants (驱动 execute_agent.py 控制流)
# ============================================================================
class ResponseTags:
    """Structured response tags that drive agent control flow.

    These tags are detected by execute_agent.py to determine:
    - SUCCESS: Continue to next step
    - FAILURE: Trigger adaptive recovery (if dynamic_step_generation enabled)
    - CRITICAL_ERROR: Abort test immediately
    - WARNING: Non-blocking issue, continue execution
    - CANNOT_VERIFY: Verification prerequisite failed

    All custom tools MUST return one of these tags for proper control flow.
    """

    SUCCESS = '[SUCCESS]'
    FAILURE = '[FAILURE]'
    WARNING = '[WARNING]'
    CANNOT_VERIFY = '[CANNOT_VERIFY]'

    # Critical error types (cause immediate test abort)
    # Format: [CRITICAL_ERROR:TYPE]
    CRITICAL_ELEMENT_NOT_FOUND = '[CRITICAL_ERROR:ELEMENT_NOT_FOUND]'
    CRITICAL_NAVIGATION_FAILED = '[CRITICAL_ERROR:NAVIGATION_FAILED]'
    CRITICAL_PERMISSION_DENIED = '[CRITICAL_ERROR:PERMISSION_DENIED]'
    CRITICAL_PAGE_CRASHED = '[CRITICAL_ERROR:PAGE_CRASHED]'
    CRITICAL_NETWORK_ERROR = '[CRITICAL_ERROR:NETWORK_ERROR]'
    CRITICAL_SESSION_EXPIRED = '[CRITICAL_ERROR:SESSION_EXPIRED]'
    CRITICAL_UNSUPPORTED_PAGE = '[CRITICAL_ERROR:UNSUPPORTED_PAGE]'
    CRITICAL_VALIDATION_ERROR = '[CRITICAL_ERROR:VALIDATION_ERROR]'


# ============================================================================
# Action Types (支持动态扩展 - 用于 planning_prompts.py)
# ============================================================================
class ActionTypes:
    """Extensible action types for planning phase.

    Core action types cannot be removed. Custom tools can register additional
    action types that will be included in planning prompts.

    Usage:
        # Register a custom action type
        ActionTypes.register_action("SwipeLeft")

        # Get all action types for prompt
        prompt = f"Use these actions: {ActionTypes.get_prompt_string()}"

        # Check if an action type is valid
        is_valid = "SwipeLeft" in ActionTypes.all()
    """

    # Core action types (frozen - cannot be removed)
    CORE = frozenset([
        'Tap', 'Input', 'Scroll', 'SelectDropdown', 'Clear', 'Hover',
        'KeyboardPress', 'Upload', 'Drag', 'GoToPage', 'GoBack', 'Sleep', 'Mouse'
    ])

    # Custom action types (extensible via registry)
    _custom: set = set()

    @classmethod
    def register_action(cls, action_name: str) -> None:
        """Register a custom action type.

        Args:
            action_name: Action name to register (e.g., 'SwipeLeft', 'DoubleTap')
        """
        if action_name not in cls.CORE:
            cls._custom.add(action_name)
            logger.debug(f'Registered custom action type: {action_name}')

    @classmethod
    def unregister_action(cls, action_name: str) -> None:
        """Unregister a custom action type.

        Args:
            action_name: Action name to unregister
        """
        cls._custom.discard(action_name)

    @classmethod
    def all(cls) -> set:
        """Get all registered action types (core + custom).

        Returns:
            Set of all valid action type names
        """
        return cls.CORE | cls._custom

    @classmethod
    def get_prompt_string(cls) -> str:
        """Generate action types string for planning prompts.

        Returns:
            Formatted string like: "Tap", "Input", "Scroll", ...
        """
        return ', '.join(f'"{a}"' for a in sorted(cls.all()))

    @classmethod
    def clear_custom(cls) -> None:
        """Clear all custom action types (mainly for testing)."""
        cls._custom.clear()


# ============================================================================
# Tool Metadata (用于注册和Prompt生成)
# ============================================================================
class WebQAToolMetadata(BaseModel):
    """Metadata for tool registration and prompt generation.

    This metadata is used by:
    1. ToolRegistry - for tool discovery and instantiation
    2. Prompt generation - for dynamic tool documentation
    3. Execution logging - for step type identification

    Attributes:
        name: Tool name used in LangChain (e.g., 'execute_api_test')
        category: Tool category for filtering and organization
        step_type: Step type that triggers this tool (e.g., 'custom_api_test')
        description_short: One-line description for prompt
        description_long: Detailed description with parameter info
        examples: Usage examples for the prompt
        use_when: Hints for when to use this tool
        dont_use_when: Hints for when NOT to use this tool
        priority: Tool priority for sorting (higher = preferred)
        dependencies: Required Python packages
    """

    # Core identification
    name: str = Field(..., description='Tool name used in LangChain')
    category: str = Field(
        default='custom',
        description='Tool category: action, assertion, ux, custom'
    )

    # Step type identifier (for planning documentation and execution logging)
    step_type: Optional[str] = Field(
        default=None,
        description=(
            'Step type identifier used for test planning documentation and execution logging. '
            "For custom tools, use 'custom_xxx' format (e.g., 'custom_api_test'). "
            'This identifier helps distinguish step types in planning prompts and execution logs. '
            'Note: This does NOT restrict LLM tool selection - the LLM chooses tools freely '
            'based on tool descriptions and context. If None, the tool appears in planning '
            'documentation by tool name only.'
        )
    )

    # Prompt generation helpers
    description_short: str = Field(
        default='',
        description='One-line description for prompt'
    )
    description_long: str = Field(
        default='',
        description='Detailed description with examples'
    )

    # Usage examples for prompt
    examples: List[str] = Field(
        default_factory=list,
        description='Usage examples'
    )

    # Tool selection hints
    use_when: List[str] = Field(
        default_factory=list,
        description='When to use this tool'
    )
    dont_use_when: List[str] = Field(
        default_factory=list,
        description='When NOT to use this tool'
    )

    # Priority for tool selection (higher = preferred)
    priority: int = Field(
        default=50,
        description='Tool priority 1-100 (core tools: 70-90, custom: 30-60)'
    )

    # Dependencies (for auto-checking)
    dependencies: List[str] = Field(
        default_factory=list,
        description="Required Python packages (e.g., ['aiohttp', 'beautifulsoup4'])"
    )

    class Config:
        """Pydantic configuration."""
        extra = 'allow'  # Allow additional fields for future extension


# ============================================================================
# Base Tool Class (所有自定义工具的基类)
# ============================================================================
class WebQABaseTool(BaseTool, ABC):
    """Abstract base class for all WebQA Agent tools.

    Provides:
    - Response formatting helpers (format_success, format_failure, format_critical_error)
    - Context management patterns (update_action_context, get_execution_context)
    - Metadata declaration for registration

    All tools must implement:
    - get_metadata(): Returns tool metadata for registration
    - _arun(): Async execution implementation (must use response helpers)

    Example:
        @register_tool
        class MyTool(WebQABaseTool):
            name: str = "my_tool"
            description: str = "My custom tool"
            args_schema: Type[BaseModel] = MyToolSchema
            ui_tester_instance: Any = Field(...)  # If needed

            @classmethod
            def get_metadata(cls) -> WebQAToolMetadata:
                return WebQAToolMetadata(
                    name="my_tool",
                    category="custom",
                    step_type="custom_my_tool",
                    description_short="Does something useful",
                )

            async def _arun(self, param1: str) -> str:
                # Use format helpers for proper control flow
                return self.format_success("Operation completed")
    """

    # ========================================================================
    # Response Formatting Helpers (确保控制流正确)
    # ========================================================================

    def format_success(self, message: str, **context) -> str:
        """Format a success response.

        Use this method to return success results. The [SUCCESS] tag is
        required for execute_agent.py to continue to the next step.

        Args:
            message: Success message describing what was accomplished
            **context: Additional context to include in response:
                - dom_diff: Dict of DOM changes (triggers dynamic step generation)
                - page_state: Current page state string (truncated to 1500 chars)

        Returns:
            Formatted response string with [SUCCESS] tag

        Example:
            return self.format_success(
                "Logged in successfully",
                page_state="Dashboard page loaded"
            )
        """
        response = f'{ResponseTags.SUCCESS} {message}'

        # Append DOM diff if present (for dynamic step generation)
        if 'dom_diff' in context and context['dom_diff']:
            import json
            response += f"\n\nDOM_DIFF_DETECTED: {json.dumps(context['dom_diff'], ensure_ascii=False)}"

        # Append page state if present
        if 'page_state' in context:
            page_state = str(context['page_state'])
            response += f'\n\nCurrent Page State:\n{page_state[:1500]}'

        return response

    def format_failure(self, message: str, recovery_hints: Optional[List[str]] = None) -> str:
        """Format a recoverable failure response.

        Use this method for failures that might be recoverable through
        adaptive recovery (when dynamic_step_generation is enabled).

        Args:
            message: Failure description
            recovery_hints: Optional list of recovery suggestions for the LLM

        Returns:
            Formatted response string with [FAILURE] tag

        Example:
            return self.format_failure(
                "Element not clickable",
                recovery_hints=[
                    "Try scrolling to make element visible",
                    "Wait for page to finish loading"
                ]
            )
        """
        response = f'{ResponseTags.FAILURE} {message}'

        if recovery_hints:
            response += '\n\n**Recovery Actions**:\n'
            for i, hint in enumerate(recovery_hints, 1):
                response += f'{i}. {hint}\n'

        return response

    def format_critical_error(self, error_type: str, message: str) -> str:
        """Format a critical error response (causes test abort).

        Use this method for unrecoverable errors that should immediately
        abort the current test case.

        Args:
            error_type: One of the error types from ResponseTags:
                - ELEMENT_NOT_FOUND
                - NAVIGATION_FAILED
                - PERMISSION_DENIED
                - PAGE_CRASHED
                - NETWORK_ERROR
                - SESSION_EXPIRED
                - UNSUPPORTED_PAGE
                - VALIDATION_ERROR
            message: Error details

        Returns:
            Formatted response string with [CRITICAL_ERROR:TYPE] tag

        Example:
            return self.format_critical_error(
                "NETWORK_ERROR",
                "Cannot connect to API endpoint: Connection refused"
            )
        """
        return f'[CRITICAL_ERROR:{error_type}] {message}'

    def format_warning(self, message: str) -> str:
        """Format a warning response (non-blocking issue).

        Use this method for issues that should be logged but don't
        prevent test execution from continuing.

        Args:
            message: Warning message

        Returns:
            Formatted response string with [WARNING] tag
        """
        return f'{ResponseTags.WARNING} {message}'

    def format_cannot_verify(self, message: str, reason: str) -> str:
        """Format a cannot-verify response.

        Use this method when verification cannot be performed due to
        missing prerequisites (e.g., element not found for assertion).

        Args:
            message: What couldn't be verified
            reason: Why verification couldn't be performed

        Returns:
            Formatted response string with [CANNOT_VERIFY] tag
        """
        return f'{ResponseTags.CANNOT_VERIFY} {message}. Reason: {reason}'

    # ========================================================================
    # Context Management (工具间状态共享)
    # ========================================================================

    def update_action_context(self, ui_tester: Any, context: Dict[str, Any]) -> None:
        """Update last_action_context for subsequent assertion tools.

        Action category tools SHOULD call this after execution to enable
        context-aware assertions.

        Args:
            ui_tester: UITester instance
            context: Action execution context, typically including:
                - description: What action was performed
                - action_type: Type of action (e.g., 'Tap', 'Input')
                - target: Target element description
                - value: Value used (for Input, SelectDropdown, etc.)
                - status: 'success' or 'failure'
                - timestamp: ISO format timestamp

        Example:
            self.update_action_context(
                self.ui_tester_instance,
                {
                    "description": "Clicked login button",
                    "action_type": "Tap",
                    "target": "login button",
                    "status": "success",
                    "timestamp": datetime.now().isoformat()
                }
            )
        """
        if hasattr(ui_tester, 'last_action_context'):
            ui_tester.last_action_context = context
            logger.debug(f"Updated action context: {context.get('description', 'N/A')}")

    def get_execution_context(self, ui_tester: Any) -> Optional[Dict[str, Any]]:
        """Get execution context from previous actions.

        Assertion category tools SHOULD call this for context-aware verification.

        Args:
            ui_tester: UITester instance

        Returns:
            Execution context dict containing:
                - last_action: Context from the most recent action
                - test_objective: Current test case objective
                - success_criteria: List of success criteria
                - completed_steps: List of successfully completed steps
                - failed_steps: List of failed steps
            Or None if no context is available
        """
        if not hasattr(ui_tester, 'last_action_context') or not ui_tester.last_action_context:
            return None

        return {
            'last_action': ui_tester.last_action_context,
            'test_objective': getattr(ui_tester, 'current_test_objective', None),
            'success_criteria': getattr(ui_tester, 'current_success_criteria', []),
            'completed_steps': [
                h for h in getattr(ui_tester, 'execution_history', [])
                if h.get('success') is True
            ],
            'failed_steps': [
                h for h in getattr(ui_tester, 'execution_history', [])
                if h.get('success') is False
            ]
        }

    # ========================================================================
    # Abstract Methods (子类必须实现)
    # ========================================================================

    @classmethod
    @abstractmethod
    def get_metadata(cls) -> WebQAToolMetadata:
        """Return metadata for tool registration and prompt generation.

        Must be implemented by all tool subclasses.

        Returns:
            WebQAToolMetadata instance with tool configuration
        """
        pass

    @classmethod
    def get_required_params(cls) -> Dict[str, str]:
        """Return required initialization parameters.

        Override to specify which parameters the tool needs from the context.

        Returns:
            Dict mapping param_name -> source_name
            Available sources:
                - 'ui_tester_instance': UITester instance with browser access
                - 'llm_config': LLM configuration dict
                - 'case_recorder': CentralCaseRecorder instance

        Example:
            @classmethod
            def get_required_params(cls) -> Dict[str, str]:
                return {
                    'ui_tester_instance': 'ui_tester_instance',
                    'llm_config': 'llm_config',
                }
        """
        return {'ui_tester_instance': 'ui_tester_instance'}

    def _run(self, **kwargs) -> str:
        """Sync execution - not supported.

        All WebQA Agent tools must use async execution via _arun().

        Raises:
            NotImplementedError: Always raised
        """
        raise NotImplementedError(
            'Sync execution not supported. Use async execution via _arun().'
        )

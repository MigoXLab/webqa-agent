"""Tool instantiation and dynamic configuration helpers.

Provides functions for assembling core + custom tools, extracting dynamic step
generation configuration from state, and parsing step types.
"""

__all__ = ['get_tools', 'get_dynamic_config', 'parse_step_type']

import logging
from typing import Any, Optional

from webqa_agent.tools.action_tool import UITool
from webqa_agent.tools.registry import get_registry
from webqa_agent.tools.ux_tool import UIUXViewportTool
from webqa_agent.tools.verify_tool import UIAssertTool

logger = logging.getLogger(__name__)


def get_tools(
    ui_tester_instance: Any,
    llm_config: dict,
    case_recorder: Any,
    enabled_custom_tools: Optional[list[str]] = None,
) -> list:
    """Get tools combining core tools with registry tools.

    Always includes core tools (UITool, UIAssertTool, UIUXViewportTool) and
    adds any custom tools from the registry if available and enabled.

    Args:
        ui_tester_instance: UITester instance for browser access
        llm_config: LLM configuration dict
        case_recorder: CentralCaseRecorder instance
        enabled_custom_tools: Optional list of custom tool step_types to enable
                             (e.g., ['lighthouse', 'nuclei', 'detect_dynamic_links'])

    Returns:
        List of instantiated tool objects (core tools + enabled custom tools)
    """
    # Always instantiate core tools to ensure consistent behavior
    core_tools = [
        UITool(ui_tester_instance=ui_tester_instance, case_recorder=case_recorder),
        UIAssertTool(
            ui_tester_instance=ui_tester_instance, case_recorder=case_recorder
        ),
        UIUXViewportTool(
            ui_tester_instance=ui_tester_instance,
            llm_config=llm_config,
            case_recorder=case_recorder,
        ),
    ]
    logger.debug(f'Core tools instantiated: {[t.name for t in core_tools]}')

    # Try to load custom tools from registry (filtered by enabled_custom_tools)
    custom_tools: list = []
    try:
        registry = get_registry()
        tool_names = registry.get_tool_names()
        if tool_names:
            # Get filtered tools from registry based on enabled_custom_tools
            registry_tools = registry.get_tools(
                ui_tester_instance=ui_tester_instance,
                llm_config=llm_config,
                case_recorder=case_recorder,
                enabled_custom_tools=enabled_custom_tools,  # Pass filtering parameter
            )
            if registry_tools:
                # Filter out core tools from registry to avoid duplicates
                # Only keep custom tools (category='custom')
                core_tool_names = {t.name for t in core_tools}
                custom_tools = [
                    t for t in registry_tools if t.name not in core_tool_names
                ]
                if custom_tools:
                    logger.debug(
                        f'Custom tools loaded from registry: {[t.name for t in custom_tools]}'
                    )
                elif enabled_custom_tools:
                    logger.debug(
                        f'No custom tools loaded (enabled: {enabled_custom_tools})'
                    )
    except Exception as e:
        logger.warning(
            f'Registry loading failed, continuing with core tools only: {e}'
        )

    # Return combined list: core tools + custom tools
    all_tools = core_tools + custom_tools
    logger.debug(f'Total tools available: {[t.name for t in all_tools]}')
    return all_tools


# ============================================================================
# Dynamic Step Generation Configuration Helper
# ============================================================================


def get_dynamic_config(state: dict) -> dict:
    """Extract and merge dynamic step generation config from state with
    defaults.

    Centralized config extraction ensures all code paths use identical defaults.
    Always returns a complete configuration dictionary with all keys present.

    Default values (8, 2) provide balanced approach:
    - max_dynamic_steps=8: Covers 90% of UI changes (modals, dropdowns, forms)
      while preventing verbose generation
    - min_elements_threshold=2: Filters single-element noise (spinners, tooltips)
      while catching meaningful changes

    Args:
        state: Graph state containing dynamic_step_generation config

    Returns:
        A complete configuration dictionary with all keys present.
        User-provided values override defaults.
    """
    defaults = {'enabled': True, 'max_dynamic_steps': 8, 'min_elements_threshold': 2}
    user_config = state.get('dynamic_step_generation', {})
    # Merge defaults with user config. User values override defaults.
    return {**defaults, **user_config}


# ============================================================================
# Step Type Parsing Helper
# ============================================================================


def parse_step_type(step: dict) -> str:
    """Parse step type from test step dict.

    Supports both core fields (action, verify, ux_verify) and custom tool fields (type).

    Args:
        step: Test step dictionary

    Returns:
        Step type string: 'Action', 'Assertion', 'UX_Verify', or custom step type
    """
    if step.get('action'):
        return 'Action'
    elif step.get('verify'):
        return 'Assertion'
    elif step.get('ux_verify'):
        return 'UX_Verify'
    elif step.get('type'):
        # Custom tool step type (e.g., 'custom_api_test')
        step_type = step['type']
        logger.debug(f'Custom step type detected: {step_type}')
        return step_type
    else:
        # Fallback to Assertion for unknown step formats
        logger.warning(f'Unknown step format, defaulting to Assertion: {step}')
        return 'Assertion'

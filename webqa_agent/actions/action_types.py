"""Centralized Action Type Definitions and Metadata.

This module provides unified action type constants and metadata to avoid
string hardcoding across the codebase and ensure consistent behavior.

Key Features:
- ActionType enumeration for type safety
- PAGE_AGNOSTIC_ACTIONS set for quick lookup
- ACTION_METADATA for enhanced capabilities
- Helper functions for common operations
"""

from enum import Enum
from typing import Dict, Set


class ActionType(str, Enum):
    """Enumeration of all supported action types.

    Action types are categorized into:
    - DOM-dependent actions: Require page DOM elements (Tap, Input, etc.)
    - Page-agnostic actions: Browser-level operations (GoBack, GoToPage, Sleep, etc.)
    """

    # DOM-dependent actions (require interactive elements on page)
    TAP = 'Tap'
    INPUT = 'Input'
    HOVER = 'Hover'
    CLEAR = 'Clear'
    SELECT_DROPDOWN = 'SelectDropdown'
    DRAG = 'Drag'
    UPLOAD = 'Upload'
    KEYBOARD_PRESS = 'KeyboardPress'
    MOUSE = 'Mouse'
    SCROLL = 'Scroll'
    CHECK = 'Check'

    # Page-agnostic actions (browser-level operations, work on PDF/plugin pages)
    GO_BACK = 'GoBack'
    GO_TO_PAGE = 'GoToPage'
    SLEEP = 'Sleep'


# Page-agnostic actions set (can execute on PDF/plugin pages)
# These operations don't require DOM elements and work at browser level
PAGE_AGNOSTIC_ACTIONS: Set[str] = {
    ActionType.GO_BACK,
    ActionType.SLEEP,
}


# Action metadata for enhanced capabilities
# Provides additional information about each action type
ACTION_METADATA: Dict[str, Dict] = {
    ActionType.GO_BACK: {
        'is_page_agnostic': True,
        'requires_dom': False,
        'requires_target': False,
        'default_phrase': 'Navigate back to the previous page',
        'aliases': [
            'go back',
            'navigate back',
            'back',
            'browser back',
        ],
        'description': 'Navigates back in browser history',
    },
    ActionType.SLEEP: {
        'is_page_agnostic': True,
        'requires_dom': False,
        'requires_target': False,
        'default_phrase_template': 'Wait for {value} milliseconds',
        'aliases': [
            'wait',
            'sleep',
            'pause',
            'wait for',
        ],
        'description': 'Pauses execution for specified duration',
    },
}


def is_page_agnostic_action(action_type: str) -> bool:
    """Check if action type is page-agnostic (can run on PDF/plugin pages).

    Page-agnostic actions operate at browser level and don't require DOM elements,
    so they can execute on unsupported page types like PDF, plugins, downloads, etc.

    Args:
        action_type: Action type string (e.g., "GoBack", "Tap")

    Returns:
        True if action is page-agnostic, False otherwise

    Examples:
        >>> is_page_agnostic_action("GoBack")
        True
        >>> is_page_agnostic_action("Tap")
        False
    """
    return action_type in PAGE_AGNOSTIC_ACTIONS


def get_action_default_phrase(action_type: str, target: str = '', value: str = '') -> str:
    """Get default action phrase for instruction building.

    This function provides standardized action phrases to avoid inconsistent
    instruction formatting across the codebase.

    Args:
        action_type: Action type (e.g., "GoBack")
        target: Target element identifier (optional)
        value: Action value (optional)

    Returns:
        Formatted action phrase string

    Examples:
        >>> get_action_default_phrase("GoBack")
        "Navigate back to the previous page"
        >>> get_action_default_phrase("Sleep", value="2000")
        "Wait for 2000 milliseconds"
        >>> get_action_default_phrase("Tap", target="button_123")
        "Tap on button_123"
    """
    metadata = ACTION_METADATA.get(action_type, {})

    # Use template if available (e.g., Sleep action)
    if 'default_phrase_template' in metadata:
        return metadata['default_phrase_template'].format(value=value or '1000')

    # Use default phrase if available
    elif 'default_phrase' in metadata:
        return metadata['default_phrase']

    # Fallback: construct from action type and target
    else:
        if target:
            return f'{action_type} on {target}'
        else:
            return action_type


def get_action_aliases(action_type: str) -> list:
    """Get list of common aliases for an action type.

    Useful for keyword-based detection in instructions.

    Args:
        action_type: Action type (e.g., "GoBack")

    Returns:
        List of alias strings

    Examples:
        >>> get_action_aliases("GoBack")
        ["go back", "navigate back", "back", ...]
    """
    metadata = ACTION_METADATA.get(action_type, {})
    return metadata.get('aliases', [])


def requires_dom_elements(action_type: str) -> bool:
    """Check if action type requires DOM elements to execute.

    Args:
        action_type: Action type (e.g., "Tap", "GoBack")

    Returns:
        True if action requires DOM, False otherwise
    """
    metadata = ACTION_METADATA.get(action_type, {})
    # Default to True (safe default - most actions need DOM)
    return metadata.get('requires_dom', True)


def get_page_agnostic_keywords() -> list:
    """Get comprehensive list of keywords indicating page-agnostic operations.

    This function provides a centralized keyword list for identifying page-agnostic
    operations from instruction text. These keywords are used by both function_tester.py
    and execute_agent.py to detect operations that can run on unsupported page types
    (PDF, plugins, etc.) without requiring DOM access.

    Returns:
        List of lowercase keyword strings for page-agnostic operation detection

    Examples:
        >>> keywords = get_page_agnostic_keywords()
        >>> 'close current tab' in keywords
        True
        >>> 'go back' in keywords
        True

    Note:
        Keywords are lowercase and normalized (spaces, no underscores/hyphens)
        for case-insensitive matching. Calling code should normalize instructions
        to lowercase and replace underscores/hyphens with spaces before matching.

        IMPORTANT: Use only contextual phrases, not standalone words that appear
        in multiple contexts. For example, use "go back" instead of "back" to avoid
        false positives in phrases like "switch back", "bring back", "back button".
    """
    return [
        # GoBack variations - ONLY contextual phrases (removed standalone "back")
        'goback', 'go back', 'navigate back', 'browser back', 'previous page',
        # GoForward variations - ONLY contextual phrases (removed standalone "forward")
        'goforward', 'go forward', 'navigate forward', 'next page',
        # Sleep variations - removed "wait" (too generic), kept "wait for"
        'sleep', 'wait for', 'pause',
    ]

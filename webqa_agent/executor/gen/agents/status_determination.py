"""Status determination and safety guard helpers.

Provides LLM-first + Safety Guard status determination logic, failure
classification, objective achievement detection, and navigation/provider
detection utilities.
"""

__all__ = [
    'apply_safety_guard',
    'derive_failure_type_from_outcomes',
    'detect_llm_provider',
    'extract_failed_step_details',
    'is_critical_failure_step',
    'is_navigation_instruction',
    'is_objective_achieved',
    'is_operation_page_agnostic',
    'parse_llm_status',
    'verdict_fallback',
]

import logging
import re
from typing import Any, Optional

from webqa_agent.actions.action_types import (ActionType,
                                              get_page_agnostic_keywords)
from webqa_agent.data.gen_structures import StepOutcome, StepSeverity

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

def _collect_severities(step_outcomes: list[StepOutcome]) -> set:
    """Collect unique severity values from step outcomes."""
    return {o.severity for o in step_outcomes} if step_outcomes else set()


# ---------------------------------------------------------------------------
# Objective achievement detection
# ---------------------------------------------------------------------------

def is_objective_achieved(tool_output: str) -> tuple[bool, str]:
    """Check if the agent has signaled that the test objective is achieved.

    Args:
        tool_output: The output from the step execution

    Returns:
        tuple: (is_achieved: bool, reason: str)
    """
    if not tool_output or 'objective_achieved:' not in tool_output.lower():
        return False, ''

    try:
        # Extract the reason after the signal (case-insensitive)
        tool_output_lower = tool_output.lower()
        marker_idx = tool_output_lower.find('objective_achieved:')
        if marker_idx != -1:
            # Extract from original tool_output to preserve case
            start_idx = marker_idx + len('objective_achieved:')
            remaining = tool_output[start_idx:]
            reason = remaining.split('\n')[0].strip()
            # Only return True if there's actual content after the signal
            if reason:
                return True, reason
    except Exception as e:
        logger.debug(f'Error parsing objective achievement signal: {e}')

    return False, ''


# ---------------------------------------------------------------------------
# Page-agnostic operation detection
# ---------------------------------------------------------------------------

def is_operation_page_agnostic(step_type: str, instruction: str) -> bool:
    """Determine if operation is page-type agnostic (can execute on unsupported
    page).

    Page-agnostic operations don't depend on DOM elements and can execute on PDF/plugin pages:
    - Browser navigation: GoBack, GoForward, GoToPage, Sleep
    - UX verification: UX_Verify (already implements screenshot fallback)

    Args:
        step_type: Step type (Action, Verify, UX_Verify, UI_Assert)
        instruction: Instruction text

    Returns:
        True if operation can execute on unsupported page, False otherwise

    Examples:
        >>> is_operation_page_agnostic("Action", "GoBack to previous page")
        True
        >>> is_operation_page_agnostic("Action", "Tap on element 123")
        False
        >>> is_operation_page_agnostic("UX_Verify", "Check page content")
        True
    """

    # Priority 1: Direct action type detection (most reliable)
    # Check if instruction contains action type names directly
    for action_type in [ActionType.GO_BACK, ActionType.SLEEP]:
        if action_type in instruction:
            logger.debug(
                f'Page-agnostic action detected via action type: {action_type}'
            )
            return True

    # Priority 2: Keyword matching (handles varied phrasings)
    # Get centralized keywords from action_types module
    # This eliminates code duplication and ensures consistency
    page_agnostic_keywords = get_page_agnostic_keywords()

    # Category C: Hybrid operations (available in degraded mode)
    degraded_mode_types = ['UX_Verify']

    # Check step type - UX_Verify is verified to work on PDF pages (uses screenshot analysis)
    if step_type in degraded_mode_types:
        return True

    # Check keywords in instruction
    instruction_lower = instruction.lower().replace('_', ' ').replace('-', ' ')
    for keyword in page_agnostic_keywords:
        if keyword in instruction_lower:
            logger.debug(f"Page-agnostic operation detected via keyword: '{keyword}'")
            return True

    # Default: DOM-dependent operation (needs to abort)
    return False


# ---------------------------------------------------------------------------
# Critical failure detection
# ---------------------------------------------------------------------------

def is_critical_failure_step(tool_output: str, intermediate_output: str = '') -> bool:
    """Check if tool output or intermediate output contains [CRITICAL_ERROR:]
    tag."""
    if not tool_output and not intermediate_output:
        return False

    # Check both outputs for critical error tags
    if '[critical_error:' in tool_output.lower():
        logger.debug('Critical failure detected in tool_output')
        return True

    if '[critical_error:' in intermediate_output.lower():
        logger.debug('Critical failure detected in intermediate_output')
        return True

    return False


# ============================================================================
# Status Determination: LLM-first + Safety Guard helpers
# ============================================================================

_URL_PATTERN = re.compile(
    r'https?://[^\s]+|www\.[^\s]+|\.(?:com|org|net|edu|gov)\b',
)

_STATUS_PATTERN = re.compile(
    r'STATUS:\s*(passed|failed|warning|pass|fail|success|failure)\b',
    re.IGNORECASE,
)
_STATUS_NORMALIZE = {
    'passed': 'passed', 'pass': 'passed', 'success': 'passed',
    'failed': 'failed', 'fail': 'failed', 'failure': 'failed',
    'warning': 'warning',
}


def parse_llm_status(llm_output: str) -> Optional[str]:
    """Parse STATUS field from LLM output with tolerant regex + normalization.

    Supports common variants: passed/pass/success -> 'passed',
    failed/fail/failure -> 'failed', warning -> 'warning'.

    Returns:
        Normalized status string ('passed', 'failed', 'warning') or None if not found.
    """
    if not llm_output:
        return None
    match = _STATUS_PATTERN.search(llm_output)
    if match:
        return _STATUS_NORMALIZE.get(match.group(1).lower())
    return None


def derive_failure_type_from_outcomes(step_outcomes: list[StepOutcome]) -> str:
    """Derive failure_type from step outcomes for reflection skip decisions.

    Returns:
        'critical', 'product_defect', 'infrastructure', or 'recoverable'.
    """
    severities = _collect_severities(step_outcomes)
    if StepSeverity.CRITICAL in severities:
        return 'critical'
    if StepSeverity.HARD_FAIL in severities:
        return 'product_defect'
    if StepSeverity.SOFT_FAIL in severities:
        return 'infrastructure'
    return 'recoverable'


def apply_safety_guard(status: str, step_outcomes: list[StepOutcome]) -> str:
    """Prevent LLM from downplaying CRITICAL/HARD_FAIL severity.

    Rules:
    - CRITICAL exists -> must be 'failed' (any other status overridden)
    - HARD_FAIL exists -> must be 'failed' (passed/warning overridden)
    """
    severities = _collect_severities(step_outcomes)
    if StepSeverity.CRITICAL in severities and status != 'failed':
        logger.warning(
            f"Safety guard: CRITICAL exists, overriding '{status}' -> 'failed'"
        )
        return 'failed'
    if StepSeverity.HARD_FAIL in severities and status != 'failed':
        logger.warning(
            f"Safety guard: HARD_FAIL exists, overriding '{status}' -> 'failed'"
        )
        return 'failed'
    return status


def verdict_fallback(
    step_outcomes: list[StepOutcome],
    warning_steps: list[int],
    objective_achieved: bool,
) -> tuple[str, Optional[str]]:
    """Deterministic fallback when LLM STATUS is missing.

    Returns:
        (status, failure_type) tuple.
    """
    severities = _collect_severities(step_outcomes)
    if StepSeverity.CRITICAL in severities:
        return ('failed', 'critical')
    if StepSeverity.HARD_FAIL in severities:
        return ('failed', 'product_defect')
    if objective_achieved:
        return ('passed', None)
    if StepSeverity.SOFT_FAIL in severities:
        return ('failed', 'infrastructure')
    if warning_steps:
        return ('warning', None)
    return ('passed', None)


# ---------------------------------------------------------------------------
# Failed step detail extraction
# ---------------------------------------------------------------------------

def extract_failed_step_details(
    recorded_data: Optional[dict[str, Any]]
) -> list[dict[str, Any]]:
    """Extract detailed information about failed steps from recorded case data.

    This provides detailed failure context for the reflection phase to make
    better REPLAN decisions without requiring additional file I/O.

    Args:
        recorded_data: The recorded case data from CentralCaseRecorder.get_case_data()

    Returns:
        List of failed step details, each containing:
        - step_id: Step identifier
        - description: What the step was trying to do
        - status: The failure status (failed/error/failure)
        - type: Step type (action/verify/ux_verify)
    """
    if not recorded_data:
        return []

    steps = recorded_data.get('steps', [])
    failed_details: list[dict[str, Any]] = []

    for step in steps:
        status = (step.get('status') or '').lower()
        if status in ('failed', 'error', 'failure'):
            failed_details.append(
                {
                    'step_id': step.get('id'),
                    'description': step.get('description', ''),
                    'status': step.get('status'),
                    'type': step.get('type', 'action'),
                }
            )

    return failed_details


# ---------------------------------------------------------------------------
# Navigation and provider detection
# ---------------------------------------------------------------------------

def is_navigation_instruction(instruction: str) -> bool:
    """Determine if the instruction is a navigation instruction.

    Args:
        instruction: Instruction text to check

    Returns:
        bool: True if it's a navigation instruction, False otherwise
    """
    if not instruction:
        return False

    # Navigation keywords list (including both English and Chinese for compatibility)
    navigation_keywords = [
        'navigate',
        'go to',
        'open',
        'visit',
        'browse',
        'load',
        'access',
        'enter',
        'launch',
        '导航',  # navigate (Chinese)
        '打开',  # open (Chinese)
        '访问',  # visit (Chinese)
        '跳转',  # jump to (Chinese)
        '前往',  # go to (Chinese)
    ]

    # Convert instruction to lowercase for matching
    instruction_lower = instruction.lower()

    # Check if it contains navigation keywords
    for keyword in navigation_keywords:
        if keyword in instruction_lower:
            return True

    # Check URL patterns
    if _URL_PATTERN.search(instruction_lower):
        return True

    return False


def detect_llm_provider(model_name: str) -> str:
    """Detect LLM provider based on model name for LangChain integration.

    Args:
        model_name: Model name from configuration

    Returns:
        str: 'anthropic' for Claude models, 'gemini' for Gemini models, 'openai' for GPT models
    """
    if not model_name:
        return 'openai'  # Default to OpenAI

    model_lower = model_name.lower()

    # Claude models (claude-3-*, claude-3.5-*, etc.)
    if model_lower.startswith('claude-'):
        return 'anthropic'

    # Google Gemini models (gemini-2.5-*, gemini-3-*, etc.)
    if model_lower.startswith('gemini-'):
        return 'gemini'

    # OpenAI models (gpt-*, o1-*, o3-*)
    if model_lower.startswith(('gpt-', 'o1-', 'o3-')):
        return 'openai'

    # Default to OpenAI for unknown models
    return 'openai'

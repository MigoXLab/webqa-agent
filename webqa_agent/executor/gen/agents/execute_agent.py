"""This module defines the agent worker node for the LangGraph-based UI testing
application.

The agent worker is responsible for executing a single test case.
"""

import asyncio
import copy
import datetime
import json
import logging
import re
from typing import Any, Dict, List, Optional, Set, Tuple, Union

from langchain.agents import AgentExecutor, create_tool_calling_agent
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage
from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder
from langchain_openai import ChatOpenAI

# Anthropic LangChain support - optional dependency
try:
    from langchain_anthropic import ChatAnthropic

    LANGCHAIN_ANTHROPIC_AVAILABLE = True
except ImportError:
    LANGCHAIN_ANTHROPIC_AVAILABLE = False
    ChatAnthropic = None  # Type placeholder

from webqa_agent.actions.action_types import (ActionType,
                                              get_page_agnostic_keywords)
from webqa_agent.crawler.deep_crawler import DeepCrawler
from webqa_agent.data.gen_structures import StepOutcome, StepSeverity
from webqa_agent.executor.gen.utils.case_recorder import CentralCaseRecorder
from webqa_agent.executor.gen.utils.error_classifier import (
    get_system_error_summary, is_system_error)
from webqa_agent.executor.gen.utils.message_converter import \
    convert_intermediate_steps_to_messages
from webqa_agent.executor.gen.utils.summary_utils import (i18n_select,
                                                          make_user_summary)
from webqa_agent.llm.llm_api import EXTENDED_THINKING_EFFORT_MAPPING
from webqa_agent.prompts.agent_execution_prompts import \
    get_execute_system_prompt
from webqa_agent.prompts.test_planning_prompts import \
    get_dynamic_step_generation_prompt
from webqa_agent.tools.action_tool import UITool
from webqa_agent.tools.base import ActionTypes
from webqa_agent.tools.registry import get_registry
from webqa_agent.tools.ux_tool import UIUXViewportTool
from webqa_agent.tools.verify_tool import UIAssertTool
from webqa_agent.utils.log_icon import icon

LONG_STEPS = 30
RETRY_STABILIZATION_DELAY = 1.0
MIN_RECOVERY_CONFIDENCE = 0.7


# ============================================================================
# Tool Registry Helper Functions
# ============================================================================


def _get_tools(
    ui_tester_instance, llm_config, case_recorder, enabled_custom_tools=None
):
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
    logging.debug(f'Core tools instantiated: {[t.name for t in core_tools]}')

    # Try to load custom tools from registry (filtered by enabled_custom_tools)
    custom_tools = []
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
                    logging.debug(
                        f'Custom tools loaded from registry: {[t.name for t in custom_tools]}'
                    )
                elif enabled_custom_tools:
                    logging.debug(
                        f'No custom tools loaded (enabled: {enabled_custom_tools})'
                    )
    except Exception as e:
        logging.warning(
            f'Registry loading failed, continuing with core tools only: {e}'
        )

    # Return combined list: core tools + custom tools
    all_tools = core_tools + custom_tools
    logging.debug(f'Total tools available: {[t.name for t in all_tools]}')
    return all_tools


# ============================================================================
# Dynamic Step Generation Configuration Helper
# ============================================================================


def _get_dynamic_config(state: dict) -> dict:
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


def _parse_step_type(step: dict) -> str:
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
        logging.debug(f'Custom step type detected: {step_type}')
        return step_type
    else:
        # Fallback to Assertion for unknown step formats
        logging.warning(f'Unknown step format, defaulting to Assertion: {step}')
        return 'Assertion'


# ============================================================================
# Dynamic Step Generation Helper Functions
# ============================================================================


def normalize_url(u):
    """Normalize URL for comparison by removing www prefix and standardizing
    paths.

    Args:
        u: URL string to normalize

    Returns:
        Normalized URL string
    """
    from urllib.parse import urlparse

    try:
        parsed = urlparse(u)
        # Handle domain variations: remove www prefix, unify to lowercase
        netloc = parsed.netloc.lower()
        if netloc.startswith('www.'):
            netloc = netloc[4:]  # Remove www.

        # Standardize path: remove trailing slash
        path = parsed.path.rstrip('/')

        # Build standardized URL
        normalized = f'{parsed.scheme}://{netloc}{path}'
        return normalized
    except Exception:
        # If parsing fails, return lowercase form of original URL
        return u.lower()


def extract_domain(u):
    """Extract normalized domain from URL.

    Args:
        u: URL string

    Returns:
        Normalized domain string (lowercase, www removed)
    """
    try:
        from urllib.parse import urlparse

        parsed = urlparse(u)
        domain = parsed.netloc.lower()
        if domain.startswith('www.'):
            domain = domain[4:]
        return domain
    except Exception:
        return ''


def extract_path(u):
    """Extract normalized path from URL.

    Args:
        u: URL string

    Returns:
        Path string with trailing slash removed
    """
    try:
        from urllib.parse import urlparse

        parsed = urlparse(u)
        return parsed.path.rstrip('/')
    except Exception:
        return ''


def extract_json_from_response(response_text: str) -> str:
    """Extract JSON content from markdown-formatted or plain text response.

    Args:
        response_text: Raw response text from LLM that may contain JSON in markdown blocks

    Returns:
        Extracted JSON string ready for parsing
    """
    if not response_text:
        return ''

    # Check for ```json...``` pattern
    json_match = re.search(r'```json\s*(.*?)\s*```', response_text, re.DOTALL)
    if json_match:
        return json_match.group(1).strip()

    # Check for ```...``` without json marker
    code_match = re.search(r'```\s*(.*?)\s*```', response_text, re.DOTALL)
    if code_match:
        potential_json = code_match.group(1).strip()
        # Basic check if it looks like JSON
        if potential_json.startswith(('[', '{')):
            return potential_json

    # Return as-is if no code blocks found
    return response_text.strip()


def extract_text_content(content: Union[str, list, None]) -> str:
    """Extract plain text content from AIMessage or ToolMessage content field.

    Handles provider-specific format differences:
    - ChatOpenAI: content is typically a string
    - ChatAnthropic: content is a list containing {'type': 'text', 'text': '...'} blocks
    - Others: None or other formats

    Args:
        content: AIMessage.content or ToolMessage.content

    Returns:
        str: Extracted plain text content, or empty string if extraction fails

    Examples:
        >>> extract_text_content("Hello")
        'Hello'

        >>> extract_text_content([{'type': 'text', 'text': 'Hello'}, {'type': 'tool_use', ...}])
        'Hello'

        >>> extract_text_content(None)
        ''
    """
    # Case 1: Already a string (OpenAI traditional format)
    if isinstance(content, str):
        return content

    # Case 2: None or empty value
    if content is None:
        return ''

    # Case 3: List format (Anthropic format or OpenAI new format)
    if isinstance(content, list):
        text_parts = []
        for block in content:
            # Handle dictionary-formatted blocks
            if isinstance(block, dict):
                # Anthropic format: {'type': 'text', 'text': '...'}
                if block.get('type') == 'text' and 'text' in block:
                    text_parts.append(block['text'])
                # Some providers might use 'content' key directly
                elif 'content' in block:
                    text_parts.append(str(block['content']))
                # Direct 'text' key without type
                elif 'text' in block:
                    text_parts.append(block['text'])
            # Handle string elements (some edge cases)
            elif isinstance(block, str):
                text_parts.append(block)

        return '\n'.join(text_parts)

    # Case 4: Other types (convert to string)
    try:
        return str(content)
    except Exception:
        logging.warning(f'Failed to extract text from content type: {type(content)}')
        return ''


def safe_get_intermediate_step(
    result: dict, index: int = 0, subindex: int = 1, default: str = ''
) -> str:
    """Safely extract intermediate_steps observation from AgentExecutor result.

    Modified to use extract_text_content for provider compatibility:
    - Original version directly returned step[subindex], which could be a list (Anthropic) or string (OpenAI)
    - Now uses extract_text_content to ensure consistent string output

    Args:
        result: Return value from AgentExecutor.ainvoke()
        index: Index of intermediate_steps (default: 0, i.e., first step)
        subindex: Index within step tuple (default: 1, i.e., observation part)
        default: Default value if extraction fails

    Returns:
        str: Extracted observation text, guaranteed to be a string
    """
    steps = result.get('intermediate_steps', [])
    if isinstance(steps, list) and len(steps) > index:
        step = steps[index]
        if isinstance(step, (list, tuple)) and len(step) > subindex:
            observation = step[subindex]
            # Use extract_text_content to ensure string output
            return extract_text_content(observation)
    return default


def extract_dom_diff_from_output(tool_output: str) -> dict:
    """Extract DOM diff information from tool output."""
    try:
        # Find DOM_DIFF_DETECTED marker (case-insensitive)
        if 'dom_diff_detected:' not in tool_output.lower():
            return {}

        # Extract JSON portion (case-insensitive search)
        tool_output_lower = tool_output.lower()
        marker_idx = tool_output_lower.find('dom_diff_detected:')
        start_idx = marker_idx + len('dom_diff_detected:')
        # Find next line or end of text
        end_idx = tool_output.find('\n\n', start_idx)
        if end_idx == -1:
            json_str = tool_output[start_idx:].strip()
        else:
            json_str = tool_output[start_idx:end_idx].strip()

        return json.loads(json_str)
    except Exception as e:
        logging.debug(f'Failed to extract DOM diff from tool output: {e}')
        return {}


def format_elements_for_llm(dom_diff: dict) -> list[dict]:
    """Format DOM diff information, extracting key information for LLM
    understanding."""
    formatted = []
    for elem_id, elem_data in dom_diff.items():
        # Get key element information
        tag_name = elem_data.get('tagName', '').lower()
        inner_text = elem_data.get('innerText', '')
        attributes = elem_data.get('attributes', {})

        # Build simplified element description
        formatted_elem = {
            'id': elem_id,
            'type': tag_name,
            'text': inner_text[:100] if inner_text else '',  # Limit text length
            'position': {
                'x': elem_data.get('center_x'),
                'y': elem_data.get('center_y'),
            },
        }

        # Add important attribute information
        important_attrs = {}
        if attributes:
            # Define comprehensive attribute whitelist
            navigation_attrs = ['href', 'target', 'rel', 'download']
            form_attrs = [
                'type',
                'placeholder',
                'value',
                'name',
                'required',
                'disabled',
            ]
            semantic_attrs = ['role', 'aria-label', 'aria-describedby', 'aria-expanded']

            for key, value in attributes.items():
                # Include whitelisted attributes
                if (
                    key
                    in ['class', 'id'] + navigation_attrs + form_attrs + semantic_attrs
                ):
                    important_attrs[key] = value
                # Include data-* attributes (often contain behavior info)
                elif key.startswith('data-'):
                    # Limit length to prevent token explosion
                    important_attrs[key] = (
                        value[:200]
                        if isinstance(value, str) and len(value) > 200
                        else value
                    )
                # Include style if it indicates visibility/interactivity
                elif (
                    key == 'style'
                    and isinstance(value, str)
                    and ('display' in value or 'visibility' in value)
                ):
                    important_attrs[key] = (
                        value[:200] + '...' if len(value) > 200 else value
                    )

        if important_attrs:
            formatted_elem['attributes'] = important_attrs

        formatted.append(formatted_elem)

    return formatted


async def generate_dynamic_steps_with_llm(
    dom_diff: dict = None,
    last_action: str = '',
    test_objective: str = '',
    executed_steps: int = 0,
    max_steps: int = 8,
    llm: any = None,
    current_case: dict = None,
    screenshot: str = None,
    tool_output: str = None,
    step_success: bool = True,
    # New parameters for failure recovery mode
    failure_recovery_mode: bool = False,
    failed_instruction: str = '',
    error_message: str = '',
) -> dict:
    """Generate dynamic test steps or recover from failed steps using LLM.

    This function operates in two distinct modes:
    1. DOM Change Mode (failure_recovery_mode=False):
       Automatically generates test steps when new UI elements appear (dropdowns, modals, forms)
       to improve test coverage of dynamically revealed components.

    2. Failure Recovery Mode (failure_recovery_mode=True):
       Intelligently adapts the test plan when steps fail (element not found, operation timeout, etc.)
       by analyzing the failure and generating alternative instructions.

    Args:
        dom_diff: New DOM elements detected (used in DOM change mode)
        last_action: The action that triggered the new elements
        test_objective: Overall test objective
        executed_steps: Number of steps executed so far
        max_steps: Maximum number of steps to generate
        llm: LLM instance for generation
        current_case: Complete test case containing all steps for context
        screenshot: Base64 screenshot of current page state for visual context
        tool_output: Output from the tool execution for context (optional)
        step_success: Whether the previous step executed successfully (default: True)
        failure_recovery_mode: If True, operate in failure recovery mode instead of DOM change mode
        failed_instruction: The instruction that failed (used in failure recovery mode)
        error_message: The error message from the failed step (used in failure recovery mode)

    Returns:
        Dict containing strategy and generated test steps
        DOM Change Mode: {"strategy": "insert|replace", "reason": "...", "steps": [...]}
        Failure Recovery Mode: {"strategy": "retry_modified|skip|abort", "reason": "...", "steps": [...], "confidence": 0.0-1.0}
    """

    # === FAILURE RECOVERY MODE ===
    if failure_recovery_mode:
        if not failed_instruction or not error_message:
            return {
                'strategy': 'abort',
                'reason': 'Missing failure context',
                'steps': [],
                'confidence': 0.0,
            }

        try:
            # Build failure recovery prompt
            all_steps = current_case.get('steps', []) if current_case else []
            remaining_steps = (
                all_steps[executed_steps:] if executed_steps < len(all_steps) else []
            )
            executed_steps_detail = (
                all_steps[:executed_steps] if executed_steps > 0 else []
            )

            failure_prompt = f"""## Test Step Failure Recovery Analysis

**Failed Step**: {executed_steps}/{len(all_steps)}
**Failed Instruction**: {failed_instruction}
**Error Message**: {error_message}

**Test Context**:
- Test Name: {current_case.get('name', 'Unknown') if current_case else 'Unknown'}
- Test Objective: {test_objective}
- Remaining Steps: {len(remaining_steps)}

**Executed Steps History** (for context):
{json.dumps(executed_steps_detail, ensure_ascii=False, indent=2) if executed_steps_detail else "None - This is the first step"}

**Current Page State**:
The screenshot shows the current UI state after the failure occurred.

## Task

Analyze why this step failed and determine the best recovery strategy:

### Strategy Options:

1. **retry_modified**: The element likely exists but with different characteristics. Suggest an alternative instruction that targets similar functionality using elements visible in the current page.

2. **skip**: The step is non-critical or the functionality has already been achieved/tested in previous steps. Skipping won't impact test validity.

3. **abort**: The step is critical to the test objective and cannot be achieved with current page state. Continuing would produce invalid results.

## Decision Guidelines:

- If remaining steps depend on this step's outcome, avoid "skip"
- If error indicates fundamental issues (page crashed, wrong page), choose "abort"
- If alternative elements with similar function exist, choose "retry_modified"
- If functionality was already tested in earlier steps, choose "skip"
"""

            # Get available action types including custom tools for recovery suggestions
            action_types_str = ActionTypes.get_prompt_string()

            failure_prompt += f"""

## Available Action Types for Recovery

You can suggest alternative steps using any of these action types:

{action_types_str}

**Recovery Considerations**:
- Use core UI actions (Tap, Input, Scroll) for alternative interaction paths
- Consider custom tools if they could diagnose issues or verify system state
- Provide exactly ONE alternative step that addresses the root cause
- Ensure the alternative step is contextually appropriate for the current page state

## Response Format (JSON only):

```json
{{
  "strategy": "retry_modified|skip|abort",
  "steps": [{{"action": "alternative instruction"}}],
  "reason": "detailed explanation of why this strategy was chosen",
  "confidence": 0.85
}}
```

**CRITICAL - Single-Step Enforcement (MUST FOLLOW)**:

## Strategy Decision Tree
Use this logic to select strategy:
1. Can the error be resolved by modifying the instruction?
   → YES: Use `retry_modified` with ONE alternative step
   → NO: Go to step 2
2. Is the failed step essential for the test objective?
   → YES: Use `abort` (test cannot continue meaningfully)
   → NO: Use `skip` (non-critical step can be bypassed)

## Strict Output Rules

### For `retry_modified`:
- **MUST**: Generate EXACTLY ONE step in the `steps` array
- **FORBIDDEN**: Multiple steps, setup steps, cleanup steps
- **Focus**: Single actionable alternative that directly addresses the error
- **If multiple steps needed**: Choose the SINGLE most critical step only

### For `skip` or `abort`:
- **MUST**: Set `steps` to empty array `[]`
- **FORBIDDEN**: Including any steps

### Confidence Threshold:
- Range: 0.0 to 1.0
- **WARNING**: If confidence < 0.7, system **WILL FORCE** abort for safety
  (Not "may" - this is deterministic behavior)

## Example Responses

✅ Valid retry_modified:
```json
{{"strategy": "retry_modified", "steps": [{{"action": "Click the modal close button instead of using browser back"}}], "reason": "GoBack failed because modal doesn't add browser history. Close button is the correct approach.", "confidence": 0.85}}
```

❌ Invalid (multiple steps - FORBIDDEN):
```json
{{"strategy": "retry_modified", "steps": [{{"action": "Wait 2 seconds"}}, {{"action": "Click close button"}}], ...}}
```

## Self-Validation Checklist (before responding):
□ Is steps array length exactly 1 for retry_modified?
□ Is steps array empty for skip/abort?
□ Is confidence realistic (not always 0.9)?
□ Does reason explain the root cause?
"""

            # Call LLM with multi-modal context
            if screenshot:
                messages = [
                    {
                        'role': 'system',
                        'content': 'You are a QA expert analyzing test step failures. Respond with JSON only.',
                    },
                    {
                        'role': 'user',
                        'content': [
                            {'type': 'text', 'text': failure_prompt},
                            {
                                'type': 'image_url',
                                'image_url': {'url': screenshot, 'detail': 'low'},
                            },
                        ],
                    },
                ]
            else:
                messages = [
                    {
                        'role': 'system',
                        'content': 'You are a QA expert analyzing test step failures. Respond with JSON only.',
                    },
                    {'role': 'user', 'content': failure_prompt},
                ]

            response = await llm.ainvoke(messages)
            response_text = (
                response.content if hasattr(response, 'content') else str(response)
            )

            # Parse JSON response
            try:
                json_content = extract_json_from_response(response_text)
                result = json.loads(json_content)

                # Validate response
                if not isinstance(result, dict) or 'strategy' not in result:
                    logging.error("LLM response missing required 'strategy' field")
                    return {
                        'strategy': 'abort',
                        'reason': 'Invalid LLM response format',
                        'steps': [],
                        'confidence': 0.0,
                    }

                strategy = result.get('strategy')
                if strategy not in ['retry_modified', 'skip', 'abort']:
                    logging.error(f"Invalid strategy '{strategy}', defaulting to abort")
                    return {
                        'strategy': 'abort',
                        'reason': f'Invalid strategy returned: {strategy}',
                        'steps': [],
                        'confidence': 0.0,
                    }

                # Validate confidence
                confidence = result.get('confidence', 0.5)
                if (
                    not isinstance(confidence, (int, float))
                    or confidence < 0
                    or confidence > 1
                ):
                    logging.warning(
                        f'Invalid confidence {confidence}, defaulting to 0.5'
                    )
                    confidence = 0.5

                # Safety check: low confidence should abort
                if confidence < MIN_RECOVERY_CONFIDENCE:
                    logging.warning(
                        f'Low confidence ({confidence}) in recovery strategy, overriding to abort'
                    )
                    return {
                        'strategy': 'abort',
                        'reason': f"Low confidence in recovery. Original suggestion: {result.get('reason', 'N/A')}",
                        'steps': [],
                        'confidence': confidence,
                    }

                # Validate steps for retry_modified
                if strategy == 'retry_modified':
                    steps = result.get('steps', [])
                    if not steps or not isinstance(steps, list) or len(steps) == 0:
                        logging.error('retry_modified strategy missing valid steps')
                        return {
                            'strategy': 'abort',
                            'reason': 'retry_modified requires new instruction',
                            'steps': [],
                            'confidence': 0.0,
                        }

                    # Warn if LLM returns multiple steps (only first will be used)
                    if len(steps) > 1:
                        logging.warning(
                            f'[RECOVERY] LLM returned {len(steps)} steps for retry_modified, '
                            f'but only the first step will be used. Consider reviewing prompt constraints.'
                        )

                    # Validate step format
                    valid_step = (
                        steps[0]
                        if (
                            isinstance(steps[0], dict)
                            and ('action' in steps[0] or 'verify' in steps[0])
                        )
                        else None
                    )
                    if not valid_step:
                        logging.error('retry_modified step has invalid format')
                        return {
                            'strategy': 'abort',
                            'reason': 'Invalid step format in retry_modified',
                            'steps': [],
                            'confidence': 0.0,
                        }

                logging.info(
                    f'Failure recovery strategy: {strategy} (confidence: {confidence:.2f})'
                )
                logging.debug(f"Recovery reason: {result.get('reason', 'N/A')}")

                return {
                    'strategy': strategy,
                    'reason': result.get('reason', 'No reason provided'),
                    'steps': result.get('steps', []),
                    'confidence': confidence,
                }

            except json.JSONDecodeError as e:
                logging.error(f'Failed to parse failure recovery LLM response: {e}')
                return {
                    'strategy': 'abort',
                    'reason': 'JSON parsing failed',
                    'steps': [],
                    'confidence': 0.0,
                }

        except Exception as e:
            logging.error(f'Error in failure recovery mode: {e}')
            return {
                'strategy': 'abort',
                'reason': f'Recovery failed: {str(e)}',
                'steps': [],
                'confidence': 0.0,
            }

    # === DOM CHANGE MODE (Original Logic) ===
    if not dom_diff:
        return {'strategy': 'insert', 'reason': 'No new elements detected', 'steps': []}

    try:
        # Prepare new element information
        new_elements = format_elements_for_llm(dom_diff)

        if not new_elements:
            return {
                'strategy': 'insert',
                'reason': 'No meaningful elements to test',
                'steps': [],
            }

        # Build system prompt
        system_prompt = get_dynamic_step_generation_prompt()

        # Prepare test case context for better coherence
        test_case_context = ''
        if current_case and 'steps' in current_case:
            all_steps = current_case['steps']
            executed_steps_detail = (
                all_steps[:executed_steps] if executed_steps > 0 else []
            )
            remaining_steps = (
                all_steps[executed_steps:] if executed_steps < len(all_steps) else []
            )

            test_case_context = f"""
Test Case Context:
- Test Case Name: {current_case.get('name', 'Unnamed')}
- Test Objective: {current_case.get('objective', test_objective)}
- Total Steps in Test: {len(all_steps)}
- Current Position: Step {executed_steps}/{len(all_steps)}

Executed Steps (for context):
{json.dumps(executed_steps_detail, ensure_ascii=False, indent=2) if executed_steps_detail else "None"}

Remaining Steps (may need adjustment after replan):
{json.dumps(remaining_steps, ensure_ascii=False, indent=2) if remaining_steps else "None"}
"""

        # Build multi-modal user prompt with dynamic status context
        visual_context_section = ''
        if screenshot:
            execution_context = (
                'AFTER the execution of the last action'
                if step_success
                else 'AFTER the attempted execution of the last action'
            )
            visual_context_section = f"""
## Current Page Visual Context
The attached screenshot shows the current state of the page {execution_context}.
Use this visual information along with the DOM diff to understand the complete UI state.
"""

        # Build context based on actual execution result
        if step_success:
            action_status = f'✅ SUCCESSFULLY EXECUTED: "{last_action}"'
            status_context = 'The above action has been completed successfully. Do NOT re-plan or duplicate this action.'
            execution_description = 'After the successful action execution'
        else:
            action_status = f'⚠️ FAILED/PARTIAL EXECUTION: "{last_action}"'
            status_context = 'The above action failed or partially succeeded. Consider recovery steps or alternative approaches.'
            execution_description = 'After the failed/partial action execution'

        # Include tool output for better context
        tool_output_section = ''
        if tool_output:
            # Truncate if too long to prevent prompt overflow
            tool_output_section = f"""

## Execution Details
{tool_output}
"""

        user_prompt = f"""
## Previous Action Status
{action_status}
{status_context}{tool_output_section}

## New UI Elements Detected
{execution_description}, {len(new_elements)} new UI elements appeared:
{json.dumps(new_elements, ensure_ascii=False, indent=2)}

{visual_context_section}

{test_case_context}

## Analysis Context
Max steps to generate: {max_steps}
Test Objective: "{test_objective}"

Please analyze these new UI elements using the QAG methodology and generate appropriate test steps if needed.
        """

        logging.debug(
            f'Requesting LLM to generate dynamic steps for {len(new_elements)} new elements'
        )

        # Call LLM with proper message structure
        if screenshot:
            # Multi-modal call with screenshot
            messages = [
                {'role': 'system', 'content': system_prompt},
                {
                    'role': 'user',
                    'content': [
                        {'type': 'text', 'text': user_prompt},
                        {
                            'type': 'image_url',
                            'image_url': {'url': screenshot, 'detail': 'low'},
                        },
                    ],
                },
            ]
        else:
            # Text-only call with proper message structure
            messages = [
                {'role': 'system', 'content': system_prompt},
                {'role': 'user', 'content': user_prompt},
            ]

        response = await llm.ainvoke(messages)

        # Parse response
        if hasattr(response, 'content'):
            response_text = response.content
        else:
            response_text = str(response)

        # Try to parse JSON response using helper function
        try:
            # Extract JSON from markdown formatting
            json_content = extract_json_from_response(response_text)
            result = json.loads(json_content)

            # Validate response format
            if isinstance(result, dict) and 'strategy' in result and 'steps' in result:
                strategy = result.get('strategy', 'insert')
                reason = result.get('reason', 'No reason provided')
                steps = result.get('steps', [])

                # Extract and validate analysis fields (Enhanced QAG format)
                analysis = result.get('analysis', {})
                q1_can_complete_alone = (
                    analysis.get('q1_can_complete_alone', False)
                    if isinstance(analysis, dict)
                    else False
                )
                q2_different_aspects = (
                    analysis.get('q2_different_aspects', False)
                    if isinstance(analysis, dict)
                    else False
                )
                q3_remaining_redundant = (
                    analysis.get('q3_remaining_redundant', False)
                    if isinstance(analysis, dict)
                    else False
                )
                q4_abstraction_gap = (
                    analysis.get('q4_abstraction_gap', False)
                    if isinstance(analysis, dict)
                    else False
                )

                # Validate strategy value
                if strategy not in ['insert', 'replace']:
                    logging.warning(
                        f"Invalid strategy '{strategy}', defaulting to 'insert'"
                    )
                    strategy = 'insert'

                # Validate QAG analysis fields
                if not isinstance(q1_can_complete_alone, bool):
                    logging.debug(
                        f'Invalid q1_can_complete_alone {q1_can_complete_alone}, defaulting to False'
                    )
                    q1_can_complete_alone = False

                if not isinstance(q2_different_aspects, bool):
                    logging.debug(
                        f'Invalid q2_different_aspects {q2_different_aspects}, defaulting to False'
                    )
                    q2_different_aspects = False

                if not isinstance(q3_remaining_redundant, bool):
                    logging.debug(
                        f'Invalid q3_remaining_redundant {q3_remaining_redundant}, defaulting to False'
                    )
                    q3_remaining_redundant = False

                if not isinstance(q4_abstraction_gap, bool):
                    logging.debug(
                        f'Invalid q4_abstraction_gap {q4_abstraction_gap}, defaulting to False'
                    )
                    q4_abstraction_gap = False

                # Validate and limit step count
                valid_steps = []
                if isinstance(steps, list):
                    for step in steps[:max_steps]:
                        if isinstance(step, dict) and (
                            'action' in step or 'verify' in step
                        ):
                            valid_steps.append(step)

                # Enhanced logging with QAG analysis data
                logging.info(
                    f"Generated {len(valid_steps)} dynamic steps with strategy '{strategy}' from {len(new_elements)} new elements"
                )

                logging.debug(f'Strategy reason: {reason}')
                if analysis:
                    logging.debug(
                        f'Enhanced QAG Analysis: q1_can_complete_alone={q1_can_complete_alone}, q2_different_aspects={q2_different_aspects}, q3_remaining_redundant={q3_remaining_redundant}, q4_abstraction_gap={q4_abstraction_gap}'
                    )

                # Return enhanced result with QAG analysis
                result_data = {
                    'strategy': strategy,
                    'reason': reason,
                    'steps': valid_steps,
                }

                # Include Enhanced QAG analysis if provided
                if analysis:
                    result_data['analysis'] = {
                        'q1_can_complete_alone': q1_can_complete_alone,
                        'q2_different_aspects': q2_different_aspects,
                        'q3_remaining_redundant': q3_remaining_redundant,
                        'q4_abstraction_gap': q4_abstraction_gap,
                    }

                return result_data
            else:
                logging.warning(
                    'LLM response missing required fields (strategy, steps)'
                )
                return {
                    'strategy': 'insert',
                    'reason': 'Invalid response format',
                    'steps': [],
                }

        except json.JSONDecodeError as e:
            logging.warning(f'Failed to parse LLM response as JSON: {e}')
            logging.debug(f'Raw LLM response: {response_text[:500]}...')
            logging.debug(
                f'Extracted JSON content: {extract_json_from_response(response_text)[:500]}...'
            )
            return {'strategy': 'insert', 'reason': 'JSON parsing failed', 'steps': []}

    except Exception as e:
        logging.error(f'Error generating dynamic steps with LLM: {e}')
        return {
            'strategy': 'insert',
            'reason': f'Generation failed: {str(e)}',
            'steps': [],
        }


def _contains_failure_indicators(text: str) -> bool:
    """Check if text contains any failure indicators.

    Args:
        text: Tool output or intermediate output to check

    Returns:
        bool: True if any failure indicator is found
    """
    if not text:
        return False

    text_lower = text.lower()
    failure_tags = ['[failure]', '[critical_error:']
    return any(tag in text_lower for tag in failure_tags)


# The node function that will be used in the graph

def _i18n(language: str, zh: str, en: str) -> str:
    """Select language-appropriate string (shorthand for i18n_select)."""
    return i18n_select(language, zh, en)


def _make_final_summary(language: str, template_zh: str, template_en: str) -> str:
    """Select language-appropriate FINAL_SUMMARY string.

    Semantic alias for _i18n -- kept for readability at call sites that
    construct final_summary values.
    """
    return _i18n(language, template_zh, template_en)


def _make_user_summary(
    language: str,
    status: str,
    objective: str,
    reason: str = '',
) -> str:
    """Generate user-facing summary (shorthand for make_user_summary)."""
    return make_user_summary(language, status, objective, reason)


_USER_SUMMARY_PATTERN = re.compile(r'USER_SUMMARY:\s*(.+)', re.IGNORECASE)


def _parse_user_summary(llm_output: str) -> Optional[str]:
    """Extract USER_SUMMARY line from LLM output."""
    if not llm_output:
        return None
    match = _USER_SUMMARY_PATTERN.search(llm_output)
    return match.group(1).strip() if match else None


async def agent_worker_node(state: dict, config: dict) -> dict:
    """Dynamically creates and invokes the execution agent for a single test
    case.

    This node is mapped over the list of test cases.
    """
    case = state['test_case']
    case_name = case.get('name', 'Unnamed Test Case')
    completed_cases = state.get('completed_cases', [])

    logging.debug(f'=== Starting Agent Worker for Test Case: {case_name} ===')
    logging.debug(f"Test case objective: {case.get('objective', 'Not specified')}")
    logging.debug(f"Test case steps count: {len(case.get('steps', []))}")
    logging.debug(f"Preamble actions count: {len(case.get('preamble_actions', []))}")
    logging.debug(f'Previously completed cases: {len(completed_cases)}')

    ui_tester_instance = config['configurable']['ui_tester_instance']

    # Use externalized case recorder from graph.py (survives timeout),
    # or create locally as fallback for backward compatibility
    case_recorder = config.get('configurable', {}).get('case_recorder')
    if case_recorder is None:
        case_recorder = CentralCaseRecorder()
        case_recorder.start_case(case_name, case_data=case)

    # Expose recorder to UITester so it can record action/verify steps automatically
    ui_tester_instance.central_case_recorder = case_recorder

    # Deep-copy original steps BEFORE any execution or adaptive recovery
    # case_steps[i] = new_steps[0] modifies the list in-place, corrupting the original plan
    original_planned_steps = copy.deepcopy(case.get('steps', []))

    language = state.get('language', 'zh-CN')
    case_objective = case.get('objective', case_name)
    system_prompt_string = get_execute_system_prompt(case, language=language)
    logging.debug(
        f'Generated system prompt length: {len(system_prompt_string)} characters'
    )

    llm_config = ui_tester_instance.llm.llm_config

    logging.info(f"{icon['running']} Agent worker for test case started: {case_name}")

    # Detect provider based on model name for LangChain integration
    model_name = llm_config.get('model', 'gpt-4o-mini')
    provider = _detect_llm_provider(model_name)

    # Build LLM kwargs based on provider
    llm_kwargs = {
        'model': model_name,
        'api_key': llm_config.get('api_key'),
    }

    # Add base_url with provider-specific handling
    base_url = llm_config.get('base_url')
    if base_url:
        # OpenAI, Gemini, and Anthropic support base_url directly
        llm_kwargs['base_url'] = base_url
    else:
        # Set default base_url for Gemini if not explicitly configured
        if provider == 'gemini':
            llm_kwargs['base_url'] = (
                'https://generativelanguage.googleapis.com/v1beta/openai/'
            )
            logging.debug('Gemini using official OpenAI compatibility endpoint')

    # Add temperature with provider-specific defaults
    # Claude and Gemini default to 1.0, OpenAI defaults to 0.1
    if provider in ('anthropic', 'gemini'):
        default_temp = 1.0
    else:
        default_temp = 0.1
    cfg_temp = llm_config.get('temperature', default_temp)
    llm_kwargs['temperature'] = cfg_temp

    # Add top_p if specified
    cfg_top_p = llm_config.get('top_p')
    if cfg_top_p is not None:
        llm_kwargs['top_p'] = cfg_top_p

    # Add max_tokens if specified (with provider-specific defaults)
    # Claude and Gemini default to 4096, OpenAI defaults to 4096
    cfg_max_tokens = llm_config.get('max_tokens', 4096)
    llm_kwargs['max_tokens'] = cfg_max_tokens

    # For Claude: Maps reasoning.effort → thinking.budget_tokens
    # Claude uses Extended Thinking API with token budgets (1K-20K tokens)
    # This is Claude-specific: thinking={"type": "enabled", "budget_tokens": N}
    # Ref: https://docs.anthropic.com/en/docs/build-with-claude/extended-thinking
    if provider == 'anthropic':
        reasoning_config = llm_config.get('reasoning')
        if isinstance(reasoning_config, dict):
            effort = reasoning_config.get('effort')
            if effort:
                # Use shared effort mapping constant for Extended Thinking configuration
                # Format: {"type": "enabled", "budget_tokens": N}
                budget = EXTENDED_THINKING_EFFORT_MAPPING.get(effort.lower())
                if budget:
                    # Validate: budget_tokens must be < max_tokens (Anthropic API requirement)
                    if budget >= cfg_max_tokens:
                        recommended_max = int(
                            budget / 0.5
                        )  # 50% ratio as middle ground
                        logging.warning(
                            f'Extended Thinking: budget_tokens ({budget}) >= max_tokens ({cfg_max_tokens}). '
                            f'Auto-adjusting budget to {cfg_max_tokens - 1}. '
                            f'Recommended: Set max_tokens={recommended_max} for effort={effort}'
                        )
                        budget = cfg_max_tokens - 1

                    llm_kwargs['thinking'] = {
                        'type': 'enabled',
                        'budget_tokens': budget,
                    }
                    logging.debug(
                        f'Claude thinking enabled with budget_tokens={budget} based on effort={effort}'
                    )

    # For OpenAI and Gemini: Maps reasoning.effort → reasoning_effort parameter
    # Both providers use OpenAI SDK format but with different implementations:
    # - OpenAI: Native reasoning models (o1, o3) with built-in reasoning
    # - Gemini: OpenAI compatibility layer (generativelanguage.googleapis.com/v1beta/openai/)
    # Ref: https://ai.google.dev/gemini-api/docs/openai (Gemini OpenAI compatibility)
    if provider in ('openai', 'gemini'):
        reasoning_config = llm_config.get('reasoning')
        if isinstance(reasoning_config, dict):
            effort = reasoning_config.get('effort')
            if effort:
                # Map effort to reasoning_effort for ChatOpenAI (OpenAI/Gemini compatible)
                # OpenAI o1/o3 and Gemini 2.5/3.x support: low, medium, high
                # We map 'minimal' → 'low' since OpenAI doesn't support 'minimal'
                effort_mapping = {
                    'minimal': 'low',  # Map minimal to low (OpenAI doesn't have 'minimal')
                    'low': 'low',
                    'medium': 'medium',
                    'high': 'high',
                }
                reasoning_effort = effort_mapping.get(effort.lower())
                if reasoning_effort:
                    # Use model_kwargs for ChatOpenAI extra parameters
                    if 'model_kwargs' not in llm_kwargs:
                        llm_kwargs['model_kwargs'] = {}
                    llm_kwargs['model_kwargs']['reasoning_effort'] = reasoning_effort
                    logging.debug(
                        f'{provider.capitalize()} reasoning_effort set to {reasoning_effort} based on effort={effort}'
                    )

    # Add request timeout to prevent indefinite hangs during concurrent execution
    cfg_timeout = llm_config.get('timeout') or 360
    logging.debug(f'LLM request timeout set to {cfg_timeout}s')

    # Instantiate appropriate LangChain chat model
    if provider == 'anthropic':
        if not LANGCHAIN_ANTHROPIC_AVAILABLE:
            raise ImportError(
                f"Model '{model_name}' requires 'langchain-anthropic' package. "
                'Install with: pip install langchain-anthropic'
            )
        llm_kwargs['default_request_timeout'] = cfg_timeout
        llm = ChatAnthropic(**llm_kwargs)
        logging.debug('Using ChatAnthropic for LangChain integration')
    else:
        # OpenAI and Gemini models use ChatOpenAI (via OpenAI SDK)
        llm_kwargs['timeout'] = cfg_timeout
        llm = ChatOpenAI(**llm_kwargs)
        logging.debug(
            f'Using ChatOpenAI for LangChain integration (provider: {provider})'
        )

    logging.debug(
        f"LangGraph LLM params resolved: provider={provider}, model={llm_kwargs.get('model')}, "
        f"base_url={llm_kwargs.get('base_url', 'default')}, temperature={llm_kwargs.get('temperature')}, "
        f"top_p={llm_kwargs.get('top_p', 'unset')}"
    )
    logging.debug(
        f"LLM configured: {llm_config.get('model')} at {llm_config.get('base_url')}"
    )

    # Extract enabled_custom_tools from state (passed from GenExecutor via LangGraph)
    enabled_custom_tools = state.get('enabled_custom_tools', [])
    logging.debug(f'Enabled custom tools from config: {enabled_custom_tools}')

    # Instantiate tools via registry with custom tools filtering
    tools = _get_tools(
        ui_tester_instance, llm_config, case_recorder, enabled_custom_tools
    )
    logging.debug(f'Tools initialized: {[tool.name for tool in tools]}')

    # The prompt now includes the system message
    prompt = ChatPromptTemplate.from_messages(
        [
            ('system', system_prompt_string),
            MessagesPlaceholder(variable_name='messages'),
            MessagesPlaceholder(variable_name='agent_scratchpad'),
        ]
    )

    # Create the agent
    agent = create_tool_calling_agent(llm, tools, prompt)
    agent_executor = AgentExecutor(
        agent=agent,
        tools=tools,
        verbose=False,
        max_iterations=5,
        return_intermediate_steps=True,
    )
    logging.debug('AgentExecutor created successfully')

    # --- Execute Preamble Actions to Restore State ---
    preamble_actions = case.get('preamble_actions', [])
    if preamble_actions:
        logging.debug(f'=== Executing {len(preamble_actions)} Preamble Actions ===')
        preamble_messages: list[BaseMessage] = [
            HumanMessage(
                content='The test has started. Before the main test steps, I need to perform some setup actions to restore the UI state. Please execute the first preamble action.'
            )
        ]

        for i, step in enumerate(preamble_actions):
            if isinstance(step, dict):
                instruction_to_execute = step.get('action')
            else:
                instruction_to_execute = step
            if not instruction_to_execute:
                logging.warning(f'Preamble action {i + 1} has no instruction, skipping')
                continue

            # Smart check: Skip preamble action if it's a navigation instruction and already on target page
            if case.get('reset_session', False) and _is_navigation_instruction(
                instruction_to_execute
            ):
                # Check if already on target page
                try:
                    page = ui_tester_instance.browser_session.page
                    current_url = page.url
                    target_url = case.get('url', '')

                    # Use module-level URL helper functions
                    current_normalized = normalize_url(current_url)
                    target_normalized = normalize_url(target_url)

                    # Basic standardized matching
                    if current_normalized == target_normalized:
                        logging.debug(
                            'Skipping preamble navigation action - already on target page (normalized match)'
                        )
                        continue

                    # More flexible domain and path matching
                    current_domain = extract_domain(current_url)
                    target_domain = extract_domain(target_url)
                    current_path = extract_path(current_url)
                    target_path = extract_path(target_url)

                    if current_domain == target_domain and (
                        current_path == target_path
                        or current_path == ''
                        and target_path == ''
                        or current_path == '/'
                        and target_path == ''
                        or current_path == ''
                        and target_path == '/'
                    ):
                        logging.debug(
                            f'Skipping preamble navigation action - domain and path match detected ({current_domain}{current_path})'
                        )
                        continue

                except Exception as e:
                    logging.warning(
                        f'Could not check current URL for preamble action: {e}, proceeding with execution'
                    )

            logging.info(
                f'Executing preamble action {i + 1}/{len(preamble_actions)}: {instruction_to_execute}'
            )
            preamble_messages.append(
                HumanMessage(
                    content=f'Now, execute this preamble action: {instruction_to_execute}'
                )
            )

            try:
                # Use a simple invoke, as preamble steps should be straightforward
                logging.debug(f'Executing preamble action {i + 1} - Calling Agent...')
                start_time = datetime.datetime.now()

                result = await agent_executor.ainvoke({'messages': preamble_messages})

                preamble_messages = result.get('messages', preamble_messages)
                # AgentExecutor may not return messages, check for intermediate_steps instead
                if 'intermediate_steps' in result and result['intermediate_steps']:
                    # Convert intermediate steps to proper message format
                    intermediate_messages = convert_intermediate_steps_to_messages(
                        result['intermediate_steps']
                    )
                    preamble_messages.extend(intermediate_messages)

                end_time = datetime.datetime.now()
                duration = (end_time - start_time).total_seconds()

                # Get raw output (could be string or list depending on provider)
                raw_output = result.get('output', '')
                # Extract text content for string operations
                tool_output = extract_text_content(raw_output)
                logging.debug(
                    f'Preamble action {i + 1} completed in {duration:.2f} seconds'
                )
                logging.debug(f'Preamble action {i + 1} result: {tool_output[:200]}...')
                preamble_messages.append(AIMessage(content=tool_output))

                # Safely check for failure in intermediate steps
                intermediate_output = safe_get_intermediate_step(
                    result, index=0, subindex=1, default=''
                )
                # Check BOTH tool_output and intermediate_output for failures
                if _contains_failure_indicators(
                    intermediate_output
                ) or _contains_failure_indicators(tool_output):
                    final_summary = _i18n(language,
                                          f"前置动作 '{instruction_to_execute}' 失败，无法继续执行测试用例。错误：{tool_output}",
                                          f"Preamble action '{instruction_to_execute}' failed, cannot proceed with the test case. Error: {tool_output}")
                    user_summary = _make_user_summary(language, 'failed', case_objective,
                                                      _i18n(language,
                                                            f"前置操作'{instruction_to_execute}'失败，无法开始测试。",
                                                            f"Preamble action '{instruction_to_execute}' failed, test could not start."))
                    logging.error(f'Preamble action {i + 1} failed, aborting test case')
                    # Ensure time data is recorded even on early failure
                    case_recorder.finish_case(final_status='failed', final_summary=final_summary, user_summary=user_summary)
                    recorded_case_data = case_recorder.get_case_data()
                    if recorded_case_data is not None:
                        recorded_case_data['original_planned_steps'] = original_planned_steps
                    # Extract metrics for consistent case_result structure
                    metrics = recorded_case_data.get('metrics', {}) if recorded_case_data else {}
                    failed_step_details = _extract_failed_step_details(recorded_case_data)
                    case_result = {
                        'case_name': case_name,
                        'case_id': case.get('case_id', ''),
                        'final_summary': final_summary,
                        'user_summary': user_summary,
                        'status': 'failed',
                        'failure_type': 'preamble_failure',
                        'metrics': {
                            'total_steps': metrics.get('total_steps', 0),
                            'passed_steps': metrics.get('passed_steps', 0),
                            'failed_steps': metrics.get('failed_steps', 0),
                            'warning_steps': metrics.get('warning_steps', 0),
                            'total_actions': metrics.get('total_actions', 0),
                        },
                        'failed_step_details': failed_step_details,
                    }
                    return {
                        'case_result': case_result,
                        'current_case_steps': [],
                        'recorded_case': recorded_case_data,
                    }

                logging.debug(f'Preamble action {i + 1} completed successfully')
            except Exception as e:
                logging.error(f'Exception during preamble action {i + 1}: {str(e)}')
                if is_system_error(e):
                    logging.warning(
                        f'System error during preamble action {i + 1}: '
                        f'{type(e).__name__}: {e}'
                    )
                    final_summary = get_system_error_summary(e, language)
                    user_summary = _make_user_summary(language, 'warning', case_objective)
                    preamble_status = 'warning'
                    preamble_failure_type = 'system_error'
                else:
                    final_summary = _i18n(language,
                                          f"前置动作 '{instruction_to_execute}' 发生异常：{str(e)}",
                                          f"Preamble action '{instruction_to_execute}' raised exception: {str(e)}")
                    user_summary = _make_user_summary(language, 'failed', case_objective,
                                                      _i18n(language,
                                                            f"前置操作'{instruction_to_execute}'发生异常。",
                                                            f"Preamble action '{instruction_to_execute}' raised an exception."))
                    preamble_status = 'failed'
                    preamble_failure_type = 'preamble_exception'
                # Ensure time data is recorded even on exception
                case_recorder.finish_case(final_status=preamble_status, final_summary=final_summary, user_summary=user_summary)
                recorded_case_data = case_recorder.get_case_data()
                if recorded_case_data is not None:
                    recorded_case_data['original_planned_steps'] = original_planned_steps
                # Extract metrics for consistent case_result structure
                metrics = recorded_case_data.get('metrics', {}) if recorded_case_data else {}
                failed_step_details = _extract_failed_step_details(recorded_case_data)
                case_result = {
                    'case_name': case_name,
                    'case_id': case.get('case_id', ''),
                    'final_summary': final_summary,
                    'user_summary': user_summary,
                    'status': preamble_status,
                    'failure_type': preamble_failure_type,
                    'metrics': {
                        'total_steps': metrics.get('total_steps', 0),
                        'passed_steps': metrics.get('passed_steps', 0),
                        'failed_steps': metrics.get('failed_steps', 0),
                        'warning_steps': metrics.get('warning_steps', 0),
                        'total_actions': metrics.get('total_actions', 0),
                    },
                    'failed_step_details': failed_step_details,
                }
                return {
                    'case_result': case_result,
                    'current_case_steps': [],
                    'recorded_case': recorded_case_data,
                }

        logging.debug('=== All Preamble Actions Completed Successfully ===')

    # --- Main Execution Loop ---
    logging.debug('=== Starting Main Test Steps Execution ===')
    messages: list[BaseMessage] = [
        HumanMessage(
            content='The test has started. I will provide you with one instruction at a time. Please execute the action or assertion described in each instruction.'
        )
    ]
    final_summary = 'No summary provided.'
    user_summary = ''
    tool_output: str = ''  # Last step's output; used post-loop for USER_SUMMARY upgrade
    case_steps = case.get('steps', [])  # Get reference to steps list
    total_steps = len(case_steps)
    step_outcomes: List[StepOutcome] = []  # Structured step results for verdict engine
    objective_achieved = False       # Track objective achievement signal
    warning_steps = []  # Track steps with warnings (e.g., UX issues)
    code_determined_status: Optional[str] = None   # Set by break/abort paths
    code_failure_type: Optional[str] = None        # Set alongside code_determined_status

    def _get_failed_step_indices() -> List[int]:
        """Extract hard-failure step indices for summary generation (backward
        compat)."""
        return [o.step_index for o in step_outcomes
                if o.severity in (StepSeverity.CRITICAL, StepSeverity.HARD_FAIL)]
    case_modified = False  # Track if case was modified with dynamic steps
    dynamic_generation_count = 0  # Track how many times dynamic generation occurred
    dom_diff_cache = (
        []
    )  # Stores DOM diff history for debugging and analysis (not used for deduplication)
    step_retry_tracker = (
        {}
    )  # Track retry attempts per step for adaptive recovery (prevents infinite loops)

    # ===================================================================
    # State Machine Flow: Step-by-Step Test Execution Loop
    # ===================================================================
    # 1. Prepare Step (lines 1078-1102): Extract instruction, determine step type, format prompt
    # 2. Generate Multi-Modal Context (lines 1104-1114): Capture screenshot with highlighted DOM
    # 3. Create Message & Prune History (lines 1116-1148): Build agent input, optimize tokens
    # 4. Execute Step with Tool Choice Masking (lines 1150-1193): Force correct tool based on step type
    # 5. Critical Failure Check (lines 1203-1262): Abort test if unrecoverable error (Priority 0)
    # 6. Regular Failure Check & Recovery (lines 1264-1465): Attempt adaptive recovery (Priority 1)
    # 7. Check Objective Achievement (lines 1467-1471): Early termination if test goal met
    # 8. Dynamic Step Generation (lines 1475-1608): Generate steps for new UI elements (Actions only)
    # 9. Increment & Continue (line 1615): Move to next step unless retry/abort
    # ===================================================================

    # Cache custom tool names for unified format detection (outside loop for performance)
    registry = get_registry()
    custom_tool_names = set(registry.get_tool_names())

    # Build step_type → timeout mapping from tool metadata
    # Tools can declare step_timeout in their metadata (e.g. 600s for element traversal)
    step_timeout_map: Dict[str, float] = {}
    # Build step_type set for tools that disable adaptive recovery (batch/scan tools)
    recovery_disabled_step_types: Set[str] = set()
    try:
        for _tool_name in registry.get_tool_names():
            _meta = registry.get_metadata(_tool_name)
            if _meta and _meta.step_type:
                if _meta.step_timeout:
                    step_timeout_map[_meta.step_type] = _meta.step_timeout
                if _meta.recovery_disabled:
                    recovery_disabled_step_types.add(_meta.step_type)
    except Exception as exc:
        logging.warning(f'Failed to build step timeout/recovery maps from registry: {exc}')

    i = 0
    while i < len(case_steps):
        step = case_steps[i]

        # Parse step type (supports core fields and custom tool type field)
        step_type = _parse_step_type(step)

        # Handle unified format custom tools: {"action": "tool_name", "params": {...}}
        # Convert params to function call instruction for agent_executor
        action_value = step.get('action')
        if action_value and action_value in custom_tool_names:
            # Update step_type to the tool's actual step_type for correct timeout lookup.
            # Without this, step_type stays 'Action' and step_timeout_map always misses.
            _tool_meta = registry.get_metadata(action_value)
            if _tool_meta and _tool_meta.step_type:
                step_type = _tool_meta.step_type
            # Convert unified format to function call instruction
            params = step.get('params', {})
            param_str = ', '.join(f'{k}={v!r}' for k, v in params.items())
            instruction_to_execute = f'{action_value}({param_str})'
            logging.debug(
                f'Converted unified format custom tool to instruction: {instruction_to_execute}'
            )
        else:
            # Standard extraction (supports core fields and custom tool instruction field)
            instruction_to_execute = (
                step.get('action')
                or step.get('verify')
                or step.get('ux_verify')
                or step.get('instruction')  # Support custom tool instruction
            )

        logging.info(
            f'Executing Step {i + 1}/{total_steps} ({step_type}), step instruction: {instruction_to_execute}'
        )

        # Define instruction templates for variation
        instruction_templates = [
            'Now, execute this instruction: {instruction}',
            'Please proceed with the following step: {instruction}',
            'The next task is to perform this action: {instruction}',
            'Execute the instruction as follows: {instruction}',
        ]
        # Vary the instruction prompt to avoid repetitive context
        prompt_template = instruction_templates[i % len(instruction_templates)]
        formatted_instruction = prompt_template.format(
            instruction=instruction_to_execute
        )

        # --- Multi-Modal Context Generation ---
        page = ui_tester_instance.browser_session.page
        dp = DeepCrawler(page)
        await dp.crawl(highlight=True, viewport_only=True)
        screenshot, _ = await ui_tester_instance._actions.b64_page_screenshot(
            file_name=f'step_{i + 1}_vision', context='agent'
        )
        await dp.remove_marker()
        logging.debug('Generated highlighted screenshot for the agent.')
        # ------------------------------------

        # Create a new message with the current step's instruction and visual context
        step_content = [{'type': 'text', 'text': formatted_instruction}]
        if screenshot:
            step_content.append(
                {
                    'type': 'image_url',
                    'image_url': {'url': f'{screenshot}', 'detail': 'low'},
                }
            )
        step_message = HumanMessage(content=step_content)

        # The agent's history includes all prior messages
        current_messages = messages + [step_message]

        # --- History Pruning for Token Optimization ---
        # Keep the full text history but only the most recent image to save tokens.
        pruned_messages = []
        # The last message is the one we just added and should always keep its image.
        for j, msg in enumerate(current_messages):
            # Check if it's not the last message
            if (
                j < len(current_messages) - 1
                and isinstance(msg, HumanMessage)
                and isinstance(msg.content, list)
            ):
                # It's an older multi-modal message, prune the image.
                text_content = next(
                    (
                        item.get('text', '')
                        for item in msg.content
                        if isinstance(item, dict) and item.get('type') == 'text'
                    ),
                    '',
                )
                pruned_messages.append(HumanMessage(content=text_content))
            else:
                # It's an AI message, a simple HumanMessage, or the last message; keep as is.
                pruned_messages.append(msg)
        logging.debug(
            f'Pruned message history for token optimization. Original length: {len(current_messages)}, Pruned length: {len(pruned_messages)}'
        )
        # ---------------------------------------------

        # Reset per-step; prevents post-loop from using stale output on timeout/exception
        tool_output = ''

        try:
            # The agent's history includes all prior messages
            logging.debug(f'Step {i + 1} - Calling Agent to execute {step_type}...')
            start_time = datetime.datetime.now()

            # Step-level timeout: tool-specific or 300s default, capped by remaining case budget
            # Tools can override via step_timeout in their metadata (e.g. 600s for traversal)
            tool_timeout = step_timeout_map.get(step_type, 300.0)
            case_start = state.get('_case_start_time')
            case_timeout = state.get('_case_timeout', 1800.0)
            if case_start is not None:
                elapsed = (datetime.datetime.now() - case_start).total_seconds()
                remaining_budget = max(case_timeout - elapsed, 30.0)  # At least 30s
                step_timeout = min(tool_timeout, remaining_budget)
            else:
                step_timeout = tool_timeout

            try:
                result = await asyncio.wait_for(
                    agent_executor.ainvoke(
                        {'messages': pruned_messages},
                    ),
                    timeout=step_timeout,
                )
            except asyncio.TimeoutError:
                logging.error(
                    f'Step {i + 1} ({step_type}) timed out after {step_timeout:.0f}s'
                )
                case_recorder.add_step(
                    description=instruction_to_execute or f'Step {i + 1}',
                    status='warning',
                    step_type=step_type.lower(),
                    model_io=f'Step timed out after {step_timeout:.0f}s',
                )
                step_outcomes.append(StepOutcome(
                    step_index=i + 1,
                    severity=StepSeverity.HARD_FAIL,
                    description=f'System timeout: step timed out after {step_timeout:.0f}s',
                ))
                # System error: abort case immediately
                _timeout_exc = asyncio.TimeoutError(f'Step timed out after {step_timeout:.0f}s')
                final_summary = get_system_error_summary(_timeout_exc, language)
                user_summary = _i18n(
                    language,
                    f'{case_objective}，工具执行超时，结果不完整，非产品缺陷。',
                    f'{case_objective} tool execution timed out, results incomplete, not a product defect.',
                )
                code_determined_status = 'warning'
                code_failure_type = 'system_error'
                logging.warning(
                    f'System timeout at step {i + 1}, aborting case as warning'
                )
                break

            end_time = datetime.datetime.now()
            duration = (end_time - start_time).total_seconds()

            messages = result.get('messages', pruned_messages)

            # Handle intermediate_steps if available (when return_intermediate_steps=True)
            if 'intermediate_steps' in result and result['intermediate_steps']:
                # Convert intermediate steps to proper message format
                intermediate_messages = convert_intermediate_steps_to_messages(
                    result['intermediate_steps']
                )
                # Append intermediate messages to maintain proper conversation history
                messages.extend(intermediate_messages)
                logging.debug(
                    f'Step {i + 1} added {len(intermediate_messages)} intermediate messages'
                )

            # Get raw output (could be string or list depending on provider)
            raw_output = result.get('output', '')
            # Extract text content for string operations
            tool_output = extract_text_content(raw_output)

            logging.debug(
                f'Step {i + 1} {step_type} completed in {duration:.2f} seconds'
            )
            logging.debug(f'Step {i + 1} tool output: {tool_output}')
            messages.append(AIMessage(content=tool_output))

            # Check for warnings in the tool output (e.g., UX issues)
            # Check both agent output and raw tool result from intermediate steps
            intermediate_output = safe_get_intermediate_step(
                result, index=0, subindex=1, default=''
            )
            combined_output = f'{tool_output}\n{intermediate_output}'
            if '[warning]' in combined_output.lower():
                warning_steps.append(i + 1)
                logging.info(
                    f'Step {i + 1} completed with warnings (e.g., UX issues detected)'
                )

            # ===================================================================
            # PRIORITY 0: Critical failure check (highest priority, independent of is_failure)
            # ===================================================================
            # Critical failures are unrecoverable errors that prevent test continuation:
            # - ELEMENT_NOT_FOUND: Target element missing from DOM (cannot interact)
            # - PAGE_CRASHED: Browser page crashed (no recovery possible)
            # - UNSUPPORTED_PAGE: PDF/plugin pages (no DOM access for automation)
            # - PERMISSION_DENIED: Authentication expired or access blocked
            # - NAVIGATION_FAILED: Page navigation failures
            # These errors abort the test immediately to conserve resources.
            # Check BEFORE regular failure handling to prevent wasted retry attempts.
            if _is_critical_failure_step(tool_output, intermediate_output):

                # Smart differentiation: Check if unsupported page + page-agnostic operation
                is_unsupported_page = 'unsupported_page' in tool_output.lower()

                if is_unsupported_page:
                    # Determine if current operation is page-agnostic
                    is_agnostic = _is_operation_page_agnostic(
                        step_type=step_type, instruction=instruction_to_execute
                    )

                    if is_agnostic:
                        # Page-agnostic operation: Allow continued execution (degraded mode)
                        logging.warning(
                            f"[WARNING] Step {i + 1} '{instruction_to_execute}' executed on unsupported page type. "
                            f'This operation is page-agnostic and continuing with limited functionality. '
                            f'Subsequent DOM-dependent operations will fail.'
                        )
                        # Don't record as failure, don't break - skip abort logic, continue execution
                        # No action needed here - just let execution continue normally
                        pass
                    else:
                        # DOM-dependent operation on unsupported page: Must abort
                        step_outcomes.append(StepOutcome(
                            step_index=i + 1,
                            severity=StepSeverity.CRITICAL,
                            description='DOM-dependent operation on unsupported page type',
                        ))
                        # P4: Get current executed step count for accurate error reporting
                        current_executed_step = len(case_recorder.current_case_steps)
                        final_summary = _make_final_summary(language,
                                                            f'FINAL_SUMMARY: 严重错误，已执行步骤 {current_executed_step}（计划步骤 {i + 1}）：'
                                                            f"'{instruction_to_execute}'。"
                                                            f'DOM 操作无法在不支持的页面类型上执行。错误详情：{tool_output}',
                                                            f'FINAL_SUMMARY: Critical failure at executed step {current_executed_step} '
                                                            f'(planned step {i + 1}): '
                                                            f"'{instruction_to_execute}'. "
                                                            f'DOM-dependent operation cannot execute on unsupported page type. '
                                                            f'Error details: {tool_output}')
                        user_summary = _make_user_summary(language, 'failed', case_objective,
                                                          _i18n(language, '页面类型不支持自动化测试。', 'Page type does not support automated testing.'))
                        logging.error(
                            f'[CRITICAL] Executed step {current_executed_step} (planned step {i + 1}) '
                            f'requires DOM elements but page is unsupported (PDF/plugin). '
                            f'Aborting remaining {len(case_steps) - i - 1} planned steps to conserve resources.'
                        )
                        code_determined_status = 'failed'
                        code_failure_type = 'critical'
                        break  # Abort test case immediately
                else:
                    # Other types of critical errors (not unsupported page): Abort immediately
                    step_outcomes.append(StepOutcome(
                        step_index=i + 1,
                        severity=StepSeverity.CRITICAL,
                        description=f'Critical error: {tool_output[:200]}',
                    ))
                    # P4: Get current executed step count for accurate error reporting
                    current_executed_step = len(case_recorder.current_case_steps)
                    final_summary = _make_final_summary(language,
                                                        f'FINAL_SUMMARY: 严重错误，已执行步骤 {current_executed_step}（计划步骤 {i + 1}）：'
                                                        f"'{instruction_to_execute}'。错误详情：{tool_output}",
                                                        f'FINAL_SUMMARY: Critical failure at executed step {current_executed_step} '
                                                        f'(planned step {i + 1}): '
                                                        f"'{instruction_to_execute}'. "
                                                        f'Error details: {tool_output}')
                    user_summary = _make_user_summary(language, 'failed', case_objective,
                                                      _i18n(language, '遇到严重错误，测试终止。', 'Critical error encountered, test terminated.'))
                    logging.error(
                        f'[CRITICAL] Executed step {current_executed_step} (planned step {i + 1}) '
                        f'encountered critical failure. '
                        f'Aborting remaining {len(case_steps) - i - 1} planned steps to conserve resources.'
                    )
                    code_determined_status = 'failed'
                    code_failure_type = 'critical'
                    break  # Abort test case immediately

            # ===================================================================
            # PRIORITY 1: Regular failure check (only executed when not critical)
            # ===================================================================
            is_failure = _contains_failure_indicators(
                intermediate_output
            ) or _contains_failure_indicators(tool_output)
            is_element_not_found = (
                '[critical_error:element_not_found]' in tool_output.lower()
                or '[critical_error:element_not_found]' in intermediate_output.lower()
            )

            if is_failure:
                # Priority 0: Skip adaptive recovery for batch/diagnostic tools.
                # Their FAILURE output is a diagnostic finding, not a transient error.
                if step_type in recovery_disabled_step_types:
                    logging.info(
                        f'Step {i + 1} ({step_type}) reported failure — '
                        f'recording as diagnostic finding, recovery disabled for this tool.'
                    )
                    step_outcomes.append(StepOutcome(
                        step_index=i + 1,
                        severity=StepSeverity.SOFT_FAIL,
                        description=f'Diagnostic result: {tool_output[:200]}',
                    ))
                    i += 1
                    continue

                # Priority 1: Try recovery for ELEMENT_NOT_FOUND (recoverable critical error)
                elif is_element_not_found:
                    # Get dynamic config to check if adaptive recovery is enabled
                    dynamic_config = _get_dynamic_config(state)

                    if dynamic_config['enabled']:
                        # Adaptive recovery enabled
                        retry_key = f'step_{i}'
                        retry_count = step_retry_tracker.get(retry_key, 0)

                        if retry_count == 0:
                            # Layer 1: Simple retry after page stabilization
                            logging.info(
                                f'Step {i + 1} element not found, attempting Layer 1 recovery (simple retry after stabilization)'
                            )
                            await asyncio.sleep(
                                RETRY_STABILIZATION_DELAY
                            )  # Let page stabilize
                            step_retry_tracker[retry_key] = 1
                            # Don't increment i, will retry same step
                            continue

                        elif retry_count == 1:
                            # Layer 2: LLM-based adaptive replanning
                            logging.info(
                                f'Step {i + 1} failed twice, attempting Layer 2 recovery (LLM adaptive replanning)'
                            )

                            # Get current page screenshot for LLM analysis
                            try:
                                recovery_screenshot, _ = (
                                    await ui_tester_instance._actions.b64_page_screenshot(
                                        file_name=f'step_{i + 1}_recovery_attempt_{retry_count + 1}',
                                        context='error',
                                    )
                                )
                            except Exception as e:
                                logging.error(
                                    f'Failed to capture recovery screenshot: {e}'
                                )
                                recovery_screenshot = (
                                    screenshot  # Fallback to last screenshot
                                )

                            # Call unified dynamic adjustment function in failure recovery mode
                            recovery_result = await generate_dynamic_steps_with_llm(
                                failure_recovery_mode=True,
                                failed_instruction=instruction_to_execute,
                                error_message=tool_output,
                                test_objective=case.get('objective', ''),
                                executed_steps=i + 1,
                                llm=llm,
                                current_case=case,
                                screenshot=recovery_screenshot,
                            )

                            strategy = recovery_result.get('strategy')
                            confidence = recovery_result.get('confidence', 0.0)

                            if strategy == 'retry_modified':
                                # Replace current step with adapted instruction
                                new_steps = recovery_result.get('steps', [])
                                if new_steps:
                                    logging.info(
                                        f'Adapting step {i + 1} with new instruction (confidence: {confidence:.2f})'
                                    )
                                    logging.debug(
                                        f"Adaptation reason: {recovery_result.get('reason', 'N/A')}"
                                    )
                                    case_steps[i] = new_steps[0]
                                    case_modified = (
                                        True  # Mark case as modified for consistency
                                    )
                                    step_retry_tracker[retry_key] = 2  # Mark as adapted
                                    continue  # Retry with adapted instruction

                            elif strategy == 'skip':
                                logging.warning(
                                    f"Skipping step {i + 1} based on recovery analysis: {recovery_result.get('reason', 'N/A')}"
                                )
                                step_outcomes.append(StepOutcome(
                                    step_index=i + 1,
                                    severity=StepSeverity.SKIPPED,
                                    description='Skipped via ELEMENT_NOT_FOUND recovery',
                                    recovery_strategy='skip',
                                    recovery_reason=recovery_result.get('reason', 'N/A'),
                                ))
                                # i will increment normally, skip this step

                            elif strategy == 'abort':
                                # P4: Get current executed step count for accurate error reporting
                                current_executed_step = len(
                                    case_recorder.current_case_steps
                                )
                                recovery_reason = recovery_result.get('reason', '')
                                logging.error(
                                    f'Aborting test at executed step {current_executed_step} (planned step {i + 1}) '
                                    f"based on recovery analysis: {recovery_reason or 'N/A'}"
                                )
                                step_outcomes.append(StepOutcome(
                                    step_index=i + 1,
                                    severity=StepSeverity.CRITICAL,
                                    description=f'Element not found abort: {recovery_reason}',
                                    recovery_strategy='abort',
                                    recovery_reason=recovery_reason,
                                ))
                                final_summary = _make_final_summary(language,
                                                                    f'FINAL_SUMMARY: 测试在已执行步骤 {current_executed_step}（计划步骤 {i + 1}）中止。'
                                                                    f"{recovery_reason or '严重错误'}",
                                                                    f'FINAL_SUMMARY: Test aborted at executed step {current_executed_step} '
                                                                    f"(planned step {i + 1}). {recovery_reason or 'Critical failure'}")
                                reason_suffix = f"{recovery_reason.rstrip('.')}." if recovery_reason else ''
                                user_summary = _make_user_summary(
                                    language, 'failed', case_objective,
                                    _i18n(language,
                                          '目标元素无法定位，自动恢复尝试失败。',
                                          f'Target element could not be located, automatic recovery failed. {reason_suffix}'))
                                code_determined_status = 'failed'
                                code_failure_type = 'recoverable'
                                break

                        else:
                            # Already adapted but still failing - mark as failed and continue
                            step_outcomes.append(StepOutcome(
                                step_index=i + 1,
                                severity=StepSeverity.HARD_FAIL,
                                description='Failed even after adaptation',
                            ))
                            logging.error(
                                f'Step {i + 1} failed even after adaptation, marking as failed'
                            )
                    else:
                        # Adaptive recovery disabled for ELEMENT_NOT_FOUND
                        step_outcomes.append(StepOutcome(
                            step_index=i + 1,
                            severity=StepSeverity.SOFT_FAIL,
                            description='Element not found, adaptive recovery disabled',
                        ))
                        logging.warning(
                            f'Step {i + 1} element not found, but adaptive recovery is disabled'
                        )

                # Handle other failures: Non-critical failures not caused by ELEMENT_NOT_FOUND
                # (e.g., GoBack with no history, operation timeout, permission issues)
                else:
                    logging.warning(
                        f'Step {i + 1} failed (non-ELEMENT_NOT_FOUND): {tool_output}'
                    )

                    # Extended LLM adaptive recovery for all failure types
                    dynamic_config = _get_dynamic_config(state)

                    if dynamic_config['enabled']:
                        # Add retry tracking to prevent infinite loops (consistent with ELEMENT_NOT_FOUND branch)
                        retry_key = f'step_{i}_non_element'
                        retry_count = step_retry_tracker.get(retry_key, 0)

                        if retry_count >= 2:  # Maximum 2 recovery attempts
                            logging.error(
                                f'[ADAPTIVE_RECOVERY] Step {i + 1} exceeded max recovery attempts (2), '
                                f'marking as failed.'
                            )
                            step_outcomes.append(StepOutcome(
                                step_index=i + 1,
                                severity=StepSeverity.HARD_FAIL,
                                description='Exceeded max recovery attempts (2)',
                            ))
                        else:
                            logging.info(
                                f'[ADAPTIVE_RECOVERY] Step {i + 1} failed with non-ELEMENT_NOT_FOUND error. '
                                f'Attempt {retry_count + 1}/2 for LLM-based adaptive recovery.'
                            )

                            try:
                                # Prepare context for LLM recovery (use correct variable: ui_tester_instance)
                                screenshot_b64 = None
                                try:
                                    screenshot_b64, _ = (
                                        await ui_tester_instance._actions.b64_page_screenshot(
                                            file_name=f'recovery_step_{i + 1}',
                                            context='adaptive_recovery',
                                        )
                                    )
                                except Exception as e:
                                    logging.warning(
                                        f'Failed to capture screenshot for recovery: {e}'
                                    )

                                # Call LLM adaptive recovery (aligned with ELEMENT_NOT_FOUND branch parameters)
                                recovery_result = await generate_dynamic_steps_with_llm(
                                    failure_recovery_mode=True,
                                    failed_instruction=instruction_to_execute,
                                    error_message=tool_output,
                                    test_objective=case.get('objective', ''),
                                    executed_steps=i + 1,  # Use int, not list
                                    llm=llm,
                                    current_case=case,  # Include current_case for context
                                    screenshot=screenshot_b64,
                                )

                                # Process recovery strategy
                                strategy = recovery_result.get('strategy', 'abort')
                                new_steps = recovery_result.get('steps', [])
                                reason = recovery_result.get(
                                    'reason', 'No reason provided'
                                )

                                logging.info(
                                    f'[ADAPTIVE_RECOVERY] Strategy: {strategy}, '
                                    f'Reason: {reason}'
                                )

                                if strategy == 'retry_modified' and new_steps:
                                    # Replace current step with modified instruction
                                    case_steps[i] = new_steps[0]
                                    case_modified = True
                                    step_retry_tracker[retry_key] = (
                                        retry_count + 1
                                    )  # Track retry count
                                    logging.info(
                                        f'[ADAPTIVE_RECOVERY] Modified step {i + 1}: '
                                        f"{new_steps[0].get('action') or new_steps[0].get('verify')}"
                                    )
                                    # Retry this step (don't increment i)
                                    continue

                                elif strategy == 'skip':
                                    # Skip this failed step as non-critical
                                    logging.warning(
                                        f'[ADAPTIVE_RECOVERY] Skipping step {i + 1} as non-critical. '
                                        f'Reason: {reason}'
                                    )
                                    step_outcomes.append(StepOutcome(
                                        step_index=i + 1,
                                        severity=StepSeverity.SKIPPED,
                                        description='Skipped via non-ELEMENT_NOT_FOUND recovery',
                                        recovery_strategy='skip',
                                        recovery_reason=reason,
                                    ))
                                    # Continue to next step (increment i at loop end)

                                elif strategy == 'abort':
                                    # Cannot recover, abort test
                                    # P4: Get current executed step count for accurate error reporting
                                    current_executed_step = len(
                                        case_recorder.current_case_steps
                                    )
                                    logging.error(
                                        f'[ADAPTIVE_RECOVERY] Cannot recover from executed step {current_executed_step} '
                                        f'(planned step {i + 1}) failure. Aborting test. Reason: {reason}'
                                    )
                                    step_outcomes.append(StepOutcome(
                                        step_index=i + 1,
                                        severity=StepSeverity.CRITICAL,
                                        description=f'Abort recovery: {reason}',
                                        recovery_strategy='abort',
                                        recovery_reason=reason,
                                    ))
                                    final_summary = _make_final_summary(language,
                                                                        f'FINAL_SUMMARY: 不可恢复的失败，已执行步骤 {current_executed_step}（计划步骤 {i + 1}）：'
                                                                        f"'{instruction_to_execute}'。LLM 自适应恢复判断必须终止。原因：{reason}",
                                                                        f'FINAL_SUMMARY: Unrecoverable failure at executed step {current_executed_step} '
                                                                        f'(planned step {i + 1}): '
                                                                        f"'{instruction_to_execute}'. "
                                                                        f'LLM adaptive recovery determined abortion necessary. '
                                                                        f'Reason: {reason}')
                                    reason_suffix = f"{reason.rstrip('.')}." if reason else ''
                                    user_summary = _make_user_summary(
                                        language, 'failed', case_objective,
                                        _i18n(language,
                                              '测试遇到不可恢复的问题，自动恢复失败。',
                                              f'Test encountered an unrecoverable issue, automatic recovery failed. {reason_suffix}'))
                                    code_determined_status = 'failed'
                                    code_failure_type = 'critical'
                                    break  # Abort test case

                                else:
                                    # Unknown strategy, default to marking as failed
                                    logging.warning(
                                        f"[ADAPTIVE_RECOVERY] Unknown strategy '{strategy}', "
                                        f'marking step as failed.'
                                    )
                                    step_outcomes.append(StepOutcome(
                                        step_index=i + 1,
                                        severity=StepSeverity.SOFT_FAIL,
                                        description=f'Unknown recovery strategy: {strategy}',
                                        recovery_strategy=strategy,
                                    ))

                            except Exception as e:
                                logging.error(
                                    f'[ADAPTIVE_RECOVERY] LLM recovery failed with exception: {e}. '
                                    f'Marking step as failed.'
                                )
                                step_outcomes.append(StepOutcome(
                                    step_index=i + 1,
                                    severity=StepSeverity.SOFT_FAIL,
                                    description=f'LLM recovery exception: {e}',
                                ))
                    else:
                        # Adaptive recovery disabled - just mark as failed
                        step_outcomes.append(StepOutcome(
                            step_index=i + 1,
                            severity=StepSeverity.SOFT_FAIL,
                            description='Non-element failure, adaptive recovery disabled',
                        ))

            # Check for objective achievement signal
            is_achieved, achievement_reason = _is_objective_achieved(tool_output)
            if is_achieved:
                objective_achieved = True
                current_executed_step = len(case_recorder.current_case_steps)
                logging.info(
                    f'Test objective achieved at executed step {current_executed_step} '
                    f'(planned step {i + 1}): {achievement_reason}'
                )
                final_summary = _make_final_summary(language,
                                                    f'FINAL_SUMMARY: 测试用例在已执行步骤 {current_executed_step}（计划步骤 {i + 1}/{total_steps}）提前终止，执行成功。{achievement_reason}',
                                                    f'FINAL_SUMMARY: Test case completed successfully with early '
                                                    f'termination at executed step {current_executed_step} '
                                                    f'(planned step {i + 1}/{total_steps}). {achievement_reason}')
                user_summary = _make_user_summary(language, 'passed', case_objective)
                code_determined_status = 'passed'
                code_failure_type = None
                break

            # Record PASSED outcome for successful steps (no prior outcome recorded)
            step_already_recorded = any(o.step_index == i + 1 for o in step_outcomes)
            if not step_already_recorded:
                step_outcomes.append(StepOutcome(
                    step_index=i + 1,
                    severity=StepSeverity.PASSED,
                ))

            logging.debug(
                f"Step {i + 1} completed {'successfully' if (i + 1) not in _get_failed_step_indices() else 'with issues'}."
            )

            # --- Dynamic Step Generation ---
            # Triggers when new DOM elements (≥ threshold) appear after actions
            # Defaults: enabled=True, max_steps=8, threshold=2
            if step_type == 'Action':
                # Get dynamic step generation config from state
                dynamic_config = _get_dynamic_config(state)

                dynamic_enabled = dynamic_config['enabled']
                max_dynamic_steps = dynamic_config['max_dynamic_steps']
                min_elements_threshold = dynamic_config['min_elements_threshold']

                if dynamic_enabled:
                    # Extract DOM diff from tool output (safely access intermediate_steps)
                    intermediate_output = safe_get_intermediate_step(
                        result, index=0, subindex=1, default=''
                    )
                    dom_diff = extract_dom_diff_from_output(intermediate_output)

                    if (
                        dom_diff
                        and len(dom_diff) >= min_elements_threshold
                        and dom_diff not in dom_diff_cache
                    ):
                        logging.info(
                            f'Detected {len(dom_diff)} new elements, starting dynamic test step generation'
                        )

                        try:
                            # Capture screenshot for visual context after successful step execution
                            logging.debug(
                                'Capturing screenshot for dynamic step generation context'
                            )
                            screenshot, _ = (
                                await ui_tester_instance._actions.b64_page_screenshot()
                            )

                            # Enhance objective with generation context for smarter LLM decision-making
                            enhanced_objective = case.get('objective', '')
                            if dynamic_generation_count > 0:
                                enhanced_objective += f' (Context: Already generated {dynamic_generation_count} rounds of dynamic steps, be selective about additional generation)'
                            if i + 1 > LONG_STEPS:  # Long test indicator
                                enhanced_objective += f' (Context: Test already has {i + 1} steps, consider if more steps add meaningful value)'

                            # Determine if current step succeeded based on step_outcomes
                            step_success = (i + 1) not in _get_failed_step_indices()

                            # Generate dynamic test steps with complete context and visual information
                            dynamic_result = await generate_dynamic_steps_with_llm(
                                dom_diff=dom_diff,
                                last_action=instruction_to_execute,
                                test_objective=enhanced_objective,
                                executed_steps=i + 1,
                                max_steps=max_dynamic_steps,
                                llm=llm,
                                current_case=case,
                                screenshot=screenshot,
                                tool_output=tool_output,
                                step_success=step_success,
                            )

                            # Handle dynamic steps based on LLM strategy decision
                            strategy = dynamic_result.get('strategy', 'insert')
                            reason = dynamic_result.get('reason', 'No reason provided')
                            dynamic_steps = dynamic_result.get('steps', [])

                            if dynamic_steps:
                                logging.info(
                                    f"Generated {len(dynamic_steps)} dynamic test steps with strategy '{strategy}': {reason}"
                                )
                                case_steps = case.get('steps', [])

                                # Increment generation count since we're actually adding steps
                                dynamic_generation_count += 1

                                # Convert dynamic steps to the standard format and filter duplicates
                                def is_similar_step(step1: dict, step2: dict) -> bool:
                                    """Check if two steps are similar to avoid
                                    duplicates."""
                                    if 'action' in step1 and 'action' in step2:
                                        return (
                                            step1['action'].lower().strip()
                                            == step2['action'].lower().strip()
                                        )
                                    if 'verify' in step1 and 'verify' in step2:
                                        return (
                                            step1['verify'].lower().strip()
                                            == step2['verify'].lower().strip()
                                        )
                                    return False

                                formatted_dynamic_steps = []
                                executed_and_remaining = (
                                    case_steps  # All existing steps
                                )

                                for dyn_step in dynamic_steps:
                                    # Check for duplicates before adding
                                    is_duplicate = False
                                    for existing_step in executed_and_remaining:
                                        if is_similar_step(dyn_step, existing_step):
                                            logging.debug(
                                                f'Skipping duplicate step: {dyn_step}'
                                            )
                                            is_duplicate = True
                                            break

                                    if not is_duplicate:
                                        if 'action' in dyn_step:
                                            formatted_dynamic_steps.append(
                                                {'action': dyn_step['action']}
                                            )
                                        if 'verify' in dyn_step:
                                            formatted_dynamic_steps.append(
                                                {'verify': dyn_step['verify']}
                                            )

                                # Apply strategy: insert or replace
                                if strategy == 'replace':
                                    # Replace all remaining steps with new steps
                                    case_steps = (
                                        case_steps[: i + 1] + formatted_dynamic_steps
                                    )
                                    logging.info(
                                        f'Replaced remaining steps with {len(formatted_dynamic_steps)} dynamic steps'
                                    )
                                else:
                                    # Insert steps at current position
                                    insert_position = i + 1
                                    case_steps[insert_position:insert_position] = (
                                        formatted_dynamic_steps
                                    )
                                    logging.info(
                                        f'Inserted {len(formatted_dynamic_steps)} dynamic steps at position {insert_position}'
                                    )

                                case['steps'] = case_steps

                                # Update total_steps to include the new steps
                                total_steps = len(case_steps)

                                # Mark the case as modified for later saving
                                case['_dynamic_steps_added'] = True
                                case['_dynamic_steps_count'] = len(
                                    formatted_dynamic_steps
                                )
                                case['_dynamic_strategy'] = strategy
                                case['_dynamic_reason'] = reason
                                case_modified = True

                                logging.info(
                                    f"Applied '{strategy}' strategy. Total steps now: {total_steps}"
                                )
                            else:
                                logging.debug(
                                    f'LLM determined no dynamic steps needed: {reason}'
                                )

                        except Exception as dyn_gen_e:
                            logging.error(
                                f'Error in dynamic step generation process: {dyn_gen_e}'
                            )
                    else:
                        if dom_diff:
                            logging.debug(
                                f'Detected {len(dom_diff)} new elements, but below threshold {min_elements_threshold}, skipping dynamic step generation'
                            )
                        else:
                            logging.debug(
                                'No DOM changes detected, skipping dynamic step generation'
                            )
                    # Store DOM diff for debugging/analysis (not used for deduplication - each step gets fresh analysis)
                    dom_diff_cache.append(dom_diff)

                else:
                    logging.debug('Dynamic step generation not enabled')
            # --- Dynamic Step Generation End ---

        except Exception as e:
            logging.error(f'Exception during step {i + 1} execution: {str(e)}')
            if is_system_error(e):
                # System-level error: mark warning, neutral summary, abort
                logging.warning(
                    f'System error at step {i + 1}: {type(e).__name__}: {e}'
                )
                step_outcomes.append(StepOutcome(
                    step_index=i + 1,
                    severity=StepSeverity.HARD_FAIL,
                    description=f'System error: {str(e)}',
                ))
                case_recorder.add_step(
                    description=instruction_to_execute or f'Step {i + 1}',
                    status='warning',
                    step_type=step_type.lower() if step_type else 'action',
                    model_io=f'System error: {str(e)}',
                )
                final_summary = get_system_error_summary(e, language)
                user_summary = _make_user_summary(language, 'warning', case_objective)
                code_determined_status = 'warning'
                code_failure_type = 'system_error'
            else:
                # Non-system error: keep existing failed logic
                step_outcomes.append(StepOutcome(
                    step_index=i + 1,
                    severity=StepSeverity.HARD_FAIL,
                    description=f'Step exception: {str(e)}',
                ))
                case_recorder.add_step(
                    description=instruction_to_execute or f'Step {i + 1}',
                    status='failed',
                    step_type=step_type.lower() if step_type else 'action',
                    model_io=f'Exception: {str(e)}',
                )
                final_summary = _make_final_summary(language,
                                                    f"FINAL_SUMMARY: 步骤 '{instruction_to_execute}' 发生异常：{str(e)}",
                                                    f"FINAL_SUMMARY: Step '{instruction_to_execute}' raised an exception: {str(e)}")
                user_summary = _make_user_summary(language, 'failed', case_objective,
                                                  _i18n(language,
                                                        f"步骤'{instruction_to_execute}'执行时发生异常。",
                                                        f"Step '{instruction_to_execute}' raised an exception during execution."))
                code_determined_status = 'failed'
                code_failure_type = 'recoverable'
            break

        # Move to next step
        i += 1

    # Upgrade template-based user_summary with LLM-generated one if available.
    # Only when code_failure_type is None (normal completion / OBJECTIVE_ACHIEVED);
    # critical/system_error/recoverable paths already set a definitive template.
    if code_failure_type is None:
        parsed_user_summary = _parse_user_summary(tool_output)
        if parsed_user_summary:
            user_summary = parsed_user_summary

    # If the loop finishes without an early exit, generate a final summary
    if 'final_summary:' not in final_summary.lower():
        logging.debug('All test steps completed, generating final summary')
        logging.debug(f'Failed steps detected during execution: {_get_failed_step_indices()}')

        # P4 Enhancement: Get executed steps count from case_recorder
        # This provides accurate step count including UI Agent's sub-steps
        executed_steps_count = len(case_recorder.current_case_steps)
        planned_steps_count = len(case_steps)
        step_expansion_ratio = (
            round(executed_steps_count / planned_steps_count, 2)
            if planned_steps_count > 0
            else 1.0
        )

        logging.debug(
            f'Step counts: {planned_steps_count} planned steps → '
            f'{executed_steps_count} executed steps (expansion ratio: {step_expansion_ratio}x)'
        )

        # Helper function to sanitize messages for summary generation
        def _sanitize_message_for_summary(msg, max_length: int = 250) -> str:
            """Clean message content to avoid Azure OpenAI content filter
            triggers.

            Removes:
            - Base64 image URLs (main trigger)
            - HTML tags (XSS detection)
            - Error keywords that trigger safety filters
            - DOM dumps
            """
            import re

            # Extract content
            if hasattr(msg, 'content'):
                content = str(msg.content)
            else:
                content = str(msg)

            # Remove base64 image URLs (primary trigger for content filter)
            content = re.sub(
                r'data:image/[^;]+;base64,[A-Za-z0-9+/=]+', '[IMAGE_REMOVED]', content
            )

            # Remove HTML tags (can trigger XSS detection)
            content = re.sub(r'<[^>]+>', '', content)

            # Remove error keywords that may trigger content filter
            content = re.sub(
                r'\b(denied|blocked|failed|error|forbidden|hack|exploit|inject)\b',
                '[X]',
                content,
                flags=re.IGNORECASE,
            )

            # Remove DOM dumps (can be large and trigger filters)
            if 'pageDescription' in content or 'dom_tree' in content:
                content = re.sub(
                    r'pageDescription.*?(?===|$)',
                    '[DOM_SUMMARY]',
                    content,
                    flags=re.DOTALL,
                )

            # Truncate to max length
            return content[:max_length]

        # Use the LLM directly to generate the summary (not through the agent)
        try:
            # Prepare context for summary generation
            # P4 Enhancement: Use executed steps count for accurate reporting
            # Build step severity summary for LLM context
            severity_summary = {
                'critical': len([o for o in step_outcomes if o.severity == StepSeverity.CRITICAL]),
                'hard_fail': len([o for o in step_outcomes if o.severity == StepSeverity.HARD_FAIL]),
                'soft_fail': len([o for o in step_outcomes if o.severity == StepSeverity.SOFT_FAIL]),
                'skipped': len([o for o in step_outcomes if o.severity == StepSeverity.SKIPPED]),
                'warning': len(warning_steps),
                'passed': len([o for o in step_outcomes if o.severity == StepSeverity.PASSED]),
            }

            if language == 'zh-CN':
                summary_prompt = f"""根据测试用例"{case_name}"的执行情况，生成一份摘要。

测试目标：{case.get('objective', '未指定')}
成功标准：{case.get('success_criteria', ['未指定'])}
计划步骤数：{planned_steps_count} 步
实际执行步骤数：{executed_steps_count} 步（扩展比例：{step_expansion_ratio}x）
失败步骤：{_get_failed_step_indices() or '无'}

步骤执行结果统计：
- 严重错误(CRITICAL): {severity_summary['critical']} 个
- 产品缺陷(HARD_FAIL): {severity_summary['hard_fail']} 个
- 基础设施问题(SOFT_FAIL): {severity_summary['soft_fail']} 个（非产品缺陷，如网络超时、工具异常）
- 跳过(SKIPPED): {severity_summary['skipped']} 个
- 警告(WARNING): {severity_summary['warning']} 个
- 通过(PASSED): {severity_summary['passed']} 个
测试目标提前达成: {'是' if objective_achieved else '否'}

**重要**：引用步骤时请使用实际执行的步骤编号。测试计划了 {planned_steps_count} 步，但 UI Agent 实际执行了 {executed_steps_count} 步（包含元素定位、滚动等子步骤）。

请先在第一行输出测试结果状态，然后输出详细摘要：

STATUS: passed（所有成功标准已验证通过，测试目标完全达成）
STATUS: failed（存在关键步骤失败、成功标准未满足、或核心功能缺陷）
STATUS: warning（核心功能正常，但存在非关键的视觉或体验问题）

判定规则（严格遵守，不可偏离）：
- 有 CRITICAL 或 HARD_FAIL → STATUS: failed
- 仅有 SOFT_FAIL 且测试目标未达成 → STATUS: failed
- 测试目标达成且无 CRITICAL/HARD_FAIL → STATUS: passed
- 无失败但有 WARNING → STATUS: warning
- 全部通过 → STATUS: passed
- **禁止规则：如果 CRITICAL=0 且 HARD_FAIL=0 且 SOFT_FAIL=0，则禁止输出 STATUS: failed**

示例输出格式：
STATUS: passed
FINAL_SUMMARY: 测试用例"{case_name}"执行完成。共执行 {executed_steps_count} 个步骤，均未出现严重错误。测试目标已达成：[确认说明]。所有成功标准均已满足。
USER_SUMMARY: [用一句话业务语言概括验证结果]

STATUS: failed
FINAL_SUMMARY: 测试用例"{case_name}"在第 [X] 步（共 {executed_steps_count} 步）失败。错误：[描述]。恢复尝试：[如有]。建议：[修复方案]。
USER_SUMMARY: [功能名]异常：[用户可感知的问题]。建议[修复方向]。

STATUS: warning
FINAL_SUMMARY: 测试用例"{case_name}"执行完成。核心功能正常，但检测到非关键问题：[问题描述]。
USER_SUMMARY: [功能名]基本正常，但[用户可感知的非关键问题]。"""
            else:
                summary_prompt = f"""Based on the test execution of case "{case_name}", generate a summary.

Test Objective: {case.get('objective', 'Not specified')}
Success Criteria: {case.get('success_criteria', ['Not specified'])}
Planned Steps: {planned_steps_count} steps
Executed Steps: {executed_steps_count} steps (expansion ratio: {step_expansion_ratio}x)
Failed Steps: {_get_failed_step_indices() or 'None'}

Step Execution Results:
- Critical errors (CRITICAL): {severity_summary['critical']}
- Product defects (HARD_FAIL): {severity_summary['hard_fail']}
- Infrastructure issues (SOFT_FAIL): {severity_summary['soft_fail']} (not product defects, e.g., network timeout, tool errors)
- Skipped (SKIPPED): {severity_summary['skipped']}
- Warnings (WARNING): {severity_summary['warning']}
- Passed (PASSED): {severity_summary['passed']}
Objective achieved early: {'Yes' if objective_achieved else 'No'}

**Important**: Use executed step numbers when referencing steps. The test had {planned_steps_count} planned steps,
but the UI Agent executed {executed_steps_count} detailed steps (including sub-steps for element location, scrolling, etc.).

Output the test result status on the first line, followed by the detailed summary:

STATUS: passed (all success criteria verified, test objective fully achieved)
STATUS: failed (critical step failures, unmet success criteria, or core functionality defects)
STATUS: warning (core functionality works, but non-critical visual or UX issues detected)

Decision rules (strictly follow, no deviation):
- CRITICAL or HARD_FAIL present → STATUS: failed
- Only SOFT_FAIL and objective not achieved → STATUS: failed
- Objective achieved with no CRITICAL/HARD_FAIL → STATUS: passed
- No failures but WARNING present → STATUS: warning
- All passed → STATUS: passed
- **Prohibition: If CRITICAL=0 AND HARD_FAIL=0 AND SOFT_FAIL=0, you MUST NOT output STATUS: failed**

Example output format:
STATUS: passed
FINAL_SUMMARY: Test case "{case_name}" completed successfully. All {executed_steps_count} executed steps completed without critical errors. Test objective achieved: [confirmation]. All success criteria met.
USER_SUMMARY: [One sentence confirming the verified feature works, in business language]

STATUS: failed
FINAL_SUMMARY: Test case "{case_name}" failed at executed step [X] (out of {executed_steps_count} total executed steps). Error: [description]. Recovery attempts: [if any]. Recommendation: [suggested fix].
USER_SUMMARY: [Feature name] issue: [user-perceivable problem]. Suggest [actionable recommendation].

STATUS: warning
FINAL_SUMMARY: Test case "{case_name}" completed. Core functionality works, but non-critical issues detected: [issue description].
USER_SUMMARY: [Feature name] mostly works, but [user-perceivable non-critical issue]."""

            # Get and sanitize recent messages (reduced from 6 to 4 to minimize content filter risk)
            recent_messages = []
            for msg in messages[-4:]:  # Last 2 exchanges (reduced from 6/3)
                sanitized = _sanitize_message_for_summary(msg, max_length=250)

                if isinstance(msg, HumanMessage):
                    recent_messages.append(f'User: {sanitized}')
                elif isinstance(msg, AIMessage):
                    recent_messages.append(f'Agent: {sanitized}')

            context = '\n'.join(recent_messages)
            logging.debug(
                f'Sanitized context for summary generation ({len(context)} chars)'
            )

            full_prompt = (
                f'{summary_prompt}\n\nRecent test execution context:\n{context}'
            )

            # Retry logic to handle content filter errors
            agent_output = None
            max_retries = 2

            for attempt in range(max_retries):
                try:
                    logging.debug(
                        f'Attempting summary generation (attempt {attempt + 1}/{max_retries})'
                    )
                    response = await llm.ainvoke(full_prompt)

                    # Successfully got response
                    if hasattr(response, 'content'):
                        agent_output = response.content
                    else:
                        agent_output = str(response)

                    logging.debug('Summary generation successful')
                    break

                except Exception as llm_error:
                    error_msg = str(llm_error)

                    # Check if this is a content filter error
                    is_content_filter = 'content' in error_msg.lower() and (
                        'filter' in error_msg.lower() or 'policy' in error_msg.lower()
                    )

                    if is_content_filter:
                        logging.warning(
                            f'Azure content filter triggered during summary generation (attempt {attempt + 1}): {error_msg[:200]}'
                        )

                        if attempt < max_retries - 1:
                            # Retry with minimal context (no message history)
                            logging.info(
                                'Retrying with minimal context (no message history)'
                            )
                            full_prompt = f"""{summary_prompt}

Test case: {case_name}
Total steps: {total_steps}
Failed steps: {len(_get_failed_step_indices())}

Generate a brief summary without referencing specific execution details."""
                            await asyncio.sleep(0.5)  # Brief delay before retry
                        else:
                            # Max retries reached
                            logging.error(
                                'Max retries reached for summary generation, using fallback'
                            )
                            break
                    else:
                        # Non-content-filter error, don't retry
                        logging.error(
                            f'Non-content-filter error in summary generation: {error_msg}'
                        )
                        break

            # If LLM failed after retries, agent_output will be None and fallback will be used below
            if not agent_output:
                # Will use fallback in except block
                raise Exception('LLM summary generation failed after retries')

            # Ensure the summary has the correct format
            # LLM may output "STATUS: passed\nFINAL_SUMMARY: ..." — strip STATUS
            # line before checking prefix to avoid wrapping an already-formatted
            # summary (which would produce a double FINAL_SUMMARY).
            _summary_output = agent_output
            if agent_output and agent_output.strip().startswith('STATUS:'):
                lines = agent_output.strip().split('\n', 1)
                if len(lines) > 1:
                    _summary_output = lines[1].strip()

            if _summary_output and not _summary_output.startswith('FINAL_SUMMARY:'):
                # Auto-format the response if it doesn't follow the expected format
                logging.debug(
                    'LLM summary missing FINAL_SUMMARY prefix, auto-formatting'
                )
                if not _get_failed_step_indices():
                    # P4: Use executed steps count
                    final_summary = _make_final_summary(language,
                                                        f'FINAL_SUMMARY: 测试用例"{case_name}"执行完成。共执行 {executed_steps_count} 个步骤。{agent_output}',
                                                        f'FINAL_SUMMARY: Test case "{case_name}" completed successfully. All {executed_steps_count} executed steps completed. {agent_output}')
                else:
                    final_summary = (
                        _make_final_summary(language,
                                            f'FINAL_SUMMARY: 测试用例"{case_name}"失败。{agent_output}',
                                            f'FINAL_SUMMARY: Test case "{case_name}" failed. {agent_output}')
                    )
            else:
                # Use agent_output (not _summary_output) to preserve STATUS line
                # for _parse_llm_status; stripped post-determination below.
                final_summary = (
                    agent_output
                    if agent_output
                    else _make_final_summary(language,
                                             f'FINAL_SUMMARY: 测试用例"{case_name}"已完成全部 {executed_steps_count} 个步骤。',
                                             f'FINAL_SUMMARY: Test case "{case_name}" completed all {executed_steps_count} executed steps.')
                )

            logging.debug(f'Final summary generated: {final_summary}')

            # Parse USER_SUMMARY from LLM output
            user_summary = _parse_user_summary(agent_output) or ''
            if not user_summary:
                # LLM did not output USER_SUMMARY — use template fallback
                if not _get_failed_step_indices():
                    user_summary = _make_user_summary(language, 'passed', case_objective)
                else:
                    user_summary = _make_user_summary(language, 'failed', case_objective)

        except Exception as e:
            logging.error(f'Exception during final summary generation: {str(e)}')
            if is_system_error(e):
                # Summary LLM itself failed → system error
                final_summary = get_system_error_summary(e, language)
                user_summary = _make_user_summary(language, 'warning', case_objective)
                code_determined_status = 'warning'
                code_failure_type = 'system_error'
            elif not _get_failed_step_indices():
                # P4: Use executed steps count
                final_summary = _make_final_summary(language,
                                                    f'FINAL_SUMMARY: 测试用例"{case_name}"执行完成。共执行 {executed_steps_count} 个步骤，未检测到失败。',
                                                    f'FINAL_SUMMARY: Test case "{case_name}" completed successfully. All {executed_steps_count} executed steps completed without detected failures.')
                user_summary = _make_user_summary(language, 'passed', case_objective)
                code_determined_status = 'passed'
            else:
                failed_indices = _get_failed_step_indices()
                final_summary = _make_final_summary(language,
                                                    f'FINAL_SUMMARY: 测试用例"{case_name}"完成，以下步骤失败：{failed_indices}，请查看执行日志。',
                                                    f'FINAL_SUMMARY: Test case "{case_name}" completed with failures at steps {failed_indices}. Review execution logs for details.')
                user_summary = _make_user_summary(language, 'failed', case_objective)
                code_determined_status = 'failed'
                code_failure_type = _derive_failure_type_from_outcomes(step_outcomes)

    # --- Status Determination: LLM-first + Safety Guard ---
    if code_determined_status is not None:
        # Path A: Code-deterministic (critical, abort, exception, objective)
        if code_failure_type == 'system_error':
            # System error bypasses safety guard — HARD_FAIL is system-caused
            status = code_determined_status
            logging.debug(
                f"System error bypass: '{case_name}' status='{status}', "
                f'skipping safety guard'
            )
        else:
            status = _apply_safety_guard(code_determined_status, step_outcomes)
        failure_type = code_failure_type
        if status == 'failed' and not failure_type:
            failure_type = _derive_failure_type_from_outcomes(step_outcomes)
        logging.debug(
            f"Code-determined status for '{case_name}': {status} "
            f'(failure_type={failure_type})'
        )
    else:
        # Path B: Normal completion — LLM STATUS with safety guard + verdict fallback
        llm_status = _parse_llm_status(final_summary)
        if llm_status:
            status = _apply_safety_guard(llm_status, step_outcomes)
            if status != llm_status:
                logging.warning(
                    f"Safety guard overrode LLM status '{llm_status}' → '{status}' "
                    f"for '{case_name}'"
                )
            else:
                logging.debug(f"LLM-determined status for '{case_name}': {status}")
        else:
            # Fallback: use deterministic verdict
            status, _fallback_failure_type = _verdict_fallback(
                step_outcomes, warning_steps, objective_achieved
            )
            logging.warning(
                f"LLM did not output valid STATUS for '{case_name}', "
                f'using verdict fallback: {status}'
            )

        # Determine failure_type
        failure_type = None
        if status == 'failed':
            failure_type = _derive_failure_type_from_outcomes(step_outcomes)

    # Clean LLM formatting markers from final_summary — these were only
    # needed for internal parsing and should not appear in user-facing reports.
    if final_summary:
        final_summary = final_summary.strip()

        # Strip STATUS: line (was only needed for _parse_llm_status)
        if final_summary.startswith('STATUS:'):
            _fs_lines = final_summary.split('\n', 1)
            final_summary = _fs_lines[1].strip() if len(_fs_lines) > 1 else ''

        # Strip USER_SUMMARY: line (stored separately in user_summary)
        if re.search(r'USER_SUMMARY:', final_summary, re.IGNORECASE):
            final_summary = re.sub(r'\n?USER_SUMMARY:.*$', '', final_summary, flags=re.MULTILINE | re.IGNORECASE).strip()

        # Strip FINAL_SUMMARY: prefix (was a formatting marker for LLM output)
        if final_summary.upper().startswith('FINAL_SUMMARY:'):
            final_summary = final_summary[len('FINAL_SUMMARY:'):].strip()

    # Diagnostic: step outcomes summary
    severity_counts: Dict[str, int] = {}
    for o in step_outcomes:
        severity_counts[o.severity.value] = severity_counts.get(o.severity.value, 0) + 1
    logging.debug(
        f"Step outcomes for '{case_name}': {severity_counts}, "
        f'warning_steps={warning_steps}, objective_achieved={objective_achieved}'
    )

    if status == 'failed':
        logging.info(f"Test case '{case_name}' failed with type: {failure_type}")

    logging.debug(f'=== Agent Worker Completed for {case_name}. ===')

    # Finalize case recording with final status (this calculates metrics)
    case_recorder.finish_case(final_status=status, final_summary=final_summary, user_summary=user_summary)

    # Get recorded case data (contains metrics and step details)
    recorded_case_data = case_recorder.get_case_data()

    # Attach original planned steps (before adaptive recovery modifications)
    # This allows case_synchronizer to correctly populate planned_steps
    if recorded_case_data is not None:
        recorded_case_data['original_planned_steps'] = original_planned_steps

    # Extract metrics and failed step details for reflection phase
    # This enriches case_result without additional file I/O
    metrics = recorded_case_data.get('metrics', {}) if recorded_case_data else {}
    failed_step_details = _extract_failed_step_details(recorded_case_data)

    # Build enriched case_result with detailed metrics for reflection phase
    case_result = {
        'case_name': case_name,
        'case_id': case.get('case_id', ''),
        'final_summary': final_summary,
        'user_summary': user_summary,
        'status': status,
        'failure_type': failure_type,
        # Enriched fields for better reflection/REPLAN decisions
        'metrics': {
            'total_steps': metrics.get('total_steps', 0),
            'passed_steps': metrics.get('passed_steps', 0),
            'failed_steps': metrics.get('failed_steps', 0),
            'warning_steps': metrics.get('warning_steps', 0),
            'skipped_steps': metrics.get('skipped_steps', 0),
            'total_actions': metrics.get('total_actions', 0),
        },
        'failed_step_details': failed_step_details,
    }

    # Include the modified case if dynamic steps were added
    result = {'case_result': case_result}
    if case_modified:
        result['modified_case'] = case

    # Include recorded case data for detailed reporting
    result['recorded_case'] = recorded_case_data

    return result


def _is_objective_achieved(tool_output: str) -> tuple[bool, str]:
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
        logging.debug(f'Error parsing objective achievement signal: {e}')

    return False, ''


def _is_operation_page_agnostic(step_type: str, instruction: str) -> bool:
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
        >>> _is_operation_page_agnostic("Action", "GoBack to previous page")
        True
        >>> _is_operation_page_agnostic("Action", "Tap on element 123")
        False
        >>> _is_operation_page_agnostic("UX_Verify", "Check page content")
        True
    """

    # Priority 1: Direct action type detection (most reliable)
    # Check if instruction contains action type names directly
    for action_type in [ActionType.GO_BACK, ActionType.SLEEP]:
        if action_type in instruction:
            logging.debug(
                f'Page-agnostic action detected via action type: {action_type}'
            )
            return True

    # Priority 2: Keyword matching (handles varied phrasings)
    # Get centralized keywords from action_types module
    # This eliminates code duplication and ensures consistency
    PAGE_AGNOSTIC_KEYWORDS = get_page_agnostic_keywords()

    # Category C: Hybrid operations (available in degraded mode)
    DEGRADED_MODE_TYPES = ['UX_Verify']

    # Check step type - UX_Verify is verified to work on PDF pages (uses screenshot analysis)
    if step_type in DEGRADED_MODE_TYPES:
        return True

    # Check keywords in instruction
    instruction_lower = instruction.lower().replace('_', ' ').replace('-', ' ')
    for keyword in PAGE_AGNOSTIC_KEYWORDS:
        if keyword in instruction_lower:
            logging.debug(f"Page-agnostic operation detected via keyword: '{keyword}'")
            return True

    # Default: DOM-dependent operation (needs to abort)
    return False


def _is_critical_failure_step(tool_output: str, intermediate_output: str = '') -> bool:
    """Check if tool output or intermediate output contains [CRITICAL_ERROR:]
    tag."""
    if not tool_output and not intermediate_output:
        return False

    # Check both outputs for critical error tags
    if '[critical_error:' in tool_output.lower():
        logging.debug('Critical failure detected in tool_output')
        return True

    if '[critical_error:' in intermediate_output.lower():
        logging.debug('Critical failure detected in intermediate_output')
        return True

    return False


# ============================================================================
# Status Determination: LLM-first + Safety Guard helpers
# ============================================================================

_STATUS_PATTERN = re.compile(
    r'STATUS:\s*(passed|failed|warning|pass|fail|success|failure)\b',
    re.IGNORECASE,
)
_STATUS_NORMALIZE = {
    'passed': 'passed', 'pass': 'passed', 'success': 'passed',
    'failed': 'failed', 'fail': 'failed', 'failure': 'failed',
    'warning': 'warning',
}


def _parse_llm_status(llm_output: str) -> Optional[str]:
    """Parse STATUS field from LLM output with tolerant regex + normalization.

    Supports common variants: passed/pass/success → 'passed',
    failed/fail/failure → 'failed', warning → 'warning'.

    Returns:
        Normalized status string ('passed', 'failed', 'warning') or None if not found.
    """
    if not llm_output:
        return None
    match = _STATUS_PATTERN.search(llm_output)
    if match:
        return _STATUS_NORMALIZE.get(match.group(1).lower())
    return None


def _derive_failure_type_from_outcomes(step_outcomes: List[StepOutcome]) -> str:
    """Derive failure_type from step outcomes for reflection skip decisions.

    Returns:
        'critical', 'product_defect', 'infrastructure', or 'recoverable'.
    """
    severities = {o.severity for o in step_outcomes} if step_outcomes else set()
    if StepSeverity.CRITICAL in severities:
        return 'critical'
    if StepSeverity.HARD_FAIL in severities:
        return 'product_defect'
    if StepSeverity.SOFT_FAIL in severities:
        return 'infrastructure'
    return 'recoverable'


def _apply_safety_guard(status: str, step_outcomes: List[StepOutcome]) -> str:
    """Prevent LLM from downplaying CRITICAL/HARD_FAIL severity.

    Rules:
    - CRITICAL exists → must be 'failed' (any other status overridden)
    - HARD_FAIL exists → must be 'failed' (passed/warning overridden)
    """
    severities = {o.severity for o in step_outcomes} if step_outcomes else set()
    if StepSeverity.CRITICAL in severities and status != 'failed':
        logging.warning(
            f"Safety guard: CRITICAL exists, overriding '{status}' → 'failed'"
        )
        return 'failed'
    if StepSeverity.HARD_FAIL in severities and status != 'failed':
        logging.warning(
            f"Safety guard: HARD_FAIL exists, overriding '{status}' → 'failed'"
        )
        return 'failed'
    return status


def _verdict_fallback(
    step_outcomes: List[StepOutcome],
    warning_steps: List[int],
    objective_achieved: bool,
) -> Tuple[str, Optional[str]]:
    """Deterministic fallback when LLM STATUS is missing.

    Returns:
        (status, failure_type) tuple.
    """
    severities = {o.severity for o in step_outcomes} if step_outcomes else set()
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


def _extract_failed_step_details(
    recorded_data: Optional[Dict[str, Any]]
) -> List[Dict[str, Any]]:
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
    failed_details: List[Dict[str, Any]] = []

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


def _is_navigation_instruction(instruction: str) -> bool:
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
    url_patterns = [
        r'https?://[^\s]+',
        r'www\.[^\s]+',
        r'\.com|\.org|\.net|\.edu|\.gov',
    ]

    for pattern in url_patterns:
        if re.search(pattern, instruction_lower):
            return True

    return False


def _detect_llm_provider(model_name: str) -> str:
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

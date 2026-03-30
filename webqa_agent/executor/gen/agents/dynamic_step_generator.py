"""Dynamic step generation and failure recovery for test execution.

This module provides LLM-driven dynamic step generation that operates in two modes:

1. **DOM Change Mode**: Automatically generates test steps when new UI elements
   appear (dropdowns, modals, forms) to improve test coverage of dynamically
   revealed components.

2. **Failure Recovery Mode**: Intelligently adapts the test plan when steps fail
   (element not found, operation timeout, etc.) by analyzing the failure and
   generating alternative instructions.

Extracted from execute_agent.py for modularity and maintainability.
"""

import json
import logging
from typing import Any, Optional

from webqa_agent.executor.gen.utils.content_extraction import (
    extract_json_from_response, format_elements_for_llm)
from webqa_agent.executor.gen.utils.token_timing import (
    MIN_RECOVERY_CONFIDENCE, instrumented_ainvoke)
from webqa_agent.prompts.test_planning_prompts import \
    get_dynamic_step_generation_prompt
from webqa_agent.tools.base import ActionTypes
from webqa_agent.utils.data_flow_reporter import record_data_flow_event

logger = logging.getLogger(__name__)


def _build_case_payload(current_case: Optional[dict]) -> dict:
    """Extract case_id and case_name from current_case for data flow events."""
    if isinstance(current_case, dict):
        return {
            'case_id': current_case.get('case_id', ''),
            'case_name': current_case.get('name', ''),
        }
    return {}


def _build_messages(
    system_content: str,
    user_content: str,
    screenshot: Optional[str] = None,
) -> list[dict]:
    """Build LLM message list, adding screenshot as image_url when present."""
    if screenshot:
        user_block: str | list = [
            {'type': 'text', 'text': user_content},
            {'type': 'image_url', 'image_url': {'url': screenshot, 'detail': 'low'}},
        ]
    else:
        user_block = user_content
    return [
        {'role': 'system', 'content': system_content},
        {'role': 'user', 'content': user_block},
    ]


def _extract_response_text(response: Any) -> str:
    """Extract text content from an LLM response object."""
    return response.content if hasattr(response, 'content') else str(response)


async def generate_dynamic_steps_with_llm(
    dom_diff: Optional[dict] = None,
    last_action: str = '',
    test_objective: str = '',
    executed_steps: int = 0,
    max_steps: int = 8,
    llm: Any = None,
    current_case: Optional[dict] = None,
    screenshot: Optional[str] = None,
    tool_output: Optional[str] = None,
    step_success: bool = True,
    # New parameters for failure recovery mode
    failure_recovery_mode: bool = False,
    failed_instruction: str = '',
    error_message: str = '',
    report_dir: Optional[str] = None,
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
        case_payload = _build_case_payload(current_case)

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
            messages = _build_messages(
                'You are a QA expert analyzing test step failures. Respond with JSON only.',
                failure_prompt,
                screenshot,
            )

            record_data_flow_event(
                stage='dynamic_steps',
                event_type='failure_recovery_request',
                payload={
                    **case_payload,
                    'failed_instruction': failed_instruction,
                    'error_message': error_message,
                    'executed_steps': executed_steps,
                    'messages': messages,
                },
                report_dir=report_dir,
            )
            response, llm_metrics = await instrumented_ainvoke(
                llm,
                messages,
                model_name=getattr(llm, 'model_name', 'unknown-model'),
                capture_metrics=True,
            )
            response_text = _extract_response_text(response)

            # Parse JSON response
            try:
                json_content = extract_json_from_response(response_text)
                result = json.loads(json_content)

                # Validate response
                if not isinstance(result, dict) or 'strategy' not in result:
                    logger.error("LLM response missing required 'strategy' field")
                    return {
                        'strategy': 'abort',
                        'reason': 'Invalid LLM response format',
                        'steps': [],
                        'confidence': 0.0,
                    }

                strategy = result.get('strategy')
                if strategy not in ['retry_modified', 'skip', 'abort']:
                    logger.error(f"Invalid strategy '{strategy}', defaulting to abort")
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
                    logger.warning(
                        f'Invalid confidence {confidence}, defaulting to 0.5'
                    )
                    confidence = 0.5

                # Safety check: low confidence should abort
                if confidence < MIN_RECOVERY_CONFIDENCE:
                    logger.warning(
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
                    if not isinstance(steps, list) or not steps:
                        logger.error('retry_modified strategy missing valid steps')
                        return {
                            'strategy': 'abort',
                            'reason': 'retry_modified requires new instruction',
                            'steps': [],
                            'confidence': 0.0,
                        }

                    # Warn if LLM returns multiple steps (only first will be used)
                    if len(steps) > 1:
                        logger.warning(
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
                        logger.error('retry_modified step has invalid format')
                        return {
                            'strategy': 'abort',
                            'reason': 'Invalid step format in retry_modified',
                            'steps': [],
                            'confidence': 0.0,
                        }

                logger.info(
                    f'Failure recovery strategy: {strategy} (confidence: {confidence:.2f})'
                )
                logger.debug(f"Recovery reason: {result.get('reason', 'N/A')}")
                record_data_flow_event(
                    stage='dynamic_steps',
                    event_type='failure_recovery_response',
                    payload={
                        **case_payload,
                        'strategy': strategy,
                        'reason': result.get('reason', 'No reason provided'),
                        'steps': result.get('steps', []),
                        'confidence': confidence,
                        'llm_metrics': llm_metrics,
                        'raw_response': response_text,
                    },
                    report_dir=report_dir,
                )

                return {
                    'strategy': strategy,
                    'reason': result.get('reason', 'No reason provided'),
                    'steps': result.get('steps', []),
                    'confidence': confidence,
                }

            except json.JSONDecodeError as e:
                logger.error(f'Failed to parse failure recovery LLM response: {e}')
                record_data_flow_event(
                    stage='dynamic_steps',
                    event_type='failure_recovery_response',
                    payload={
                        **case_payload,
                        'strategy': 'abort',
                        'reason': 'JSON parsing failed',
                        'error': str(e),
                        'llm_metrics': llm_metrics,
                        'raw_response': response_text,
                    },
                    report_dir=report_dir,
                )
                return {
                    'strategy': 'abort',
                    'reason': 'JSON parsing failed',
                    'steps': [],
                    'confidence': 0.0,
                }

        except Exception as e:
            logger.error(f'Error in failure recovery mode: {e}')
            record_data_flow_event(
                stage='dynamic_steps',
                event_type='failure_recovery_response',
                payload={
                    **case_payload,
                    'strategy': 'abort',
                    'reason': f'Recovery failed: {str(e)}',
                    'error': str(e),
                },
                report_dir=report_dir,
            )
            return {
                'strategy': 'abort',
                'reason': f'Recovery failed: {str(e)}',
                'steps': [],
                'confidence': 0.0,
            }

    # === DOM CHANGE MODE (Original Logic) ===
    if not dom_diff:
        return {'strategy': 'insert', 'reason': 'No new elements detected', 'steps': []}
    case_payload = _build_case_payload(current_case)

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

        logger.debug(
            f'Requesting LLM to generate dynamic steps for {len(new_elements)} new elements'
        )

        messages = _build_messages(system_prompt, user_prompt, screenshot)

        record_data_flow_event(
            stage='dynamic_steps',
            event_type='dom_change_request',
            payload={
                **case_payload,
                'last_action': last_action,
                'step_success': step_success,
                'new_elements_count': len(new_elements),
                'messages': messages,
            },
            report_dir=report_dir,
        )
        response, llm_metrics = await instrumented_ainvoke(
            llm,
            messages,
            model_name=getattr(llm, 'model_name', 'unknown-model'),
            capture_metrics=True,
        )

        response_text = _extract_response_text(response)

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
                analysis_dict = analysis if isinstance(analysis, dict) else {}

                _QAG_FIELDS = [
                    'q1_can_complete_alone',
                    'q2_different_aspects',
                    'q3_remaining_redundant',
                    'q4_abstraction_gap',
                ]
                validated_analysis = {}
                for field in _QAG_FIELDS:
                    value = analysis_dict.get(field, False)
                    if not isinstance(value, bool):
                        logger.debug(f'Invalid {field} {value}, defaulting to False')
                        value = False
                    validated_analysis[field] = value

                # Validate strategy value
                if strategy not in ['insert', 'replace']:
                    logger.warning(
                        f"Invalid strategy '{strategy}', defaulting to 'insert'"
                    )
                    strategy = 'insert'

                # Validate and limit step count
                valid_steps = []
                if isinstance(steps, list):
                    for step in steps[:max_steps]:
                        if isinstance(step, dict) and (
                            'action' in step or 'verify' in step
                        ):
                            valid_steps.append(step)

                # Enhanced logging with QAG analysis data
                logger.info(
                    f"Generated {len(valid_steps)} dynamic steps with strategy '{strategy}' from {len(new_elements)} new elements"
                )

                logger.debug(f'Strategy reason: {reason}')
                if analysis:
                    logger.debug(f'Enhanced QAG Analysis: {validated_analysis}')

                # Return enhanced result with QAG analysis
                result_data = {
                    'strategy': strategy,
                    'reason': reason,
                    'steps': valid_steps,
                }

                # Include Enhanced QAG analysis if provided
                if analysis:
                    result_data['analysis'] = validated_analysis
                record_data_flow_event(
                    stage='dynamic_steps',
                    event_type='dom_change_response',
                    payload={
                        **case_payload,
                        'strategy': strategy,
                        'reason': reason,
                        'steps': valid_steps,
                        'analysis': result_data.get('analysis'),
                        'llm_metrics': llm_metrics,
                        'raw_response': response_text,
                    },
                    report_dir=report_dir,
                )

                return result_data
            else:
                logger.warning(
                    'LLM response missing required fields (strategy, steps)'
                )
                record_data_flow_event(
                    stage='dynamic_steps',
                    event_type='dom_change_response',
                    payload={
                        **case_payload,
                        'strategy': 'insert',
                        'reason': 'Invalid response format',
                        'steps': [],
                        'llm_metrics': llm_metrics,
                        'raw_response': response_text,
                    },
                    report_dir=report_dir,
                )
                return {
                    'strategy': 'insert',
                    'reason': 'Invalid response format',
                    'steps': [],
                }

        except json.JSONDecodeError as e:
            logger.warning(f'Failed to parse LLM response as JSON: {e}')
            logger.debug(f'Raw LLM response: {response_text[:500]}...')
            logger.debug(
                f'Extracted JSON content: {extract_json_from_response(response_text)[:500]}...'
            )
            record_data_flow_event(
                stage='dynamic_steps',
                event_type='dom_change_response',
                payload={
                    **case_payload,
                    'strategy': 'insert',
                    'reason': 'JSON parsing failed',
                    'steps': [],
                    'error': str(e),
                    'llm_metrics': llm_metrics,
                    'raw_response': response_text,
                },
                report_dir=report_dir,
            )
            return {'strategy': 'insert', 'reason': 'JSON parsing failed', 'steps': []}

    except Exception as e:
        logger.error(f'Error generating dynamic steps with LLM: {e}')
        record_data_flow_event(
            stage='dynamic_steps',
            event_type='dom_change_response',
            payload={
                **_build_case_payload(current_case),
                'strategy': 'insert',
                'reason': f'Generation failed: {str(e)}',
                'steps': [],
                'error': str(e),
            },
            report_dir=report_dir,
        )
        return {
            'strategy': 'insert',
            'reason': f'Generation failed: {str(e)}',
            'steps': [],
        }

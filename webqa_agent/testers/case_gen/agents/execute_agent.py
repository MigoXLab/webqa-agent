"""This module defines the agent worker node for the LangGraph-based UI testing
application.

The agent worker is responsible for executing a single test case.
"""
import asyncio
import datetime
import json
import logging
import re

from langchain.agents import AgentExecutor, create_tool_calling_agent
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage
from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder
from langchain_openai import ChatOpenAI

from webqa_agent.crawler.deep_crawler import DeepCrawler
from webqa_agent.testers.case_gen.prompts.agent_prompts import get_execute_system_prompt
from webqa_agent.testers.case_gen.prompts.planning_prompts import get_dynamic_step_generation_prompt
from webqa_agent.testers.case_gen.tools.element_action_tool import UIAssertTool, UITool
from webqa_agent.testers.case_gen.tools.ux_tool import UIUXViewportTool
from webqa_agent.testers.case_gen.utils.case_recorder import CentralCaseRecorder
from webqa_agent.testers.case_gen.utils.message_converter import convert_intermediate_steps_to_messages
from webqa_agent.utils.log_icon import icon

LONG_STEPS = 30
RETRY_STABILIZATION_DELAY = 1.0
MIN_RECOVERY_CONFIDENCE = 0.7

# ============================================================================
# Critical Failure Detection Patterns
# ============================================================================

# Literal patterns for exact substring matching (backward compatible)
CRITICAL_LITERAL_PATTERNS = [
    "element not found",
    "cannot find", 
    "page crashed",
    "permission denied",
    "access denied",
    "network timeout",
    "browser error",
    "navigation failed",
    "session expired",
    "server error",
    "connection timeout",
    "unable to load",
    "page not accessible",
    "critical error",
    "missing locator",
    "not found in the buffer",
    "could not be retrieved",
    "failed due to a missing",
    "dropdown options could not be retrieved",
]

# Regex patterns for flexible matching
CRITICAL_REGEX_PATTERNS = [
    r"not found in\s+.*buffer",
    r"failed due to\s+.*missing",
    r"locator.*not.*found",
    r"element.*not.*available", 
    r"missing.*for.*action",
    r"missing.*parameter",
    r"element with id.*not found",
]

# Pre-compile regex for performance
CRITICAL_REGEX = re.compile(
    '|'.join(CRITICAL_REGEX_PATTERNS),
    re.IGNORECASE
)

# ============================================================================
# Dynamic Step Generation Helper Functions
# ============================================================================

def extract_json_from_response(response_text: str) -> str:
    """Extract JSON content from markdown-formatted or plain text response
    
    Args:
        response_text: Raw response text from LLM that may contain JSON in markdown blocks
        
    Returns:
        Extracted JSON string ready for parsing
    """
    if not response_text:
        return ""
    
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


def safe_get_intermediate_step(result: dict, index: int = 0, subindex: int = 1, default: str = "") -> str:
    """Safely access intermediate_steps to prevent list index out of range errors.

    Args:
        result: The result dictionary from agent execution
        index: The index of the intermediate step (default: 0)
        subindex: The subindex within the step tuple/list (default: 1)
        default: Default value to return if access fails (default: "")

    Returns:
        The intermediate step content or default value
    """
    steps = result.get('intermediate_steps', [])
    if isinstance(steps, list) and len(steps) > index:
        step = steps[index]
        if isinstance(step, (list, tuple)) and len(step) > subindex:
            return step[subindex]
    return default


def extract_dom_diff_from_output(tool_output: str) -> dict:
    """Extract DOM diff information from tool output"""
    try:
        # Find DOM_DIFF_DETECTED marker
        if "DOM_DIFF_DETECTED:" not in tool_output:
            return {}
        
        # Extract JSON portion
        start_marker = "DOM_DIFF_DETECTED:"
        start_idx = tool_output.find(start_marker)
        if start_idx == -1:
            return {}
        
        start_idx += len(start_marker)
        # Find next line or end of text
        end_idx = tool_output.find("\n\n", start_idx)
        if end_idx == -1:
            json_str = tool_output[start_idx:].strip()
        else:
            json_str = tool_output[start_idx:end_idx].strip()
        
        return json.loads(json_str)
    except Exception as e:
        logging.debug(f"Failed to extract DOM diff from tool output: {e}")
        return {}


def format_elements_for_llm(dom_diff: dict) -> list[dict]:
    """Format DOM diff information, extracting key information for LLM understanding"""
    formatted = []
    for elem_id, elem_data in dom_diff.items():
        # Get key element information
        tag_name = elem_data.get("tagName", "").lower()
        inner_text = elem_data.get("innerText", "")
        attributes = elem_data.get("attributes", {})
        
        # Build simplified element description
        formatted_elem = {
            "id": elem_id,
            "type": tag_name,
            "text": inner_text[:100] if inner_text else "",  # Limit text length
            "position": {
                "x": elem_data.get("center_x"),
                "y": elem_data.get("center_y")
            }
        }
        
        # Add important attribute information
        important_attrs = {}
        if attributes:
            # Define comprehensive attribute whitelist
            navigation_attrs = ['href', 'target', 'rel', 'download']
            form_attrs = ['type', 'placeholder', 'value', 'name', 'required', 'disabled']
            semantic_attrs = ['role', 'aria-label', 'aria-describedby', 'aria-expanded']
            
            for key, value in attributes.items():
                # Include whitelisted attributes
                if key in ['class', 'id'] + navigation_attrs + form_attrs + semantic_attrs:
                    important_attrs[key] = value
                # Include data-* attributes (often contain behavior info)
                elif key.startswith('data-'):
                    # Limit length to prevent token explosion
                    important_attrs[key] = value[:200] if isinstance(value, str) and len(value) > 200 else value
                # Include style if it indicates visibility/interactivity
                elif key == 'style' and isinstance(value, str) and ('display' in value or 'visibility' in value):
                    important_attrs[key] = value[:200] + "..." if len(value) > 200 else value
        
        if important_attrs:
            formatted_elem["attributes"] = important_attrs
        
        formatted.append(formatted_elem)
    
    return formatted


async def generate_dynamic_steps_with_llm(
    dom_diff: dict = None,
    last_action: str = "",
    test_objective: str = "",
    executed_steps: int = 0,
    max_steps: int = 5,
    llm: any = None,
    current_case: dict = None,
    screenshot: str = None,
    tool_output: str = None,
    step_success: bool = True,
    # New parameters for failure recovery mode
    failure_recovery_mode: bool = False,
    failed_instruction: str = "",
    error_message: str = ""
) -> dict:
    """Generate dynamic test steps or recover from failed steps using LLM

    This function serves two purposes:
    1. DOM Change Mode (failure_recovery_mode=False): Generate new test steps for newly appeared UI elements
    2. Failure Recovery Mode (failure_recovery_mode=True): Adapt test plan when steps fail due to stale DOM

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
            return {"strategy": "abort", "reason": "Missing failure context", "steps": [], "confidence": 0.0}

        try:
            # Build failure recovery prompt
            all_steps = current_case.get("steps", []) if current_case else []
            remaining_steps = all_steps[executed_steps:] if executed_steps < len(all_steps) else []
            executed_steps_detail = all_steps[:executed_steps] if executed_steps > 0 else []

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

## Response Format (JSON only):

```json
{{
  "strategy": "retry_modified|skip|abort",
  "steps": [{{"action": "alternative instruction"}}],
  "reason": "detailed explanation of why this strategy was chosen",
  "confidence": 0.85
}}
```

**Important**:
- For retry_modified: steps array must contain exactly one step with the new instruction
- For skip/abort: steps array should be empty []
- confidence should be 0.0-1.0 (if < 0.7, system may override to abort for safety)
"""

            # Call LLM with multi-modal context
            if screenshot:
                messages = [
                    {"role": "system", "content": "You are a QA expert analyzing test step failures. Respond with JSON only."},
                    {
                        "role": "user",
                        "content": [
                            {"type": "text", "text": failure_prompt},
                            {"type": "image_url", "image_url": {"url": screenshot, "detail": "low"}}
                        ]
                    }
                ]
            else:
                messages = [
                    {"role": "system", "content": "You are a QA expert analyzing test step failures. Respond with JSON only."},
                    {"role": "user", "content": failure_prompt}
                ]

            response = await llm.ainvoke(messages)
            response_text = response.content if hasattr(response, 'content') else str(response)

            # Parse JSON response
            try:
                json_content = extract_json_from_response(response_text)
                result = json.loads(json_content)

                # Validate response
                if not isinstance(result, dict) or "strategy" not in result:
                    logging.error("LLM response missing required 'strategy' field")
                    return {"strategy": "abort", "reason": "Invalid LLM response format", "steps": [], "confidence": 0.0}

                strategy = result.get("strategy")
                if strategy not in ["retry_modified", "skip", "abort"]:
                    logging.error(f"Invalid strategy '{strategy}', defaulting to abort")
                    return {"strategy": "abort", "reason": f"Invalid strategy returned: {strategy}", "steps": [], "confidence": 0.0}

                # Validate confidence
                confidence = result.get("confidence", 0.5)
                if not isinstance(confidence, (int, float)) or confidence < 0 or confidence > 1:
                    logging.warning(f"Invalid confidence {confidence}, defaulting to 0.5")
                    confidence = 0.5

                # Safety check: low confidence should abort
                if confidence < MIN_RECOVERY_CONFIDENCE:
                    logging.warning(f"Low confidence ({confidence}) in recovery strategy, overriding to abort")
                    return {
                        "strategy": "abort",
                        "reason": f"Low confidence in recovery. Original suggestion: {result.get('reason', 'N/A')}",
                        "steps": [],
                        "confidence": confidence
                    }

                # Validate steps for retry_modified
                if strategy == "retry_modified":
                    steps = result.get("steps", [])
                    if not steps or not isinstance(steps, list) or len(steps) == 0:
                        logging.error("retry_modified strategy missing valid steps")
                        return {"strategy": "abort", "reason": "retry_modified requires new instruction", "steps": [], "confidence": 0.0}

                    # Validate step format
                    valid_step = steps[0] if isinstance(steps[0], dict) and ("action" in steps[0] or "verify" in steps[0]) else None
                    if not valid_step:
                        logging.error("retry_modified step has invalid format")
                        return {"strategy": "abort", "reason": "Invalid step format in retry_modified", "steps": [], "confidence": 0.0}

                logging.info(f"Failure recovery strategy: {strategy} (confidence: {confidence:.2f})")
                logging.debug(f"Recovery reason: {result.get('reason', 'N/A')}")

                return {
                    "strategy": strategy,
                    "reason": result.get("reason", "No reason provided"),
                    "steps": result.get("steps", []),
                    "confidence": confidence
                }

            except json.JSONDecodeError as e:
                logging.error(f"Failed to parse failure recovery LLM response: {e}")
                return {"strategy": "abort", "reason": "JSON parsing failed", "steps": [], "confidence": 0.0}

        except Exception as e:
            logging.error(f"Error in failure recovery mode: {e}")
            return {"strategy": "abort", "reason": f"Recovery failed: {str(e)}", "steps": [], "confidence": 0.0}

    # === DOM CHANGE MODE (Original Logic) ===
    if not dom_diff:
        return {"strategy": "insert", "reason": "No new elements detected", "steps": []}
    
    try:
        # Prepare new element information
        new_elements = format_elements_for_llm(dom_diff)
        
        if not new_elements:
            return {"strategy": "insert", "reason": "No meaningful elements to test", "steps": []}
        
        # Build system prompt
        system_prompt = get_dynamic_step_generation_prompt()
        
        # Prepare test case context for better coherence
        test_case_context = ""
        if current_case and "steps" in current_case:
            all_steps = current_case["steps"]
            executed_steps_detail = all_steps[:executed_steps] if executed_steps > 0 else []
            remaining_steps = all_steps[executed_steps:] if executed_steps < len(all_steps) else []
            
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
        visual_context_section = ""
        if screenshot:
            execution_context = "AFTER the execution of the last action" if step_success else "AFTER the attempted execution of the last action"
            visual_context_section = f"""
## Current Page Visual Context
The attached screenshot shows the current state of the page {execution_context}.
Use this visual information along with the DOM diff to understand the complete UI state.
"""

        # Build context based on actual execution result
        if step_success:
            action_status = f"✅ SUCCESSFULLY EXECUTED: \"{last_action}\""
            status_context = "The above action has been completed successfully. Do NOT re-plan or duplicate this action."
            execution_description = "After the successful action execution"
        else:
            action_status = f"⚠️ FAILED/PARTIAL EXECUTION: \"{last_action}\""
            status_context = "The above action failed or partially succeeded. Consider recovery steps or alternative approaches."
            execution_description = "After the failed/partial action execution"

        # Include tool output for better context
        tool_output_section = ""
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
        
        logging.debug(f"Requesting LLM to generate dynamic steps for {len(new_elements)} new elements")
        
        # Call LLM with proper message structure
        if screenshot:
            # Multi-modal call with screenshot
            messages = [
                {"role": "system", "content": system_prompt},
                {
                    "role": "user", 
                    "content": [
                        {"type": "text", "text": user_prompt},
                        {
                            "type": "image_url",
                            "image_url": {"url": screenshot, "detail": "low"}
                        }
                    ]
                }
            ]
        else:
            # Text-only call with proper message structure
            messages = [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt}
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
            if isinstance(result, dict) and "strategy" in result and "steps" in result:
                strategy = result.get("strategy", "insert")
                reason = result.get("reason", "No reason provided")
                steps = result.get("steps", [])
                
                # Extract and validate analysis fields (Enhanced QAG format)
                analysis = result.get("analysis", {})
                q1_can_complete_alone = analysis.get("q1_can_complete_alone", False) if isinstance(analysis, dict) else False
                q2_different_aspects = analysis.get("q2_different_aspects", False) if isinstance(analysis, dict) else False
                q3_remaining_redundant = analysis.get("q3_remaining_redundant", False) if isinstance(analysis, dict) else False
                q4_abstraction_gap = analysis.get("q4_abstraction_gap", False) if isinstance(analysis, dict) else False
                
                # Validate strategy value
                if strategy not in ["insert", "replace"]:
                    logging.warning(f"Invalid strategy '{strategy}', defaulting to 'insert'")
                    strategy = "insert"
                
                # Validate QAG analysis fields
                if not isinstance(q1_can_complete_alone, bool):
                    logging.debug(f"Invalid q1_can_complete_alone {q1_can_complete_alone}, defaulting to False")
                    q1_can_complete_alone = False
                
                if not isinstance(q2_different_aspects, bool):
                    logging.debug(f"Invalid q2_different_aspects {q2_different_aspects}, defaulting to False")
                    q2_different_aspects = False
                
                if not isinstance(q3_remaining_redundant, bool):
                    logging.debug(f"Invalid q3_remaining_redundant {q3_remaining_redundant}, defaulting to False")
                    q3_remaining_redundant = False
                
                if not isinstance(q4_abstraction_gap, bool):
                    logging.debug(f"Invalid q4_abstraction_gap {q4_abstraction_gap}, defaulting to False")
                    q4_abstraction_gap = False
                
                # Validate and limit step count
                valid_steps = []
                if isinstance(steps, list):
                    for step in steps[:max_steps]:
                        if isinstance(step, dict) and ("action" in step or "verify" in step):
                            valid_steps.append(step)
                
                # Enhanced logging with QAG analysis data
                logging.info(f"Generated {len(valid_steps)} dynamic steps with strategy '{strategy}' from {len(new_elements)} new elements")
                
                logging.debug(f"Strategy reason: {reason}")
                if analysis:
                    logging.debug(f"Enhanced QAG Analysis: q1_can_complete_alone={q1_can_complete_alone}, q2_different_aspects={q2_different_aspects}, q3_remaining_redundant={q3_remaining_redundant}, q4_abstraction_gap={q4_abstraction_gap}")
                
                # Return enhanced result with QAG analysis
                result_data = {
                    "strategy": strategy,
                    "reason": reason,
                    "steps": valid_steps
                }
                
                # Include Enhanced QAG analysis if provided
                if analysis:
                    result_data["analysis"] = {
                        "q1_can_complete_alone": q1_can_complete_alone,
                        "q2_different_aspects": q2_different_aspects,
                        "q3_remaining_redundant": q3_remaining_redundant,
                        "q4_abstraction_gap": q4_abstraction_gap
                    }
                
                return result_data
            else:
                logging.warning("LLM response missing required fields (strategy, steps)")
                return {"strategy": "insert", "reason": "Invalid response format", "steps": []}
                
        except json.JSONDecodeError as e:
            logging.warning(f"Failed to parse LLM response as JSON: {e}")
            logging.debug(f"Raw LLM response: {response_text[:500]}...")
            logging.debug(f"Extracted JSON content: {extract_json_from_response(response_text)[:500]}...")
            return {"strategy": "insert", "reason": "JSON parsing failed", "steps": []}
        
    except Exception as e:
        logging.error(f"Error generating dynamic steps with LLM: {e}")
        return {"strategy": "insert", "reason": f"Generation failed: {str(e)}", "steps": []}


# The node function that will be used in the graph
async def agent_worker_node(state: dict, config: dict) -> dict:
    """Dynamically creates and invokes the execution agent for a single test
    case.

    This node is mapped over the list of test cases.
    """
    case = state["test_case"]
    case_name = case.get("name", "Unnamed Test Case")
    completed_cases = state.get("completed_cases", [])

    logging.debug(f"=== Starting Agent Worker for Test Case: {case_name} ===")
    logging.debug(f"Test case objective: {case.get('objective', 'Not specified')}")
    logging.debug(f"Test case steps count: {len(case.get('steps', []))}")
    logging.debug(f"Preamble actions count: {len(case.get('preamble_actions', []))}")
    logging.debug(f"Previously completed cases: {len(completed_cases)}")

    ui_tester_instance = config["configurable"]["ui_tester_instance"]

    # Create an independent case recorder (decoupled from UITester store)
    case_recorder = CentralCaseRecorder()
    case_recorder.start_case(case_name, case_data=case)
    
    # Expose recorder to UITester so it can record action/verify steps automatically
    ui_tester_instance.central_case_recorder = case_recorder

    # Note: case tracking is managed by execute_single_case node via start_case/finish_case
    # No need to set test name here as it's already handled

    system_prompt_string = get_execute_system_prompt(case)
    logging.debug(f"Generated system prompt length: {len(system_prompt_string)} characters")

    llm_config = ui_tester_instance.llm.llm_config

    logging.info(f"{icon['running']} Agent worker for test case started: {case_name}")

    # Use ChatOpenAI directly for better integration with LangChain
    llm_kwargs = {
        "model": llm_config.get("model", "gpt-4o-mini"),
        "api_key": llm_config.get("api_key"),
        "base_url": llm_config.get("base_url"),
    }
    # default temperature 0.1 unless user explicitly sets another value
    cfg_temp = llm_config.get("temperature", 0.1)
    llm_kwargs["temperature"] = cfg_temp
    cfg_top_p = llm_config.get("top_p")
    if cfg_top_p is not None:
        llm_kwargs["top_p"] = cfg_top_p

    llm = ChatOpenAI(**llm_kwargs)
    logging.debug(
        f"LangGraph LLM params resolved: model={llm_kwargs.get('model')}, base_url={llm_kwargs.get('base_url')}, "
        f"temperature={llm_kwargs.get('temperature', '0.1')}, top_p={llm_kwargs.get('top_p', 'unset')}"
    )
    logging.debug(f"LLM configured: {llm_config.get('model')} at {llm_config.get('base_url')}")

    # Instantiate tools with correct parameters
    # Note: All tools now use ui_tester_instance to dynamically get page,
    # which ensures correct page reference after get_new_page operations
    tools = [
        UITool(ui_tester_instance=ui_tester_instance),
        UIAssertTool(ui_tester_instance=ui_tester_instance),
        UIUXViewportTool(ui_tester_instance=ui_tester_instance, llm_config=llm_config, case_recorder=case_recorder),
    ]
    logging.debug(f"Tools initialized: {[tool.name for tool in tools]}")

    # The prompt now includes the system message
    prompt = ChatPromptTemplate.from_messages(
        [
            ("system", system_prompt_string),
            MessagesPlaceholder(variable_name="messages"),
            MessagesPlaceholder(variable_name="agent_scratchpad"),
        ]
    )

    # Create the agent
    agent = create_tool_calling_agent(llm, tools, prompt)
    agent_executor = AgentExecutor(agent=agent, tools=tools, verbose=False, max_iterations=5, return_intermediate_steps=True)
    logging.debug("AgentExecutor created successfully")

    # --- Execute Preamble Actions to Restore State ---
    preamble_actions = case.get("preamble_actions", [])
    if preamble_actions:
        logging.debug(f"=== Executing {len(preamble_actions)} Preamble Actions ===")
        preamble_messages: list[BaseMessage] = [
            HumanMessage(
                content="The test has started. Before the main test steps, I need to perform some setup actions to restore the UI state. Please execute the first preamble action."
            )
        ]

        for i, step in enumerate(preamble_actions):
            if isinstance(step, dict):
                instruction_to_execute = step.get("action")
            else:
                instruction_to_execute = step
            if not instruction_to_execute:
                logging.warning(f"Preamble action {i+1} has no instruction, skipping")
                continue

            # Smart check: Skip preamble action if it's a navigation instruction and already on target page
            if case.get("reset_session", False) and _is_navigation_instruction(instruction_to_execute):
                # Check if already on target page
                try:
                    page = ui_tester_instance.driver.get_page()
                    current_url = page.url
                    target_url = case.get("url", "")

                    def normalize_url(u):
                        from urllib.parse import urlparse

                        try:
                            parsed = urlparse(u)
                            # Handle domain variations: remove www prefix, unify to lowercase
                            netloc = parsed.netloc.lower()
                            if netloc.startswith("www."):
                                netloc = netloc[4:]  # Remove www.

                            # Standardize path: remove trailing slash
                            path = parsed.path.rstrip("/")

                            # Build standardized URL
                            normalized = f"{parsed.scheme}://{netloc}{path}"
                            return normalized
                        except Exception:
                            # If parsing fails, return lowercase form of original URL
                            return u.lower()

                    # More flexible URL matching
                    def extract_domain(u):
                        try:
                            from urllib.parse import urlparse

                            parsed = urlparse(u)
                            domain = parsed.netloc.lower()
                            if domain.startswith("www."):
                                domain = domain[4:]
                            return domain
                        except Exception:
                            return ""

                    def extract_path(u):
                        try:
                            from urllib.parse import urlparse

                            parsed = urlparse(u)
                            return parsed.path.rstrip("/")
                        except Exception:
                            return ""

                    current_normalized = normalize_url(current_url)
                    target_normalized = normalize_url(target_url)

                    # Basic standardized matching
                    if current_normalized == target_normalized:
                        logging.debug("Skipping preamble navigation action - already on target page (normalized match)")
                        continue

                    # More flexible domain and path matching
                    current_domain = extract_domain(current_url)
                    target_domain = extract_domain(target_url)
                    current_path = extract_path(current_url)
                    target_path = extract_path(target_url)

                    if current_domain == target_domain and (
                        current_path == target_path
                        or current_path == ""
                        and target_path == ""
                        or current_path == "/"
                        and target_path == ""
                        or current_path == ""
                        and target_path == "/"
                    ):
                        logging.debug(
                            f"Skipping preamble navigation action - domain and path match detected ({current_domain}{current_path})"
                        )
                        continue

                except Exception as e:
                    logging.warning(f"Could not check current URL for preamble action: {e}, proceeding with execution")

            logging.info(f"Executing preamble action {i+1}/{len(preamble_actions)}: {instruction_to_execute}")
            preamble_messages.append(
                HumanMessage(content=f"Now, execute this preamble action: {instruction_to_execute}")
            )

            try:
                # Use a simple invoke, as preamble steps should be straightforward
                logging.debug(f"Executing preamble action {i+1} - Calling Agent...")
                start_time = datetime.datetime.now()

                result = await agent_executor.ainvoke({"messages": preamble_messages})

                preamble_messages = result.get("messages", preamble_messages)
                # AgentExecutor may not return messages, check for intermediate_steps instead
                if "intermediate_steps" in result and result["intermediate_steps"]:
                    # Convert intermediate steps to proper message format
                    intermediate_messages = convert_intermediate_steps_to_messages(result["intermediate_steps"])
                    preamble_messages.extend(intermediate_messages)

                end_time = datetime.datetime.now()
                duration = (end_time - start_time).total_seconds()

                tool_output = result.get("output", "")
                logging.debug(f"Preamble action {i+1} completed in {duration:.2f} seconds")
                logging.debug(f"Preamble action {i+1} result: {tool_output[:200]}...")
                preamble_messages.append(AIMessage(content=tool_output))

                # Safely check for failure in intermediate steps
                intermediate_output = safe_get_intermediate_step(result, index=0, subindex=1, default="")
                if "[failure]" in intermediate_output.lower():
                    final_summary = f"FINAL_SUMMARY: Preamble action '{instruction_to_execute}' failed, cannot proceed with the test case. Error: {tool_output}"
                    case_result = {"case_name": case_name, "final_summary": final_summary, "status": "failed"}
                    logging.error(f"Preamble action {i+1} failed, aborting test case")
                    return {"case_result": case_result, "current_case_steps": []}

                logging.debug(f"Preamble action {i+1} completed successfully")
            except Exception as e:
                logging.error(f"Exception during preamble action {i+1}: {str(e)}")
                final_summary = f"FINAL_SUMMARY: Preamble action '{instruction_to_execute}' raised exception: {str(e)}"
                case_result = {"case_name": case_name, "final_summary": final_summary, "status": "failed"}
                return {"case_result": case_result, "current_case_steps": []}

        logging.debug("=== All Preamble Actions Completed Successfully ===")

    # --- Main Execution Loop ---
    logging.debug("=== Starting Main Test Steps Execution ===")
    messages: list[BaseMessage] = [
        HumanMessage(
            content="The test has started. I will provide you with one instruction at a time. Please execute the action or assertion described in each instruction."
        )
    ]
    final_summary = "No summary provided."
    case_steps = case.get("steps", [])  # Get reference to steps list
    total_steps = len(case_steps)
    failed_steps = []  # Track failed steps for summary generation
    warning_steps = []  # Track steps with warnings (e.g., UX issues)
    case_modified = False  # Track if case was modified with dynamic steps
    dynamic_generation_count = 0  # Track how many times dynamic generation occurred
    dom_diff_cache = []
    step_retry_tracker = {}  # Track retry attempts per step for adaptive recovery

    i = 0
    while i < len(case_steps):
        step = case_steps[i]
        instruction_to_execute = step.get("action") or step.get("verify") or step.get("ux_verify")
        # step_type = "Action" if step.get("action") else "Assertion"
        if step.get("action"):
            step_type = "Action"
        elif step.get("verify"):
            step_type = "Assertion"
        elif step.get("ux_verify"):
            step_type = "UX_Verify"
        else:
            logging.warning(f"Unknown step type: {step}")
            step_type = "Assertion"

        logging.info(f"Executing Step {i+1}/{total_steps} ({step_type}), step instruction: {instruction_to_execute}")

        # Define instruction templates for variation
        instruction_templates = [
            "Now, execute this instruction: {instruction}",
            "Please proceed with the following step: {instruction}",
            "The next task is to perform this action: {instruction}",
            "Execute the instruction as follows: {instruction}",
        ]
        # Vary the instruction prompt to avoid repetitive context
        prompt_template = instruction_templates[i % len(instruction_templates)]
        formatted_instruction = prompt_template.format(instruction=instruction_to_execute)

        # --- Multi-Modal Context Generation ---
        page = ui_tester_instance.driver.get_page()
        dp = DeepCrawler(page)
        await dp.crawl(highlight=True, viewport_only=True)
        screenshot = await ui_tester_instance._actions.b64_page_screenshot(
            file_name="agent_step_vision", save_to_log=False
        )
        await dp.remove_marker()
        logging.debug("Generated highlighted screenshot for the agent.")
        # ------------------------------------

        # Create a new message with the current step's instruction and visual context
        step_content = [{"type": "text", "text": formatted_instruction}]
        if screenshot:
            step_content.append({
                "type": "image_url",
                "image_url": {"url": f"{screenshot}", "detail": "low"},
            })
        step_message = HumanMessage(content=step_content)

        # The agent's history includes all prior messages
        current_messages = messages + [step_message]

        # --- History Pruning for Token Optimization ---
        # Keep the full text history but only the most recent image to save tokens.
        pruned_messages = []
        # The last message is the one we just added and should always keep its image.
        for j, msg in enumerate(current_messages):
            # Check if it's not the last message
            if j < len(current_messages) - 1 and isinstance(msg, HumanMessage) and isinstance(msg.content, list):
                # It's an older multi-modal message, prune the image.
                text_content = next((item["text"] for item in msg.content if item["type"] == "text"), "")
                pruned_messages.append(HumanMessage(content=text_content))
            else:
                # It's an AI message, a simple HumanMessage, or the last message; keep as is.
                pruned_messages.append(msg)
        logging.debug(
            f"Pruned message history for token optimization. Original length: {len(current_messages)}, Pruned length: {len(pruned_messages)}"
        )
        # ---------------------------------------------

        # --- Tool Choice Masking ---
        tool_choice = None
        if step_type == "Action":
            tool_choice = {"type": "function", "function": {"name": "execute_ui_action"}}
            logging.debug("Forcing tool choice: execute_ui_action")
        elif step_type == "Assertion":
            tool_choice = {"type": "function", "function": {"name": "execute_ui_assertion"}}
            logging.debug("Forcing tool choice: execute_ui_assertion")
        elif step_type == "UX_Verify":
            tool_choice = {"type": "function", "function": {"name": "execute_ux_verify"}}
            logging.debug("Forcing tool choice: execute_ux_verify")
        # -------------------------

        try:
            # The agent's history includes all prior messages
            logging.debug(f"Step {i+1} - Calling Agent to execute {step_type}...")
            start_time = datetime.datetime.now()

            result = await agent_executor.ainvoke(
                {"messages": pruned_messages},
                config={"configurable": {"tool_choice": tool_choice}} if tool_choice else {},
            )

            end_time = datetime.datetime.now()
            duration = (end_time - start_time).total_seconds()

            messages = result.get("messages", pruned_messages)

            # Handle intermediate_steps if available (when return_intermediate_steps=True)
            if "intermediate_steps" in result and result["intermediate_steps"]:
                # Convert intermediate steps to proper message format
                intermediate_messages = convert_intermediate_steps_to_messages(result["intermediate_steps"])
                # Append intermediate messages to maintain proper conversation history
                messages.extend(intermediate_messages)
                logging.debug(f"Step {i+1} added {len(intermediate_messages)} intermediate messages")


            tool_output = result.get("output", "")

            logging.debug(f"Step {i+1} {step_type} completed in {duration:.2f} seconds")
            logging.debug(f"Step {i+1} tool output: {tool_output}")
            messages.append(AIMessage(content=tool_output))
            
            # Check for warnings in the tool output (e.g., UX issues)
            # Check both agent output and raw tool result from intermediate steps
            intermediate_output = safe_get_intermediate_step(result, index=0, subindex=1, default="")
            combined_output = f"{tool_output}\n{intermediate_output}"
            if "[warning]" in combined_output.lower():
                warning_steps.append(i + 1)
                logging.info(f"Step {i+1} completed with warnings (e.g., UX issues detected)")

            is_failure = "[failure]" in intermediate_output.lower() or "failed" in tool_output.lower()

            # Check if this is an ELEMENT_NOT_FOUND error (potentially recoverable)
            is_element_not_found = (
                "[CRITICAL_ERROR:ELEMENT_NOT_FOUND]" in tool_output or
                "element not found" in tool_output.lower()
            )

            if is_failure:
                # Priority 1: Try recovery for ELEMENT_NOT_FOUND (recoverable critical error)
                if is_element_not_found:
                    # Get dynamic config to check if adaptive recovery is enabled
                    dynamic_config = state.get("dynamic_step_generation", {"enabled": False})

                    if dynamic_config.get("enabled", False):
                        # Adaptive recovery enabled
                        retry_key = f"step_{i}"
                        retry_count = step_retry_tracker.get(retry_key, 0)

                        if retry_count == 0:
                            # Layer 1: Simple retry after page stabilization
                            logging.info(f"Step {i+1} element not found, attempting Layer 1 recovery (simple retry after stabilization)")
                            await asyncio.sleep(RETRY_STABILIZATION_DELAY)  # Let page stabilize
                            step_retry_tracker[retry_key] = 1
                            # Don't increment i, will retry same step
                            continue

                        elif retry_count == 1:
                            # Layer 2: LLM-based adaptive replanning
                            logging.info(f"Step {i+1} failed twice, attempting Layer 2 recovery (LLM adaptive replanning)")

                            # Get current page screenshot for LLM analysis
                            try:
                                recovery_screenshot = await ui_tester_instance._actions.b64_page_screenshot(
                                    file_name="recovery_screenshot", save_to_log=False
                                )
                            except Exception as e:
                                logging.error(f"Failed to capture recovery screenshot: {e}")
                                recovery_screenshot = screenshot  # Fallback to last screenshot

                            # Call unified dynamic adjustment function in failure recovery mode
                            recovery_result = await generate_dynamic_steps_with_llm(
                                failure_recovery_mode=True,
                                failed_instruction=instruction_to_execute,
                                error_message=tool_output,
                                test_objective=case.get("objective", ""),
                                executed_steps=i+1,
                                llm=llm,
                                current_case=case,
                                screenshot=recovery_screenshot
                            )

                            strategy = recovery_result.get("strategy")
                            confidence = recovery_result.get("confidence", 0.0)

                            if strategy == "retry_modified":
                                # Replace current step with adapted instruction
                                new_steps = recovery_result.get("steps", [])
                                if new_steps and len(new_steps) > 0:
                                    logging.info(f"Adapting step {i+1} with new instruction (confidence: {confidence:.2f})")
                                    logging.debug(f"Adaptation reason: {recovery_result.get('reason', 'N/A')}")
                                    case_steps[i] = new_steps[0]
                                    step_retry_tracker[retry_key] = 2  # Mark as adapted
                                    continue  # Retry with adapted instruction

                            elif strategy == "skip":
                                logging.warning(f"Skipping step {i+1} based on recovery analysis: {recovery_result.get('reason', 'N/A')}")
                                failed_steps.append(i + 1)
                                # i will increment normally, skip this step

                            elif strategy == "abort":
                                logging.error(f"Aborting test at step {i+1} based on recovery analysis: {recovery_result.get('reason', 'N/A')}")
                                final_summary = f"FINAL_SUMMARY: Test aborted at step {i+1}. {recovery_result.get('reason', 'Critical failure')}"
                                break

                        else:
                            # Already adapted but still failing - mark as failed and continue
                            failed_steps.append(i + 1)
                            logging.error(f"Step {i+1} failed even after adaptation, marking as failed")
                    else:
                        # Adaptive recovery disabled for ELEMENT_NOT_FOUND
                        failed_steps.append(i + 1)
                        logging.warning(f"Step {i+1} element not found, but adaptive recovery is disabled")

                # Priority 2: Check for other critical failures (non-recoverable)
                elif _is_critical_failure_step(tool_output, instruction_to_execute):
                    failed_steps.append(i + 1)
                    final_summary = f"FINAL_SUMMARY: Critical failure at step {i + 1}: '{instruction_to_execute}'. Error details: {tool_output[:200]}..."
                    logging.error(f"Critical failure detected at step {i + 1}, aborting remaining steps to save time")
                    break

                # Priority 3: Other failures (non-critical)
                else:
                    failed_steps.append(i + 1)
                    logging.warning(f"Step {i+1} detected as failed based on output")

            # Check for objective achievement signal
            is_achieved, achievement_reason = _is_objective_achieved(tool_output)
            if is_achieved:
                logging.info(f"Test objective achieved at step {i+1}: {achievement_reason}")
                final_summary = f"FINAL_SUMMARY: Test case completed successfully with early termination at step {i+1}. {achievement_reason}"
                break

            logging.debug(f"Step {i+1} completed {'successfully' if (i+1) not in failed_steps else 'with issues'}.")

            # --- Dynamic Step Generation ---
            if step_type == "Action":
                # Get dynamic step generation config from state
                dynamic_config = state.get("dynamic_step_generation", {
                    "enabled": False,
                    "max_dynamic_steps": 5,
                    "min_elements_threshold": 2
                })
                
                dynamic_enabled = dynamic_config.get("enabled", False)
                max_dynamic_steps = dynamic_config.get("max_dynamic_steps", 5)
                min_elements_threshold = dynamic_config.get("min_elements_threshold", 2)
                
                if dynamic_enabled:
                    # Extract DOM diff from tool output (safely access intermediate_steps)
                    intermediate_output = safe_get_intermediate_step(result, index=0, subindex=1, default="")
                    dom_diff = extract_dom_diff_from_output(intermediate_output)

                    if dom_diff and len(dom_diff) >= min_elements_threshold and dom_diff not in dom_diff_cache:
                        logging.info(f"Detected {len(dom_diff)} new elements, starting dynamic test step generation")
                        
                        try:
                            # Capture screenshot for visual context after successful step execution
                            logging.debug("Capturing screenshot for dynamic step generation context")
                            screenshot = await ui_tester_instance._actions.b64_page_screenshot()
                            
                            # Enhance objective with generation context for smarter LLM decision-making
                            enhanced_objective = case.get("objective", "")
                            if dynamic_generation_count > 0:
                                enhanced_objective += f" (Context: Already generated {dynamic_generation_count} rounds of dynamic steps, be selective about additional generation)"
                            if i+1 > LONG_STEPS:  # Long test indicator
                                enhanced_objective += f" (Context: Test already has {i+1} steps, consider if more steps add meaningful value)"
                            
                            # Determine if current step succeeded based on failed_steps list
                            step_success = (i + 1) not in failed_steps
                            
                            # Generate dynamic test steps with complete context and visual information
                            dynamic_result = await generate_dynamic_steps_with_llm(
                                dom_diff=dom_diff,
                                last_action=instruction_to_execute,
                                test_objective=enhanced_objective,
                                executed_steps=i+1,
                                max_steps=max_dynamic_steps,
                                llm=llm,
                                current_case=case,
                                screenshot=screenshot,
                                tool_output=tool_output,
                                step_success=step_success
                            )
                            
                            # Handle dynamic steps based on LLM strategy decision
                            strategy = dynamic_result.get("strategy", "insert")
                            reason = dynamic_result.get("reason", "No reason provided")
                            dynamic_steps = dynamic_result.get("steps", [])
                            
                            if dynamic_steps:
                                logging.info(f"Generated {len(dynamic_steps)} dynamic test steps with strategy '{strategy}': {reason}")
                                case_steps = case.get("steps", [])
                                
                                # Increment generation count since we're actually adding steps
                                dynamic_generation_count += 1
                                
                                # Convert dynamic steps to the standard format and filter duplicates
                                def is_similar_step(step1: dict, step2: dict) -> bool:
                                    """Check if two steps are similar to avoid duplicates"""
                                    if "action" in step1 and "action" in step2:
                                        return step1["action"].lower().strip() == step2["action"].lower().strip()
                                    if "verify" in step1 and "verify" in step2:
                                        return step1["verify"].lower().strip() == step2["verify"].lower().strip()
                                    return False
                                
                                formatted_dynamic_steps = []
                                executed_and_remaining = case_steps[:i+1] + case_steps[i+1:]  # All existing steps
                                
                                for dyn_step in dynamic_steps:
                                    # Check for duplicates before adding
                                    is_duplicate = False
                                    for existing_step in executed_and_remaining:
                                        if is_similar_step(dyn_step, existing_step):
                                            logging.debug(f"Skipping duplicate step: {dyn_step}")
                                            is_duplicate = True
                                            break
                                    
                                    if not is_duplicate:
                                        if "action" in dyn_step:
                                            formatted_dynamic_steps.append({"action": dyn_step["action"]})
                                        if "verify" in dyn_step:
                                            formatted_dynamic_steps.append({"verify": dyn_step["verify"]})
                                
                                # Apply strategy: insert or replace
                                if strategy == "replace":
                                    # Replace all remaining steps with new steps
                                    case_steps = case_steps[:i+1] + formatted_dynamic_steps
                                    logging.info(f"Replaced remaining steps with {len(formatted_dynamic_steps)} dynamic steps")
                                else:
                                    # Insert steps at current position
                                    insert_position = i + 1
                                    case_steps[insert_position:insert_position] = formatted_dynamic_steps
                                    logging.info(f"Inserted {len(formatted_dynamic_steps)} dynamic steps at position {insert_position}")
                                
                                case["steps"] = case_steps
                                
                                # Update total_steps to include the new steps
                                total_steps = len(case_steps)
                                
                                # Mark the case as modified for later saving
                                case["_dynamic_steps_added"] = True
                                case["_dynamic_steps_count"] = len(formatted_dynamic_steps)
                                case["_dynamic_strategy"] = strategy
                                case["_dynamic_reason"] = reason
                                case_modified = True
                                
                                logging.info(f"Applied '{strategy}' strategy. Total steps now: {total_steps}")
                            else:
                                logging.debug(f"LLM determined no dynamic steps needed: {reason}")
                        
                        except Exception as dyn_gen_e:
                            logging.error(f"Error in dynamic step generation process: {dyn_gen_e}")
                    else:
                        if dom_diff:
                            logging.debug(f"Detected {len(dom_diff)} new elements, but below threshold {min_elements_threshold}, skipping dynamic step generation")
                        else:
                            logging.debug("No DOM changes detected, skipping dynamic step generation")
                    dom_diff_cache.append(dom_diff)

                else:
                    logging.debug("Dynamic step generation not enabled")
            # --- Dynamic Step Generation End ---

        except Exception as e:
            logging.error(f"Exception during step {i+1} execution: {str(e)}")
            failed_steps.append(i + 1)
            final_summary = f"FINAL_SUMMARY: Step '{instruction_to_execute}' raised an exception: {str(e)}"
            break
            
        # Move to next step
        i += 1

    # If the loop finishes without an early exit, generate a final summary
    if "FINAL_SUMMARY:" not in final_summary:
        logging.debug("All test steps completed, generating final summary")
        logging.debug(f"Failed steps detected during execution: {failed_steps}")

        # Use the LLM directly to generate the summary (not through the agent)
        try:
            # Prepare context for summary generation
            summary_prompt = f"""Based on the test execution of case "{case_name}", generate a summary.
            
Test Objective: {case.get('objective', 'Not specified')}
Success Criteria: {case.get('success_criteria', ['Not specified'])}
Total Steps Executed: {total_steps}
Failed Steps: {failed_steps if failed_steps else 'None'}

Generate a test summary in this format:
FINAL_SUMMARY: Test case "{case_name}" [status]. [details about execution]. [objective achievement status].

If all steps passed without failures:
FINAL_SUMMARY: Test case "{case_name}" completed successfully. All {total_steps} test steps executed without critical errors. Test objective achieved: [confirmation]. All success criteria met.

If there were failures:
FINAL_SUMMARY: Test case "{case_name}" failed at step [X]. Error: [description]. Recovery attempts: [if any]. Recommendation: [suggested fix]."""

            # Get the last few messages for context (excluding images to save tokens)
            recent_messages = []
            for msg in messages[-6:]:  # Last 3 exchanges
                if isinstance(msg, HumanMessage):
                    if isinstance(msg.content, list):
                        # Extract text content only
                        text_content = next((item["text"] for item in msg.content if item["type"] == "text"), str(msg.content))
                        recent_messages.append(f"Human: {text_content}")
                    else:
                        recent_messages.append(f"Human: {msg.content}")
                elif isinstance(msg, AIMessage):
                    recent_messages.append(f"AI: {msg.content[:500]}...")  # Truncate for brevity

            context = "\n".join(recent_messages)
            full_prompt = f"{summary_prompt}\n\nRecent test execution context:\n{context}"

            # Use the LLM directly
            response = await llm.ainvoke(full_prompt)

            # Extract content from response
            if hasattr(response, 'content'):
                agent_output = response.content
            else:
                agent_output = str(response)

            # Ensure the summary has the correct format
            if agent_output and not agent_output.strip().startswith("FINAL_SUMMARY:"):
                # Auto-format the response if it doesn't follow the expected format
                logging.debug("LLM summary missing FINAL_SUMMARY prefix, auto-formatting")
                if not failed_steps:
                    final_summary = f"FINAL_SUMMARY: Test case \"{case_name}\" completed successfully. All {total_steps} test steps executed. {agent_output}"
                else:
                    final_summary = f"FINAL_SUMMARY: Test case \"{case_name}\" failed. {agent_output}"
            else:
                final_summary = agent_output if agent_output else f"FINAL_SUMMARY: Test case \"{case_name}\" completed all {total_steps} steps."

            logging.debug(f"Final summary generated: {final_summary}")

        except Exception as e:
            logging.error(f"Exception during final summary generation: {str(e)}")
            # Provide a reasonable default summary based on what we know
            if not failed_steps:
                final_summary = f"FINAL_SUMMARY: Test case \"{case_name}\" completed successfully. All {total_steps} test steps executed without detected failures."
            else:
                final_summary = f"FINAL_SUMMARY: Test case \"{case_name}\" completed with failures at steps {failed_steps}. Review execution logs for details."

    # Determine test case status with improved logic
    final_summary_lower = final_summary.lower()

    # More comprehensive success indicators
    success_indicators = [
        "completed successfully",
        "test objective achieved",
        "success criteria met",
        "all test steps executed",
        "without critical errors",
        "passed"
    ]

    # More comprehensive failure indicators
    failure_indicators = [
        "failed at step",
        "test case failed",
        "error:",
        "exception:",
        "could not",
        "unable to",
        "critical error",
        "test objective not achieved"
    ]

    # Check for indicators
    has_success = any(indicator in final_summary_lower for indicator in success_indicators)
    has_failure = any(indicator in final_summary_lower for indicator in failure_indicators)

    # Determine status with clear priority
    if "failed at step" in final_summary_lower or "test case failed" in final_summary_lower:
        status = "failed"
    elif "completed successfully" in final_summary_lower and not has_failure:
        status = "passed"
    elif has_failure and not has_success:
        status = "failed"
    elif has_success and not has_failure:
        status = "passed"
    else:
        # Default based on whether we detected any failed steps during execution
        if failed_steps:  # Use the failed_steps list we collected
            status = "failed"
        else:
            status = "passed"
    
    # Check if there are warning steps - upgrade status to "warning" if test passed but has warnings
    if status == "passed" and warning_steps:
        status = "warning"
        logging.info(f"Test case '{case_name}' passed but has warnings at steps: {warning_steps}")

    logging.debug(f"Test case '{case_name}' final status: {status} (success indicators: {has_success}, failure indicators: {has_failure}, warning steps: {warning_steps})")

    # Classify failure type if the test case failed
    failure_type = None
    if status == "failed":
        failure_type = _classify_failure_type(final_summary, failed_steps)
        logging.info(f"Test case '{case_name}' failed with type: {failure_type}")

    case_result = {
        "case_name": case_name,
        "final_summary": final_summary,
        "status": status,
        "failure_type": failure_type,
    }

    # Include the modified case if dynamic steps were added
    result = {"case_result": case_result}
    if case_modified:
        result["modified_case"] = case

    logging.debug(f"=== Agent Worker Completed for {case_name}. ===")

    # Finalize case recording with final status
    case_recorder.finish_case(final_status=status, final_summary=final_summary)

    # Get recorded case data
    result_with_case = dict(result)
    recorded_case_data = case_recorder.get_case_data()
    result_with_case["recorded_case"] = recorded_case_data
    
    return result_with_case


def _is_objective_achieved(tool_output: str) -> tuple[bool, str]:
    """Check if the agent has signaled that the test objective is achieved.
    
    Args:
        tool_output: The output from the step execution
    
    Returns:
        tuple: (is_achieved: bool, reason: str)
    """
    if not tool_output or "OBJECTIVE_ACHIEVED:" not in tool_output:
        return False, ""
    
    try:
        # Extract the reason after the signal
        parts = tool_output.split("OBJECTIVE_ACHIEVED:")
        if len(parts) > 1:
            reason = parts[1].split("\n")[0].strip()
            # Only return True if there's actual content after the signal
            if reason:
                return True, reason
    except Exception as e:
        logging.debug(f"Error parsing objective achievement signal: {e}")
    
    return False, ""


def _is_critical_failure_step(tool_output: str, step_instruction: str = "") -> bool:
    """Check if a single step output indicates a critical failure that should stop execution.
    
    Uses hybrid detection approach:
    1. Primary: Structured error tags [CRITICAL_ERROR:category] (preferred)
    2. Fallback: Pattern matching for backward compatibility and enhanced coverage
    
    Args:
        tool_output: The output from the step execution
        step_instruction: The instruction that was executed (for context)
    
    Returns:
        bool: True if this is a critical failure that should stop execution
    """
    if not tool_output:
        return False
    
    output_lower = tool_output.lower()
    
    # Phase 1: Check for structured critical error tags (preferred method)
    if "[critical_error:" in output_lower:
        logging.debug("Critical failure detected via structured error tag")
        return True
    
    # Phase 2a: Check literal patterns (backward compatibility)
    for pattern in CRITICAL_LITERAL_PATTERNS:
        if pattern in output_lower:
            logging.debug(f"Critical failure detected via literal pattern: '{pattern}'")
            return True
    
    # Phase 2b: Check regex patterns (enhanced matching)
    if CRITICAL_REGEX.search(output_lower):
        logging.debug("Critical failure detected via regex pattern")
        return True
    
    return False


def _classify_failure_type(final_summary: str, failed_steps: list = None) -> str:
    """Classify failure type as 'critical' or 'recoverable'.
    
    Args:
        final_summary: The final summary text containing failure information
        failed_steps: List of failed step numbers
    
    Returns:
        str: 'critical' for unrecoverable failures, 'recoverable' for failures that might be fixed via replan
    """
    if not final_summary:
        return "recoverable"
    
    summary_lower = final_summary.lower()
    
    # Check for early critical failure exit (from immediate step detection)
    if "critical failure at step" in summary_lower:
        logging.debug("Early critical failure exit detected - classified as critical")
        return "critical"
    
    # Critical failure patterns - these indicate unrecoverable issues
    critical_patterns = [
        "element not found",
        "cannot find",
        "page crashed",
        "permission denied", 
        "access denied",
        "network timeout",
        "max iterations",
        "exception:",
        "cannot proceed",
        "preamble action",
        "raised exception",
        "agent stopped due to max iterations",
        "element not available",
        "page not accessible",
        "browser error",
        "navigation failed",
        "session expired",
        "server error",
        "connection timeout",
        "unable to load",
        "critical error"
    ]
    
    # Check if any critical pattern is present
    for pattern in critical_patterns:
        if pattern in summary_lower:
            logging.debug(f"Critical failure detected: pattern '{pattern}' found in summary")
            return "critical"
    
    # Additional heuristics for critical failures
    # If too many steps failed, it might indicate a fundamental issue
    if failed_steps and len(failed_steps) > 0:
        total_failed = len(failed_steps)
        if total_failed >= 3:  # If 3 or more steps failed, likely critical
            logging.debug(f"Critical failure detected: {total_failed} steps failed")
            return "critical"
    
    # Default to recoverable for validation failures, partial failures, etc.
    logging.debug("Failure classified as recoverable")
    return "recoverable"


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
        "navigate",
        "go to",
        "open",
        "visit",
        "browse",
        "load",
        "access",
        "enter",
        "launch",
        "导航",  # navigate (Chinese)
        "打开",  # open (Chinese)
        "访问",  # visit (Chinese)
        "跳转",  # jump to (Chinese)
        "前往",  # go to (Chinese)
    ]

    # Convert instruction to lowercase for matching
    instruction_lower = instruction.lower()

    # Check if it contains navigation keywords
    for keyword in navigation_keywords:
        if keyword in instruction_lower:
            return True

    # Check URL patterns
    url_patterns = [r"https?://[^\s]+", r"www\.[^\s]+", r"\.com|\.org|\.net|\.edu|\.gov"]

    for pattern in url_patterns:
        if re.search(pattern, instruction_lower):
            return True

    return False
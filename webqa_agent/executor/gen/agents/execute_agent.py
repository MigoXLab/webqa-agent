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
import time
from typing import Any, Dict, List, Optional, Set

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

from webqa_agent.crawler.deep_crawler import DeepCrawler
from webqa_agent.data.gen_structures import StepOutcome, StepSeverity
from webqa_agent.executor.gen.agents.dynamic_step_generator import \
    generate_dynamic_steps_with_llm
from webqa_agent.executor.gen.agents.status_determination import (
    apply_safety_guard, derive_failure_type_from_outcomes, detect_llm_provider,
    extract_failed_step_details, is_critical_failure_step,
    is_navigation_instruction, is_objective_achieved,
    is_operation_page_agnostic, parse_llm_status, verdict_fallback)
from webqa_agent.executor.gen.agents.step_helpers import (
    build_user_summary, contains_failure_indicators, i18n, is_similar_step,
    make_final_summary, parse_user_summary, sanitize_message_for_summary)
from webqa_agent.executor.gen.utils.case_recorder import CentralCaseRecorder
from webqa_agent.executor.gen.utils.content_extraction import (
    extract_dom_diff_from_output, extract_text_content,
    safe_get_intermediate_step)
from webqa_agent.executor.gen.utils.error_classifier import (
    get_system_error_summary, is_system_error)
from webqa_agent.executor.gen.utils.message_converter import \
    convert_intermediate_steps_to_messages
from webqa_agent.executor.gen.utils.token_timing import (
    LONG_STEPS, RETRY_STABILIZATION_DELAY, StepLLMTimingCallback,
    build_time_breakdown, extract_token_usage_from_result,
    instrumented_ainvoke)
from webqa_agent.executor.gen.utils.tool_config import (get_dynamic_config,
                                                        get_tools,
                                                        parse_step_type)
from webqa_agent.executor.gen.utils.url_utils import (extract_domain,
                                                      extract_path,
                                                      normalize_url)
from webqa_agent.llm.llm_api import (EXTENDED_THINKING_EFFORT_MAPPING,
                                     get_llm_duration_stats,
                                     reset_llm_duration_stats)
from webqa_agent.prompts.agent_execution_prompts import (
    get_execute_system_prompt, get_file_upload_context,
    get_preamble_system_prompt)
from webqa_agent.tools.base import ResponseTags
from webqa_agent.tools.registry import get_registry
from webqa_agent.utils.data_flow_reporter import (record_data_flow_event,
                                                  serialize_intermediate_steps,
                                                  serialize_langchain_message)
from webqa_agent.utils.log_icon import icon
from webqa_agent.utils.timing_breakdown import (get_tool_timing_bucket,
                                                reset_tool_timing_bucket)


def _create_agent_executor(
    llm: Any,
    tools: list,
    system_prompt: str,
    max_iterations: int = 5,
) -> AgentExecutor:
    """Create a configured AgentExecutor bound to the given system prompt.

    Args:
        llm: LangChain chat model instance.
        tools: List of LangChain tools to bind.
        system_prompt: System prompt string for this executor profile.
        max_iterations: Maximum ReAct loop iterations (default 5).

    Returns:
        Configured AgentExecutor instance.
    """
    prompt = ChatPromptTemplate.from_messages([
        ('system', system_prompt),
        MessagesPlaceholder(variable_name='messages'),
        MessagesPlaceholder(variable_name='agent_scratchpad'),
    ])
    agent = create_tool_calling_agent(llm, tools, prompt)
    return AgentExecutor(
        agent=agent,
        tools=tools,
        verbose=False,
        max_iterations=max_iterations,
        return_intermediate_steps=True,
    )


async def agent_worker_node(state: dict, config: dict) -> dict:
    """Dynamically creates and invokes the execution agent for a single test
    case.

    This node is mapped over the list of test cases.
    """
    case = state['test_case']
    case_name = case.get('name', 'Unnamed Test Case')
    report_dir = state.get('report_config', {}).get('report_dir')
    completed_cases = state.get('completed_cases', [])
    # Only record safe fields from case (exclude cookies, session data, etc.)
    safe_case = {
        k: v for k, v in case.items()
        if k not in ('cookies', 'session', 'auth', 'credentials', 'token', 'api_key')
    }
    record_data_flow_event(
        stage='agent_execution',
        event_type='case_execution_start',
        payload={
            'case_id': case.get('case_id', ''),
            'case_name': case_name,
            'case': safe_case,
            'completed_case_count': len(completed_cases),
        },
        report_dir=report_dir,
    )

    logging.debug(f'=== Starting Agent Worker for Test Case: {case_name} ===')
    logging.debug(f"Test case objective: {case.get('objective', 'Not specified')}")
    logging.debug(f"Test case steps count: {len(case.get('steps', []))}")
    logging.debug(f"Preamble actions count: {len(case.get('preamble_actions', []))}")
    logging.debug(f'Previously completed cases: {len(completed_cases)}')

    ui_tester_instance = config['configurable']['ui_tester_instance']
    ui_tester_instance.report_dir = report_dir
    # Attach test file library for path security validation in action_tool
    ui_tester_instance.test_file_library = state.get('test_file_library')

    case_recorder = config.get('configurable', {}).get('case_recorder')
    if case_recorder is None:
        case_recorder = CentralCaseRecorder()
        case_recorder.start_case(case_name, case_data=case)

    ui_tester_instance.central_case_recorder = case_recorder
    original_planned_steps = copy.deepcopy(case.get('steps', []))

    language = state.get('language', 'zh-CN')
    planning_mode = state.get('planning_mode', 'explore')
    case_objective = case.get('objective', case_name)
    system_prompt_string = get_execute_system_prompt(
        case,
        language=language,
    )
    logging.debug(
        f'Generated system prompt length: {len(system_prompt_string)} characters'
    )

    # Inject file upload context if test file library is available
    test_file_library = state.get('test_file_library')
    if test_file_library:
        file_catalog = test_file_library.get_catalog_for_llm()
        if file_catalog:
            system_prompt_string += get_file_upload_context(file_catalog)
            logging.debug(
                f'Injected file upload context ({len(file_catalog)} chars) '
                f'into agent system prompt'
            )

    llm_config = ui_tester_instance.llm.llm_config
    logging.info(f"{icon['running']} Agent worker for test case started: {case_name}")

    model_name = llm_config.get('model', 'gpt-4o-mini')
    provider = detect_llm_provider(model_name)
    llm_kwargs = {
        'model': model_name,
        'api_key': llm_config.get('api_key'),
    }

    base_url = llm_config.get('base_url')
    if base_url:
        llm_kwargs['base_url'] = base_url
    elif provider == 'gemini':
        llm_kwargs['base_url'] = (
            'https://generativelanguage.googleapis.com/v1beta/openai/'
        )
        logging.debug('Gemini using official OpenAI compatibility endpoint')

    default_temp = 1.0 if provider in ('anthropic', 'gemini') else 0.1
    cfg_temp = llm_config.get('temperature', default_temp)
    llm_kwargs['temperature'] = cfg_temp

    cfg_top_p = llm_config.get('top_p')
    if cfg_top_p is not None:
        llm_kwargs['top_p'] = cfg_top_p

    cfg_max_tokens = llm_config.get('max_tokens', 4096)
    llm_kwargs['max_tokens'] = cfg_max_tokens

    if provider == 'anthropic':
        reasoning_config = llm_config.get('reasoning')
        if isinstance(reasoning_config, dict):
            effort = reasoning_config.get('effort')
            if effort:
                budget = EXTENDED_THINKING_EFFORT_MAPPING.get(effort.lower())
                if budget:
                    if budget >= cfg_max_tokens:
                        recommended_max = int(budget / 0.5)
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

    if provider in ('openai', 'gemini'):
        reasoning_config = llm_config.get('reasoning')
        if isinstance(reasoning_config, dict):
            effort = reasoning_config.get('effort')
            if effort:
                effort_mapping = {
                    'minimal': 'low',
                    'low': 'low',
                    'medium': 'medium',
                    'high': 'high',
                }
                reasoning_effort = effort_mapping.get(effort.lower())
                if reasoning_effort:
                    llm_kwargs.setdefault('model_kwargs', {})
                    llm_kwargs['model_kwargs']['reasoning_effort'] = reasoning_effort
                    logging.debug(
                        f'{provider.capitalize()} reasoning_effort set to {reasoning_effort} based on effort={effort}'
                    )

    cfg_timeout = llm_config.get('timeout') or 360
    logging.debug(f'LLM request timeout set to {cfg_timeout}s')
    step_llm_timing_callback = StepLLMTimingCallback()
    llm_kwargs.setdefault('callbacks', [])
    llm_kwargs['callbacks'].append(step_llm_timing_callback)

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

    enabled_custom_tools = state.get('enabled_custom_tools', [])
    logging.debug(f'Enabled custom tools from config: {enabled_custom_tools}')

    tools = get_tools(
        ui_tester_instance,
        llm_config,
        case_recorder,
        enabled_custom_tools,
    )
    logging.debug(f'Tools initialized: {[tool.name for tool in tools]}')

    preamble_system_prompt_str = get_preamble_system_prompt(language=language)
    preamble_executor = _create_agent_executor(
        llm, tools, preamble_system_prompt_str, max_iterations=3
    )
    action_executor = _create_agent_executor(
        llm, tools, system_prompt_string, max_iterations=5
    )
    verify_executor = _create_agent_executor(
        llm, tools, system_prompt_string, max_iterations=3
    )
    logging.debug('AgentExecutor profiles created (preamble=3, action=5, verify=3)')

    # ---------------------------------------------------------------------------
    # Shared helper: close a preamble failure and build the return dict.
    # Defined as a closure so it can capture case_recorder, case, case_name,
    # and original_planned_steps without parameter boilerplate.
    # ---------------------------------------------------------------------------
    def _finish_preamble_failure(
        final_summary: str,
        user_summary: str,
        status: str = 'failed',
        failure_type: str = 'preamble_failure',
    ) -> dict:
        case_recorder.finish_case(
            final_status=status,
            final_summary=final_summary,
            user_summary=user_summary,
        )
        recorded = case_recorder.get_case_data()
        if recorded is not None:
            recorded['original_planned_steps'] = original_planned_steps
        metrics = recorded.get('metrics', {}) if recorded else {}
        return {
            'case_result': {
                'case_name': case_name,
                'case_id': case.get('case_id', ''),
                'final_summary': final_summary,
                'user_summary': user_summary,
                'status': status,
                'failure_type': failure_type,
                'metrics': {
                    'total_steps': metrics.get('total_steps', 0),
                    'passed_steps': metrics.get('passed_steps', 0),
                    'failed_steps': metrics.get('failed_steps', 0),
                    'warning_steps': metrics.get('warning_steps', 0),
                    'total_actions': metrics.get('total_actions', 0),
                },
                'failed_step_details': extract_failed_step_details(recorded),
            },
            'current_case_steps': [],
            'recorded_case': recorded,
        }

    # --- Execute Preamble Actions to Restore State ---
    preamble_actions = case.get('preamble_actions', [])
    if preamble_actions:
        logging.debug(f'=== Executing {len(preamble_actions)} Preamble Actions ===')
        preamble_messages: list[BaseMessage] = [
            HumanMessage(
                content=(
                    'PREAMBLE PHASE: You are establishing the required UI state '
                    'before the main test steps begin. '
                    'Execute each provided action using only the parameters specified '
                    'in the action definition — do not supplement, modify, or infer '
                    'parameter values (such as URLs, input text, or element targets) '
                    'from the test objective or any other context. '
                    'Please execute the first preamble action.'
                )
            )
        ]

        for i, step in enumerate(preamble_actions):
            # ------------------------------------------------------------------
            # Direct execution path for structured actions (bypass LLM entirely)
            # ------------------------------------------------------------------
            if isinstance(step, dict):
                action_name = step.get('action', '')
                params = step.get('params', {})

                if action_name == 'GoToPage' and params.get('url'):
                    # GoToPage with explicit URL: execute directly, never let LLM
                    # hallucinate or substitute the target URL.
                    raw_url = params['url'].strip()
                    target_url = normalize_url(raw_url)
                    # normalize_url strips trailing slashes / lowercases the host
                    # but does not add a scheme — fall back to raw if scheme lost.
                    if not target_url.startswith(('http://', 'https://')):
                        logging.warning(
                            f'Preamble GoToPage URL missing http(s) scheme: '
                            f'{raw_url!r} — attempting navigation with original URL'
                        )
                        target_url = raw_url
                    try:
                        await ui_tester_instance.browser_session.navigate_to(target_url)
                        logging.info(
                            f'Preamble action {i + 1}/{len(preamble_actions)}: '
                            f'GoToPage executed directly → {target_url}'
                        )
                        continue  # Done — skip preamble_executor entirely
                    except Exception as _nav_err:
                        logging.error(
                            f'Preamble GoToPage direct execution failed: {target_url} — {_nav_err}'
                        )
                        final_summary = i18n(
                            language,
                            f"前置导航到 '{target_url}' 失败：{_nav_err}",
                            f"Preamble navigation to '{target_url}' failed: {_nav_err}",
                        )
                        user_summary = build_user_summary(language, 'failed', case_objective)
                        return _finish_preamble_failure(final_summary, user_summary)

                # Non-direct action: include params in instruction so LLM has
                # the full context and cannot invent missing values.
                if params:
                    params_str = json.dumps(params, ensure_ascii=False, default=str)
                    instruction_to_execute = f'{action_name}（params: {params_str}）'
                else:
                    instruction_to_execute = action_name or str(step)
            else:
                instruction_to_execute = step

            if not instruction_to_execute:
                logging.warning(f'Preamble action {i + 1} has no instruction, skipping')
                continue

            # Smart check: Skip preamble action if it's a navigation instruction and already on target page
            if case.get('reset_session', False) and is_navigation_instruction(
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
                    content=(
                        f'[PREAMBLE {i + 1}/{len(preamble_actions)}] '
                        f'Execute this setup action using exactly the '
                        f'parameters provided: {instruction_to_execute}'
                    )
                )
            )
            record_data_flow_event(
                stage='agent_execution',
                event_type='preamble_request',
                payload={
                    'case_id': case.get('case_id', ''),
                    'case_name': case_name,
                    'preamble_step_index': i + 1,
                    'instruction': instruction_to_execute,
                },
                report_dir=report_dir,
            )

            try:
                # Use a simple invoke, as preamble steps should be straightforward
                logging.debug(f'Executing preamble action {i + 1} - Calling Agent...')
                start_time = datetime.datetime.now()
                result = await preamble_executor.ainvoke(
                    {'messages': preamble_messages}
                )

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
                if contains_failure_indicators(
                    intermediate_output
                ) or contains_failure_indicators(tool_output):
                    final_summary = i18n(language,
                                         f"前置动作 '{instruction_to_execute}' 失败，无法继续执行测试用例。错误：{tool_output}",
                                         f"Preamble action '{instruction_to_execute}' failed, cannot proceed with the test case. Error: {tool_output}")

                    extracted_user = (
                        parse_user_summary(tool_output)
                        or parse_user_summary(intermediate_output)
                    )
                    if extracted_user:
                        user_summary = extracted_user
                    else:
                        user_summary = build_user_summary(language, 'failed', case_objective)

                    logging.error(f'Preamble action {i + 1} failed, aborting test case')
                    _result = _finish_preamble_failure(final_summary, user_summary)
                    record_data_flow_event(
                        stage='agent_execution',
                        event_type='preamble_response',
                        payload={
                            'case_id': case.get('case_id', ''),
                            'case_name': case_name,
                            'preamble_step_index': i + 1,
                            'instruction': instruction_to_execute,
                            'status': 'failed',
                            'duration_seconds': duration,
                            'output': tool_output,
                            'case_result': _result['case_result'],
                        },
                        report_dir=report_dir,
                    )
                    record_data_flow_event(
                        stage='agent_execution',
                        event_type='case_execution_result',
                        payload={
                            'case_id': case.get('case_id', ''),
                            'case_name': case_name,
                            'case_result': _result['case_result'],
                        },
                        report_dir=report_dir,
                    )
                    return _result

                # Record successful preamble response (only reached if no failure detected)
                record_data_flow_event(
                    stage='agent_execution',
                    event_type='preamble_response',
                    payload={
                        'case_id': case.get('case_id', ''),
                        'case_name': case_name,
                        'preamble_step_index': i + 1,
                        'instruction': instruction_to_execute,
                        'status': 'ok',
                        'duration_seconds': duration,
                        'output': tool_output,
                        'intermediate_steps': serialize_intermediate_steps(
                            result.get('intermediate_steps')
                        ),
                    },
                    report_dir=report_dir,
                )
                logging.debug(f'Preamble action {i + 1} completed successfully')
            except Exception as e:
                end_time = datetime.datetime.now()
                duration = (end_time - start_time).total_seconds()
                logging.error(f'Exception during preamble action {i + 1}: {str(e)}')
                if is_system_error(e):
                    logging.warning(
                        f'System error during preamble action {i + 1}: '
                        f'{type(e).__name__}: {e}'
                    )
                    final_summary = get_system_error_summary(e, language)
                    user_summary = build_user_summary(language, 'warning', case_objective, exception=e)
                    preamble_status = 'warning'
                    preamble_failure_type = 'system_error'
                else:
                    final_summary = i18n(language,
                                         f"前置动作 '{instruction_to_execute}' 发生异常：{str(e)}",
                                         f"Preamble action '{instruction_to_execute}' raised exception: {str(e)}")
                    user_summary = build_user_summary(language, 'failed', case_objective,
                                                      i18n(language,
                                                           f"前置操作'{instruction_to_execute}'发生异常。",
                                                           f"Preamble action '{instruction_to_execute}' raised an exception."))
                    preamble_status = 'failed'
                    preamble_failure_type = 'preamble_exception'
                _result = _finish_preamble_failure(
                    final_summary, user_summary,
                    status=preamble_status,
                    failure_type=preamble_failure_type,
                )
                record_data_flow_event(
                    stage='agent_execution',
                    event_type='preamble_response',
                    payload={
                        'case_id': case.get('case_id', ''),
                        'case_name': case_name,
                        'preamble_step_index': i + 1,
                        'instruction': instruction_to_execute,
                        'status': 'exception',
                        'duration_seconds': duration,
                        'error': str(e),
                        'case_result': _result['case_result'],
                    },
                    report_dir=report_dir,
                )
                record_data_flow_event(
                    stage='agent_execution',
                    event_type='case_execution_result',
                    payload={
                        'case_id': case.get('case_id', ''),
                        'case_name': case_name,
                        'case_result': _result['case_result'],
                    },
                    report_dir=report_dir,
                )
                return _result

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
        step_type = parse_step_type(step)

        # Handle unified format custom tools: {"action": "tool_name", "params": {...}}
        # Convert params to function call instruction for current_executor
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

        # Select executor by step type: verify/ux_verify → max_iterations=3; action → 5
        current_executor = (
            verify_executor if step_type in ('Assertion', 'UX_Verify') else action_executor
        )

        logging.info(
            f'Executing Step {i + 1}/{total_steps} ({step_type}), step instruction: {instruction_to_execute}'
        )
        record_data_flow_event(
            stage='agent_execution',
            event_type='step_request',
            payload={
                'case_id': case.get('case_id', ''),
                'case_name': case_name,
                'planned_step_index': i + 1,
                'step_type': step_type,
                'instruction': instruction_to_execute,
                'messages': [serialize_langchain_message(msg) for msg in messages],
            },
            report_dir=report_dir,
        )

        # Rotating instruction templates with scope constraint to prevent over-execution
        instruction_templates = [
            'Now, execute this instruction: {instruction}\n\nComplete this step only. Do not proceed to any other actions.',
            'Please proceed with the following step: {instruction}\n\nOnce done, report the result. Do not execute additional actions.',
            'The next task is to perform this action: {instruction}\n\nAfter completing this action, stop and report. Do not continue further.',
            'Execute the instruction as follows: {instruction}\n\nReport the result when complete. Do not perform any other operations.',
        ]
        prompt_template = instruction_templates[i % len(instruction_templates)]
        formatted_instruction = prompt_template.format(instruction=instruction_to_execute)
        reset_tool_timing_bucket()
        reset_llm_duration_stats()
        step_llm_timing_callback.reset_step()

        # --- Multi-Modal Context Generation ---
        prep_started = time.perf_counter()
        page = ui_tester_instance.browser_session.page
        dp = DeepCrawler(page)
        screenshot_started = time.perf_counter()
        await dp.crawl(highlight=True, viewport_only=True)
        screenshot, _ = await ui_tester_instance._actions.b64_page_screenshot(
            file_name=f'step_{i + 1}_vision', context='agent'
        )
        screenshot_seconds = max(time.perf_counter() - screenshot_started, 0.0)
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
        message_prep_seconds = max(time.perf_counter() - prep_started, 0.0)
        record_data_flow_event(
            stage='agent_execution',
            event_type='step_input_sent',
            payload={
                'case_id': case.get('case_id', ''),
                'case_name': case_name,
                'planned_step_index': i + 1,
                'step_type': step_type,
                'instruction': instruction_to_execute,
                'messages_with_step': [
                    serialize_langchain_message(msg) for msg in current_messages
                ],
                'messages_sent_to_agent': [
                    serialize_langchain_message(msg) for msg in pruned_messages
                ],
                'timing_hints': {
                    'message_prep_seconds': message_prep_seconds,
                    'screenshot_seconds': screenshot_seconds,
                },
            },
            report_dir=report_dir,
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
                    current_executor.ainvoke(
                        {'messages': pruned_messages},
                    ),
                    timeout=step_timeout,
                )
            except asyncio.TimeoutError:
                logging.error(
                    f'Step {i + 1} ({step_type}) timed out after {step_timeout:.0f}s'
                )
                timeout_breakdown = build_time_breakdown(
                    e2e_duration_seconds=step_timeout,
                    llm_duration_seconds=0.0,
                    message_prep_seconds=message_prep_seconds,
                    screenshot_seconds=screenshot_seconds,
                    tool_execution_seconds=0.0,
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
                record_data_flow_event(
                    stage='agent_execution',
                    event_type='step_response',
                    payload={
                        'case_id': case.get('case_id', ''),
                        'case_name': case_name,
                        'planned_step_index': i + 1,
                        'step_type': step_type,
                        'instruction': instruction_to_execute,
                        'status': 'timeout',
                        'duration_seconds': step_timeout,
                        'time_breakdown': timeout_breakdown,
                    },
                    report_dir=report_dir,
                )
                # System error: abort case immediately
                _timeout_exc = asyncio.TimeoutError(f'Step timed out after {step_timeout:.0f}s')
                final_summary = get_system_error_summary(_timeout_exc, language)
                _obj = case_objective.rstrip('。！？.!?，,；;：:、… ')
                user_summary = i18n(
                    language,
                    f'{_obj}，工具执行超时，结果不完整，非产品缺陷。',
                    f'{_obj} tool execution timed out, results incomplete, not a product defect.',
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
            llm_api_stats = get_llm_duration_stats()
            llm_callback_seconds = step_llm_timing_callback.consume_step_duration()
            # Use max() instead of sum to avoid double-counting when both
            # LangChain callback and LLMAPI accumulator measure overlapping calls.
            llm_duration_seconds = max(
                float(llm_callback_seconds),
                float(llm_api_stats.get('duration_seconds', 0.0)),
                0.0,
            )
            llm_token_usage = dict(llm_api_stats.get('token_usage', {}))

            # Fallback: extract token usage from agent result messages when
            # callback-based tracking returns 0 (e.g. direct-mode Action steps
            # where only the outer LangChain LLM call happens).
            if llm_token_usage.get('total_tokens', 0) == 0:
                llm_token_usage = extract_token_usage_from_result(result, messages)
                if llm_token_usage.get('total_tokens', 0) > 0:
                    logging.debug(
                        f'Step {i + 1} token usage recovered from AIMessage metadata: '
                        f'{llm_token_usage}'
                    )

            tool_timing_bucket = get_tool_timing_bucket()
            tool_execution_seconds = float(tool_timing_bucket.get('tool_execution_seconds', 0.0))
            time_breakdown = build_time_breakdown(
                e2e_duration_seconds=duration,
                llm_duration_seconds=llm_duration_seconds,
                message_prep_seconds=message_prep_seconds,
                screenshot_seconds=screenshot_seconds,
                tool_execution_seconds=tool_execution_seconds,
            )

            logging.debug(
                f'Step {i + 1} {step_type} completed in {duration:.2f} seconds'
            )
            logging.debug(f'Step {i + 1} tool output: {tool_output}')
            messages.append(AIMessage(content=tool_output))
            record_data_flow_event(
                stage='agent_execution',
                event_type='step_response',
                payload={
                    'case_id': case.get('case_id', ''),
                    'case_name': case_name,
                    'planned_step_index': i + 1,
                    'step_type': step_type,
                    'instruction': instruction_to_execute,
                    'status': 'ok',
                    'duration_seconds': duration,
                    'llm_metrics': {
                        'duration_seconds': llm_duration_seconds,
                        'token_usage': llm_token_usage,
                    },
                    'tool_timing': tool_timing_bucket,
                    'time_breakdown': time_breakdown,
                    'output': tool_output,
                    'intermediate_steps': serialize_intermediate_steps(
                        result.get('intermediate_steps')
                    ),
                },
                report_dir=report_dir,
            )

            # Check for warnings in the tool output (e.g., UX issues)
            # Check both agent output and raw tool result from intermediate steps
            intermediate_output = safe_get_intermediate_step(
                result, index=0, subindex=1, default=''
            )
            combined_output = f'{tool_output}\n{intermediate_output}'
            combined_output_lower = combined_output.lower()
            if ResponseTags.WARNING.lower() in combined_output_lower:
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
            if is_critical_failure_step(tool_output, intermediate_output):

                # Smart differentiation: Check if unsupported page + page-agnostic operation
                is_unsupported_page = 'unsupported_page' in tool_output.lower()

                if is_unsupported_page:
                    # Determine if current operation is page-agnostic
                    is_agnostic = is_operation_page_agnostic(
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
                        final_summary = make_final_summary(language,
                                                           f'FINAL_SUMMARY: 严重错误，已执行步骤 {current_executed_step}（计划步骤 {i + 1}）：'
                                                           f"'{instruction_to_execute}'。"
                                                           f'DOM 操作无法在不支持的页面类型上执行。错误详情：{tool_output}',
                                                           f'FINAL_SUMMARY: Critical failure at executed step {current_executed_step} '
                                                           f'(planned step {i + 1}): '
                                                           f"'{instruction_to_execute}'. "
                                                           f'DOM-dependent operation cannot execute on unsupported page type. '
                                                           f'Error details: {tool_output}')
                        user_summary = build_user_summary(language, 'failed', case_objective,
                                                          i18n(language, '页面类型不支持自动化测试。', 'Page type does not support automated testing.'))
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
                    final_summary = make_final_summary(language,
                                                       f'FINAL_SUMMARY: 严重错误，已执行步骤 {current_executed_step}（计划步骤 {i + 1}）：'
                                                       f"'{instruction_to_execute}'。错误详情：{tool_output}",
                                                       f'FINAL_SUMMARY: Critical failure at executed step {current_executed_step} '
                                                       f'(planned step {i + 1}): '
                                                       f"'{instruction_to_execute}'. "
                                                       f'Error details: {tool_output}')
                    user_summary = build_user_summary(language, 'failed', case_objective,
                                                      i18n(language, '遇到严重错误，测试终止。', 'Critical error encountered, test terminated.'))
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
            is_failure = contains_failure_indicators(
                intermediate_output
            ) or contains_failure_indicators(tool_output)
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
                    _diag_summary = (
                        ui_tester_instance.last_action_context.get('diagnostic_summary')
                        if ui_tester_instance
                        and getattr(ui_tester_instance, 'last_action_context', None)
                        else None
                    )
                    step_outcomes.append(StepOutcome(
                        step_index=i + 1,
                        severity=StepSeverity.SOFT_FAIL,
                        description=(
                            f'[Tool completed — page findings] {_diag_summary}'
                            if _diag_summary
                            else f'Batch tool completed (no structured summary): {tool_output[:200]}'
                        ),
                    ))
                    i += 1
                    continue

                # Priority 1: Try recovery for ELEMENT_NOT_FOUND (recoverable critical error)
                elif is_element_not_found:
                    # Get dynamic config to check if adaptive recovery is enabled
                    dynamic_config = get_dynamic_config(state)

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
                                report_dir=report_dir,
                                planning_mode=planning_mode,
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
                                final_summary = make_final_summary(language,
                                                                   f'FINAL_SUMMARY: 测试在已执行步骤 {current_executed_step}（计划步骤 {i + 1}）中止。'
                                                                   f"{recovery_reason or '严重错误'}",
                                                                   f'FINAL_SUMMARY: Test aborted at executed step {current_executed_step} '
                                                                   f"(planned step {i + 1}). {recovery_reason or 'Critical failure'}")
                                reason_suffix = f"{recovery_reason.rstrip('.')}." if recovery_reason else ''
                                user_summary = build_user_summary(
                                    language, 'failed', case_objective,
                                    i18n(language,
                                         '目标元素无法定位，自动恢复尝试失败，请排查页面是否存在该目标元素。',
                                         'Target element could not be located, automatic recovery failed. '
                                         'Please verify the target element exists on the page.'
                                         + (f' {reason_suffix}' if reason_suffix else '')))
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
                    dynamic_config = get_dynamic_config(state)

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
                                    report_dir=report_dir,
                                    planning_mode=planning_mode,
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
                                    # final_summary: keep abort context (step, instruction, reason)
                                    # for agent/executor diagnostics.
                                    final_summary = make_final_summary(
                                        language,
                                        f'FINAL_SUMMARY: 不可恢复的失败，已执行步骤 {current_executed_step}（计划步骤 {i + 1}）：'
                                        f"'{instruction_to_execute}'。LLM 自适应恢复判断必须终止。原因：{reason}",
                                        f'FINAL_SUMMARY: Unrecoverable failure at executed step {current_executed_step} '
                                        f'(planned step {i + 1}): '
                                        f"'{instruction_to_execute}'. "
                                        f'LLM adaptive recovery determined abortion necessary. '
                                        f'Reason: {reason}',
                                    )
                                    # user_summary: try to reuse the step's own USER_SUMMARY if
                                    # present (forward-compatible — current tools don't emit
                                    # USER_SUMMARY in step output, but custom tools may do so).
                                    extracted_user = (
                                        parse_user_summary(tool_output)
                                        or parse_user_summary(intermediate_output)
                                    )
                                    if extracted_user:
                                        user_summary = extracted_user
                                    else:
                                        user_summary = build_user_summary(language, 'failed', case_objective)
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
            is_achieved, achievement_reason = is_objective_achieved(tool_output)
            if is_achieved:
                objective_achieved = True
                current_executed_step = len(case_recorder.current_case_steps)
                logging.info(
                    f'Test objective achieved at executed step {current_executed_step} '
                    f'(planned step {i + 1}): {achievement_reason}'
                )
                final_summary = make_final_summary(language,
                                                   f'FINAL_SUMMARY: 测试用例在已执行步骤 {current_executed_step}（计划步骤 {i + 1}/{total_steps}）提前终止，执行成功。{achievement_reason}',
                                                   f'FINAL_SUMMARY: Test case completed successfully with early '
                                                   f'termination at executed step {current_executed_step} '
                                                   f'(planned step {i + 1}/{total_steps}). {achievement_reason}')
                user_summary = build_user_summary(language, 'passed', case_objective)
                code_determined_status = 'passed'
                code_failure_type = None
                break

            # Record PASSED outcome for successful steps (no prior outcome recorded)
            step_already_recorded = any(o.step_index == i + 1 for o in step_outcomes)

            # Classify [CANNOT_VERIFY] and [WARNING] tags that bypass failure detection
            is_cannot_verify = ResponseTags.CANNOT_VERIFY.lower() in combined_output_lower
            is_non_failure_warning = (
                ResponseTags.WARNING.lower() in combined_output_lower
                and not is_failure
                and not is_cannot_verify
            )

            if is_cannot_verify and not step_already_recorded:
                step_outcomes.append(StepOutcome(
                    step_index=i + 1,
                    severity=StepSeverity.SOFT_FAIL,
                    description=f'Verification inconclusive: {tool_output[:200]}',
                ))
            elif is_non_failure_warning and not step_already_recorded:
                step_outcomes.append(StepOutcome(
                    step_index=i + 1,
                    severity=StepSeverity.WARNING,
                    description=f'Warning: {tool_output[:200]}',
                ))
            elif not step_already_recorded:
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
                dynamic_config = get_dynamic_config(state)

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
                                report_dir=report_dir,
                                planning_mode=planning_mode,
                                original_planned_steps=original_planned_steps,
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

            # Record step_response for the exception so JSONL/gantt stay consistent
            _locals = locals()
            exc_duration = (
                (datetime.datetime.now() - start_time).total_seconds()
                if 'start_time' in _locals
                else 0.0
            )
            exc_llm_seconds = step_llm_timing_callback.consume_step_duration()
            exc_llm_stats = get_llm_duration_stats()
            exc_llm_duration = max(
                float(exc_llm_seconds),
                float(exc_llm_stats.get('duration_seconds', 0.0)),
                0.0,
            )
            exc_breakdown = build_time_breakdown(
                e2e_duration_seconds=exc_duration,
                llm_duration_seconds=exc_llm_duration,
                message_prep_seconds=message_prep_seconds,
                screenshot_seconds=screenshot_seconds,
                tool_execution_seconds=0.0,
            )
            record_data_flow_event(
                stage='agent_execution',
                event_type='step_response',
                payload={
                    'case_id': case.get('case_id', ''),
                    'case_name': case_name,
                    'planned_step_index': i + 1,
                    'step_type': step_type,
                    'instruction': instruction_to_execute,
                    'status': 'exception',
                    'duration_seconds': exc_duration,
                    'llm_metrics': {
                        'duration_seconds': exc_llm_duration,
                        'token_usage': dict(exc_llm_stats.get('token_usage', {})),
                    },
                    'time_breakdown': exc_breakdown,
                    'error': str(e),
                },
                report_dir=report_dir,
            )

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
                user_summary = build_user_summary(language, 'warning', case_objective, exception=e)
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
                final_summary = make_final_summary(language,
                                                   f"FINAL_SUMMARY: 步骤 '{instruction_to_execute}' 发生异常：{str(e)}",
                                                   f"FINAL_SUMMARY: Step '{instruction_to_execute}' raised an exception: {str(e)}")
                user_summary = build_user_summary(language, 'failed', case_objective,
                                                  i18n(language,
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
        parsed_user_summary = parse_user_summary(tool_output)
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

            _step_diag_lines = [
                f'  - Step {o.step_index} ({o.severity.value.upper()}): {o.description}'
                for o in step_outcomes
                if o.description and o.severity != StepSeverity.PASSED
            ]
            _diag_header = i18n(
                language,
                '步骤诊断详情（工具实际发现，优先参考）：',
                'Step Diagnostic Details (actual tool findings, prioritize these):',
            )
            _step_details_section = (
                f'\n{_diag_header}\n' + '\n'.join(_step_diag_lines) + '\n'
                if _step_diag_lines else ''
            )

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
{_step_details_section}
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
{_step_details_section}
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
                sanitized = sanitize_message_for_summary(msg, max_length=250)

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
                    response = await instrumented_ainvoke(
                        llm,
                        full_prompt,
                        model_name=getattr(llm, 'model_name', 'unknown-model'),
                    )

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
                    final_summary = make_final_summary(language,
                                                       f'FINAL_SUMMARY: 测试用例"{case_name}"执行完成。共执行 {executed_steps_count} 个步骤。{agent_output}',
                                                       f'FINAL_SUMMARY: Test case "{case_name}" completed successfully. All {executed_steps_count} executed steps completed. {agent_output}')
                else:
                    final_summary = (
                        make_final_summary(language,
                                           f'FINAL_SUMMARY: 测试用例"{case_name}"失败。{agent_output}',
                                           f'FINAL_SUMMARY: Test case "{case_name}" failed. {agent_output}')
                    )
            else:
                # Use agent_output (not _summary_output) to preserve STATUS line
                # for parse_llm_status; stripped post-determination below.
                final_summary = (
                    agent_output
                    if agent_output
                    else make_final_summary(language,
                                            f'FINAL_SUMMARY: 测试用例"{case_name}"已完成全部 {executed_steps_count} 个步骤。',
                                            f'FINAL_SUMMARY: Test case "{case_name}" completed all {executed_steps_count} executed steps.')
                )

            logging.debug(f'Final summary generated: {final_summary}')

            # Parse USER_SUMMARY from LLM output
            user_summary = parse_user_summary(agent_output) or ''
            if not user_summary:
                # LLM did not output USER_SUMMARY — use template fallback
                if not _get_failed_step_indices():
                    user_summary = build_user_summary(language, 'passed', case_objective)
                else:
                    user_summary = build_user_summary(language, 'failed', case_objective)

        except Exception as e:
            logging.error(f'Exception during final summary generation: {str(e)}')
            if is_system_error(e):
                # Summary LLM itself failed → system error
                final_summary = get_system_error_summary(e, language)
                user_summary = build_user_summary(language, 'warning', case_objective, exception=e)
                code_determined_status = 'warning'
                code_failure_type = 'system_error'
            elif not _get_failed_step_indices():
                # P4: Use executed steps count
                final_summary = make_final_summary(language,
                                                   f'FINAL_SUMMARY: 测试用例"{case_name}"执行完成。共执行 {executed_steps_count} 个步骤，未检测到失败。',
                                                   f'FINAL_SUMMARY: Test case "{case_name}" completed successfully. All {executed_steps_count} executed steps completed without detected failures.')
                user_summary = build_user_summary(language, 'passed', case_objective)
                code_determined_status = 'passed'
            else:
                failed_indices = _get_failed_step_indices()
                final_summary = make_final_summary(language,
                                                   f'FINAL_SUMMARY: 测试用例"{case_name}"完成，以下步骤失败：{failed_indices}，请查看执行日志。',
                                                   f'FINAL_SUMMARY: Test case "{case_name}" completed with failures at steps {failed_indices}. Review execution logs for details.')
                user_summary = build_user_summary(language, 'failed', case_objective)
                code_determined_status = 'failed'
                code_failure_type = derive_failure_type_from_outcomes(step_outcomes)

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
            status = apply_safety_guard(code_determined_status, step_outcomes)
        failure_type = code_failure_type
        if status == 'failed' and not failure_type:
            failure_type = derive_failure_type_from_outcomes(step_outcomes)
        logging.debug(
            f"Code-determined status for '{case_name}': {status} "
            f'(failure_type={failure_type})'
        )
    else:
        # Path B: Normal completion — LLM STATUS with safety guard + verdict fallback
        llm_status = parse_llm_status(final_summary)
        if llm_status:
            status = apply_safety_guard(llm_status, step_outcomes)
            if status != llm_status:
                logging.warning(
                    f"Safety guard overrode LLM status '{llm_status}' → '{status}' "
                    f"for '{case_name}'"
                )
            else:
                logging.debug(f"LLM-determined status for '{case_name}': {status}")
        else:
            # Fallback: use deterministic verdict
            status, _fallback_failure_type = verdict_fallback(
                step_outcomes, warning_steps, objective_achieved
            )
            logging.warning(
                f"LLM did not output valid STATUS for '{case_name}', "
                f'using verdict fallback: {status}'
            )

        # Determine failure_type
        failure_type = None
        if status == 'failed':
            failure_type = derive_failure_type_from_outcomes(step_outcomes)

    # Clean LLM formatting markers from final_summary — these were only
    # needed for internal parsing and should not appear in user-facing reports.
    if final_summary:
        final_summary = final_summary.strip()

        # Strip STATUS: line (was only needed for parse_llm_status)
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
    failed_step_details = extract_failed_step_details(recorded_case_data)

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
    record_data_flow_event(
        stage='agent_execution',
        event_type='case_execution_result',
        payload={
            'case_id': case.get('case_id', ''),
            'case_name': case_name,
            'case_result': case_result,
        },
        report_dir=report_dir,
    )

    # Include the modified case if dynamic steps were added
    result = {'case_result': case_result}
    if case_modified:
        result['modified_case'] = case

    # Include recorded case data for detailed reporting
    result['recorded_case'] = recorded_case_data

    return result

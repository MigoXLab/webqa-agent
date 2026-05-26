"""This module defines the main graph for the LangGraph-based UI testing
application.

It includes the definitions for all nodes and edges in the orchestrator graph.
"""

import asyncio
import datetime
import json
import logging
import os
import re
from typing import Any, Dict, List
from urllib.parse import urljoin

from langgraph.graph import END, StateGraph

from webqa_agent.crawler.crawl import CrawlHandler
from webqa_agent.crawler.deep_crawler import (DeepCrawler, ElementKey,
                                              ElementMap)
from webqa_agent.crawler.feature_detector import detect_page_features
from webqa_agent.executor.gen.agents.execute_agent import agent_worker_node
from webqa_agent.executor.gen.state.schemas import MainGraphState
from webqa_agent.executor.gen.utils.case_recorder import CentralCaseRecorder
from webqa_agent.executor.gen.utils.error_classifier import is_system_error
from webqa_agent.executor.gen.utils.summary_utils import (i18n_select,
                                                          make_user_summary)
from webqa_agent.llm.llm_api import get_last_llm_call_metrics
from webqa_agent.prompts.focused_planning_prompts import (
    get_focused_element_filtering_system_prompt,
    get_focused_element_filtering_user_prompt, get_focused_planning_prompt,
    get_focused_reflection_prompt)
from webqa_agent.prompts.test_planning_prompts import (
    get_element_filtering_system_prompt, get_element_filtering_user_prompt,
    get_planning_prompt, get_reflection_prompt)
from webqa_agent.tools.core.ui_driver import UITester
from webqa_agent.utils import Display, i18n
from webqa_agent.utils.data_flow_reporter import record_data_flow_event
from webqa_agent.utils.get_log import test_id_var
from webqa_agent.utils.log_icon import icon
from webqa_agent.utils.reporting_utils import save_test_result_json

_completed_case_count = 0  # 全局已完成 case 计数


def _case_signature(case: dict) -> str:
    """Generate a dedup signature for a test case.

    Key = normalized(name) + normalized(objective) + ordered steps text. Used
    to detect duplicate replanned cases from concurrent reflections.
    """
    name = case.get('name', '').strip().lower()
    objective = case.get('objective', '').strip().lower()
    steps = case.get('steps', [])
    step_texts = []
    for s in steps:
        if isinstance(s, dict):
            text = s.get('action', s.get('verify', ''))
            step_texts.append(str(text).strip().lower())
    steps_sig = '|'.join(step_texts)
    return f'{name}::{objective}::{steps_sig}'


def _write_json_sync(filepath: str, data: Any) -> None:
    """Synchronous JSON write, intended to be called via
    asyncio.to_thread()."""
    with open(filepath, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=4)


# Case ID 生成器（协程安全）
_case_id_counter = 0
_case_id_lock = asyncio.Lock()


async def get_next_case_id() -> str:
    """安全地获取下一个 case_id（格式: case_1, case_2, ...）"""
    global _case_id_counter
    async with _case_id_lock:
        _case_id_counter += 1
        return f'case_{_case_id_counter}'


def _resolve_report_dir(state: Dict[str, Any]) -> str:
    """Resolve report directory from state config or environment fallback.

    Args:
        state: Graph state containing report_config

    Returns:
        Resolved report directory path
    """
    report_dir = state.get('report_config', {}).get('report_dir')
    if not report_dir:
        timestamp = os.getenv('WEBQA_REPORT_TIMESTAMP')
        report_dir = os.path.join('reports', f'test_{timestamp}')
    return report_dir


def _extract_json_from_response(response: str) -> list:
    """Extract the first valid JSON array or object from an LLM response.

    Uses json.JSONDecoder.raw_decode() to parse only the first complete JSON
    value, which handles LLM outputs that contain duplicated content or
    trailing garbage text (e.g. ``[...array1...]garbage[...array2...]``).
    """
    decoder = json.JSONDecoder()

    # Try to find and parse starting from the first '[' or '{'
    for start_char in ('[', '{'):
        idx = response.find(start_char)
        if idx == -1:
            continue
        try:
            obj, _ = decoder.raw_decode(response, idx)
            if isinstance(obj, dict):
                return [obj]
            if isinstance(obj, list):
                return obj
        except json.JSONDecodeError:
            continue

    raise ValueError('No JSON array or object found in the response.')


async def plan_test_cases(state: MainGraphState) -> Dict[str, List[Dict[str, Any]]]:
    """Analyzes the initial page and generates test cases."""
    # 重置 case_id 计数器（每次新的测试运行从 case_1 开始）
    global _case_id_counter
    _case_id_counter = 0

    ui_tester = None
    s = None  # session
    sp = state.get('session_pool', None)
    llm_cfg = state.get('llm_config', None)
    business_objectives = state.get(
        'business_objectives', 'No specific business objectives provided.'
    )
    planning_mode = state.get('planning_mode', 'explore')
    language = state.get('language', 'zh-CN')
    report_dir = _resolve_report_dir(state)

    logging.debug(
        '=== Stage 0: Generating initial test plan with two-stage architecture ==='
    )

    # === Stage 0: Data Collection ===
    logging.info('Stage 0: Collecting full-page data...')
    s = await sp.acquire(timeout=300.0)
    try:
        await s.navigate_to(state['url'], cookies=state.get('cookies'))
        ui_tester = UITester(
            llm_config=llm_cfg,
            browser_session=s,
            execution_mode='gen',  # GEN mode: conservative approach for AI exploration
            language=language,
        )
        await ui_tester.initialize()

        # P0 Fix: Initialize URLValidator to prevent LLM URL hallucinations
        # Set base URL from test target for runtime validation
        ui_tester._actions.set_url_validator(state['url'])
        logging.debug(f"URLValidator initialized with base_url: {state['url']}")

        page = await ui_tester.get_current_page()
        dp = DeepCrawler(page)

        # Full-page crawl with highlights
        crawl_result = await dp.crawl(highlight=True, viewport_only=False)

        # Check for unsupported page types at the start
        if (
            hasattr(crawl_result, 'page_status')
            and crawl_result.page_status == 'UNSUPPORTED_PAGE'
        ):
            page_type = getattr(crawl_result, 'page_type', 'unknown')
            logging.warning(
                f'Initial page type ({page_type}) is unsupported, cannot generate test cases'
            )
            return {'test_cases': []}
        screenshot, _ = await ui_tester._actions.b64_page_screenshot(
            full_page=True, file_name='plan_full_page', context='agent'
        )

        # Get all interactive elements (we'll filter them in Stage 1)
        await dp.remove_marker()

        # Define simplified template for element filtering (only essential fields for LLM judgment)
        filter_template = [
            ElementKey.TAG_NAME,
            ElementKey.INNER_TEXT,
            ElementKey.ATTRIBUTES,
            ElementKey.CENTER_X,
            ElementKey.CENTER_Y,
        ]

        all_elements = dp.extract_interactive_elements(get_new_elems=False)

        # Convert to simplified format for LLM filtering using ElementMap.clean()
        filtered_elements_for_llm = ElementMap(data=all_elements).clean(
            output_template=[str(t) for t in filter_template]
        )

        # Get page text and intelligently truncate
        await dp.crawl(highlight=True, filter_text=True, viewport_only=False)
        page_text_raw = dp.get_text()
        page_text_array = json.loads(page_text_raw) if page_text_raw else []
        page_text_info = DeepCrawler.smart_truncate_page_text(
            page_text_array, max_tokens=3000
        )

        logging.info(
            f'Stage 0: Collected {len(all_elements)} interactive elements, '
            f'{len(page_text_array)} text segments '
            f"(using {page_text_info.get('estimated_tokens', 0)} tokens)"
        )

        # === Extract Page Links for Navigation Testing ===
        # Extract all navigable links using CrawlHandler
        crawl_handler = CrawlHandler(base_url=state['url'])
        all_page_links = await crawl_handler.extract_links(page)

        logging.info(
            f'Stage 0: Extracted {len(all_page_links)} navigable links from page'
        )

        # Build navigation mapping: correlate priority elements with target URLs
        # This will be done after priority_elements is available (after Stage 1)
        navigation_map = {}

        # === Stage 1: LLM-Driven Element Filtering ===
        logging.info('Stage 1: LLM-driven element filtering...')
        if planning_mode == 'focused':
            filter_system = get_focused_element_filtering_system_prompt(language)
            filter_user = get_focused_element_filtering_user_prompt(
                url=state['url'],
                focused_objective=business_objectives,
                elements=filtered_elements_for_llm,
                max_elements=30,
            )
        else:
            filter_system = get_element_filtering_system_prompt(language)
            filter_user = get_element_filtering_user_prompt(
                url=state['url'],
                business_objectives=business_objectives,
                elements=filtered_elements_for_llm,
                max_elements=50,
            )
        record_data_flow_event(
            stage='planning',
            event_type='stage1_filter_request',
            payload={
                'url': state['url'],
                'business_objectives': business_objectives,
                'filter_model': ui_tester.llm.filter_model,
                'system_prompt': filter_system,
                'user_prompt': filter_user,
                'interactive_elements_count': len(all_elements),
            },
            report_dir=report_dir,
        )

        # Use lightweight model for filtering (cost-effective)
        filter_model = ui_tester.llm.filter_model
        primary_model = ui_tester.llm.model
        if filter_model == primary_model:
            logging.debug(f'Using filter model: {filter_model} (same as primary model)')
        else:
            logging.debug(
                f'Using filter model: {filter_model} (lightweight model for cost efficiency, primary: {primary_model})'
            )

        stage1_start = datetime.datetime.now()
        filter_response = await ui_tester.llm.get_llm_response(
            system_prompt=filter_system,
            prompt=filter_user,
            images=None,  # No image needed for filtering
            model_override=filter_model,
        )
        stage1_duration = (datetime.datetime.now() - stage1_start).total_seconds()
        stage1_llm_metrics = get_last_llm_call_metrics() or {}
        record_data_flow_event(
            stage='planning',
            event_type='stage1_filter_response',
            payload={
                'url': state['url'],
                'response': filter_response,
                'duration_seconds': stage1_duration,
                'llm_metrics': stage1_llm_metrics,
            },
            report_dir=report_dir,
        )
        logging.debug(f'Stage 1 completed in {stage1_duration:.2f} seconds')

        # Parse filtering result
        try:
            selected_elements = json.loads(filter_response)
            selected_ids = [item['id'] for item in selected_elements]
            logging.info(
                f'Stage 1: LLM selected {len(selected_ids)}/{len(all_elements)} priority elements'
            )

            # Build priority elements map (keep full info for Stage 2)
            priority_elements = {
                elem_id: all_elements[elem_id]
                for elem_id in selected_ids
                if elem_id in all_elements
            }
        except Exception as e:
            logging.error(
                f'Stage 1: Element filtering failed: {e}, using fallback strategy'
            )
            logging.error(f'Stage 1: Raw response: {filter_response[:500]}...')
            # Fallback: use first 50 elements
            priority_elements = dict(list(all_elements.items())[:50])
            logging.info(
                f'Stage 1: Fallback to first {len(priority_elements)} elements'
            )

        # === Build Navigation Mapping ===
        # Correlate priority elements with links based on href attributes or text matching
        for elem_id, elem_data in priority_elements.items():
            # Check if element has href attribute (direct link)
            attributes = elem_data.get(ElementKey.ATTRIBUTES, {})
            if 'href' in attributes:
                href = attributes['href']
                # Filter out non-navigable links and build absolute URL
                if href and not href.startswith(('javascript:', 'mailto:', 'tel:')):
                    absolute_url = urljoin(state['url'], href)
                    navigation_map[elem_id] = {
                        'text': elem_data.get(ElementKey.INNER_TEXT, ''),
                        'target': absolute_url,
                    }

            # For JS-controlled navigation (e.g., onclick handlers), try text matching with links
            # This is best-effort heuristic matching
            else:
                inner_text = elem_data.get(ElementKey.INNER_TEXT, '').strip()
                if inner_text:
                    # Try to find matching link by text content
                    for link in all_page_links:
                        # Simple heuristic: if link contains element text, it's likely the target
                        if inner_text.lower() in link.lower():
                            navigation_map[elem_id] = {
                                'text': inner_text,
                                'target': link,
                                'inferred': True,  # Mark as heuristic match
                            }
                            break

        logging.info(
            f'Stage 0: Built navigation mapping for {len(navigation_map)} elements'
        )

        # === Solution A+: Lightweight Feature Detection ===
        logging.info(
            'Performing lightweight feature detection to guide tool selection...'
        )
        detected_features = await detect_page_features(page)

        # Inject concise feature hints into business objectives if features detected
        enhanced_business_objectives = business_objectives
        if detected_features:
            feature_hint = ', '.join(detected_features) + '.'

            # Add actionable hint only when dynamic/interactive features detected
            has_dynamic = any(
                kw in str(detected_features)
                for kw in ['SPA', 'API', 'MutationObserver', 'Lazy']
            )
            if has_dynamic:
                feature_hint += ' Page may reveal new content after user interactions.'

            enhanced_business_objectives = business_objectives + feature_hint
            logging.info(
                f'Feature Detection: {len(detected_features)} features detected: {detected_features}'
            )
        else:
            logging.info(
                'Feature Detection: No specific features detected, using standard tools only'
            )

        # === Stage 2: Test Case Planning with Enhanced Context ===
        logging.info('Stage 2: Test case planning with enhanced context...')
        # Get enabled custom tools from state for prompt filtering
        enabled_custom_tools = state.get('enabled_custom_tools')
        _lib = state.get('test_file_library')

        if planning_mode == 'focused':
            system_prompt, user_prompt = get_focused_planning_prompt(
                focused_objective=enhanced_business_objectives,
                state_url=state['url'],
                language=language,
                page_text_summary=page_text_info,
                priority_elements=priority_elements,
                all_page_links=all_page_links,
                navigation_map=navigation_map,
                enabled_custom_tools=enabled_custom_tools,
                file_catalog=_lib.get_catalog_for_llm() if _lib else '',
            )
        else:
            system_prompt, user_prompt = get_planning_prompt(
                business_objectives=enhanced_business_objectives,
                state_url=state['url'],
                language=language,
                page_text_summary=page_text_info,
                priority_elements=priority_elements,
                all_page_links=all_page_links,
                navigation_map=navigation_map,
                enabled_custom_tools=enabled_custom_tools,
                file_catalog=_lib.get_catalog_for_llm() if _lib else '',
            )
        record_data_flow_event(
            stage='planning',
            event_type='stage2_case_planning_request',
            payload={
                'url': state['url'],
                'business_objectives': enhanced_business_objectives,
                'system_prompt': system_prompt,
                'user_prompt': user_prompt,
                'has_screenshot': bool(screenshot),
            },
            report_dir=report_dir,
        )

        logging.info('Stage 2: Sending request to primary LLM...')
        start_time = datetime.datetime.now()
        # Get max_tokens from config or use default
        configured_max_tokens = ui_tester.llm.llm_config.get('max_tokens', 8192)

        response = await ui_tester.llm.get_llm_response(
            system_prompt=system_prompt,
            prompt=user_prompt,
            images=screenshot,
            max_tokens=configured_max_tokens,  # Use config value for flexibility
        )
        end_time = datetime.datetime.now()
        stage2_duration = (end_time - start_time).total_seconds()
        total_duration = stage1_duration + stage2_duration
        stage2_llm_metrics = get_last_llm_call_metrics() or {}
        record_data_flow_event(
            stage='planning',
            event_type='stage2_case_planning_response',
            payload={
                'url': state['url'],
                'response': response,
                'duration_seconds': stage2_duration,
                'total_duration_seconds': total_duration,
                'llm_metrics': stage2_llm_metrics,
            },
            report_dir=report_dir,
        )
        logging.info(
            f'Two-stage planning completed: Stage 1 ({stage1_duration:.2f}s) + Stage 2 ({stage2_duration:.2f}s) = Total {total_duration:.2f}s'
        )

        try:
            # Extract only the JSON part of the response, ignoring the scratchpad
            json_part_match = re.search(r'```json\s*([\s\S]*?)\s*```', response)
            if json_part_match:
                json_str = json_part_match.group(1)
                if json_str.strip().startswith('{'):
                    json_str = f'[{json_str}]'
                test_cases = json.loads(json_str)
            else:
                # Fallback: use raw_decode to parse the first complete JSON value,
                # which correctly handles LLM outputs with duplicated/trailing content
                test_cases = _extract_json_from_response(response)

            for case in test_cases:
                case['status'] = 'pending'
                case['execution_steps'] = []
                case['url'] = state['url']
                case['case_id'] = (
                    await get_next_case_id()
                )  # 为 graph 生成的 case 添加递增 ID
            try:
                report_dir = _resolve_report_dir(state)
                os.makedirs(report_dir, exist_ok=True)
                cases_path = os.path.join(report_dir, 'cases.json')
                await asyncio.to_thread(_write_json_sync, cases_path, test_cases)
                logging.debug(f'Successfully saved initial test cases to {cases_path}')
            except Exception as e:
                logging.error(f'Failed to save initial test cases to file: {e}')

            logging.debug(f'Generated {len(test_cases)} test cases.')
            record_data_flow_event(
                stage='planning',
                event_type='planned_test_cases',
                payload={
                    'url': state['url'],
                    'test_cases_count': len(test_cases),
                    'test_cases': test_cases,
                },
                report_dir=report_dir,
            )
            logging.info(
                f"{icon['rocket']} Designed {len(test_cases)} functional test cases"
            )
            return {'test_cases': test_cases}
        except (json.JSONDecodeError, IndexError, ValueError) as e:
            error_msg = f'Failed to parse test cases from LLM response: {e}'
            logging.error(f'{error_msg}\nResponse: {response}')
            record_data_flow_event(
                stage='planning',
                event_type='stage2_case_planning_parse_error',
                payload={
                    'url': state['url'],
                    'error': str(e),
                    'response': response,
                    'llm_metrics': stage2_llm_metrics,
                },
                report_dir=report_dir,
            )
            return {'test_cases': [], 'planning_error': error_msg}
    finally:
        # Cleanup UITester resources (LLM client, browser listeners)
        if ui_tester:
            try:
                await asyncio.wait_for(ui_tester.cleanup(), timeout=10.0)
            except asyncio.TimeoutError:
                logging.warning('UITester cleanup timed out after 10s in plan_test_cases')
            except Exception as cleanup_err:
                logging.warning(f'UITester cleanup failed in plan_test_cases: {cleanup_err}')

        # Release session back to pool after planning is complete
        if s and sp:
            await sp.release(s)
            logging.debug(
                f'[plan_test_cases] Released session {s.session_id} back to pool'
            )


async def run_test_cases(state: MainGraphState) -> Dict[str, Any]:
    """使用 asyncio worker pool 模式并发执行所有 test cases，实现真正的动态补位。"""
    # 重置 progress 计数（每次新的测试运行从0开始）
    global _completed_case_count
    _completed_case_count = 0

    # 支持 generate_only 模式：仅生成测试用例，不执行
    if state.get('generate_only'):
        logging.info("'generate_only' is True, skipping test case execution")
        return {
            'completed_cases': [],
            'recorded_cases': [],
            'test_cases': state.get('test_cases', []),
        }

    test_cases = state.get('test_cases', [])
    if not test_cases:
        logging.info('No test cases to execute')
        return {'completed_cases': [], 'recorded_cases': []}

    sp = state['session_pool']
    pool_size = sp.pool_size
    planning_mode = state.get('planning_mode', 'explore')
    max_replan_count = state.get('max_replan_count', 3)

    logging.info(
        f'Starting worker pool with {pool_size} workers for {len(test_cases)} cases'
    )

    # 创建共享队列并填充 test cases
    case_queue = asyncio.Queue()
    for case in test_cases:
        await case_queue.put(case)

    # 共享结果存储
    completed_cases = []
    recorded_cases = []
    all_test_cases = list(test_cases)  # 跟踪所有 test cases（包括 replanned 的）
    running_cases: set[str] = set()  # 当前正在执行的 case names（用于反思 prompt）
    replan_count = 0  # 全局 replan 计数
    results_lock = asyncio.Lock()

    # Worker 函数：持续从队列拉取 case 并执行
    async def worker(worker_id: int):
        global _completed_case_count
        nonlocal replan_count, all_test_cases  # 声明需要修改外部变量  # noqa: F824

        while True:
            case = (
                await case_queue.get()
            )  # wait for new cases (including replanned ones)

            # Check for sentinel value(None) to exit
            if case is None:
                logging.debug(f'Worker {worker_id}: Received sentinel, exiting')
                break

            case_name = case.get('name', 'UNNAMED')
            case_id = case.get('case_id', 'N/A')  # 获取 case_id 用于日志
            is_replanned = case.get(
                '_is_replanned', False
            )  # 标记是否为 replan 生成的 case

            # 跟踪正在执行的 case（用于反思 prompt，防止 replan 重复）
            async with results_lock:
                running_cases.add(case_name)

            # 设置日志上下文（case_id 用于 grep 和识别）
            log_context = f'Gen | {case_id}'
            token = test_id_var.set(log_context)

            # Set screenshot prefix to avoid filename collisions in parallel execution
            from webqa_agent.actions.action_handler import \
                screenshot_prefix_var

            prefix_token = screenshot_prefix_var.set(case_id)

            try:
                logging.info(
                    f"Worker {worker_id}: Starting case '{case_name}'"
                    + (' [REPLANNED]' if is_replanned else '')
                )

                s = None
                ui_tester = None
                failed = False

                # 获取 session（阻塞直到有可用 session）
                s = await sp.acquire(timeout=300.0)
                logging.debug(f"Worker {worker_id}: Acquired session for '{case_name}'")

                await s.navigate_to(state['url'], cookies=state.get('cookies'))

                ui_tester = UITester(
                    llm_config=state['llm_config'],
                    browser_session=s,
                    execution_mode='gen',  # GEN mode: conservative approach for AI exploration
                    language=state.get('language', 'zh-CN'),
                )
                await ui_tester.initialize()
                # P0 Fix: Initialize URLValidator to prevent LLM URL hallucinations in worker execution
                if state.get('url'):
                    ui_tester._actions.set_url_validator(state['url'])
                    logging.debug(
                        f"Worker {worker_id}: URLValidator initialized with base_url: {state['url']}"
                    )

                # Set testcase context
                ui_tester.current_case_data = case
                ui_tester.current_test_name = case_name
                ui_tester.current_test_objective = case.get(
                    'objective', case.get('name')
                )
                ui_tester.current_success_criteria = case.get('success_criteria', [])
                ui_tester.execution_history.clear()
                ui_tester.last_action_context = None

                lang = state.get('language', 'zh-CN')
                display_prefix = i18n.t(lang, 'tools.ai_function.display_text', 'Gen Mode')

                with Display.display(  # pylint: disable=not-callable
                    f'{display_prefix} - {case_name}'
                ) as tracker:
                    tracker.result = 'failed'  # default; overridden on success
                    logging.debug(f"Worker {worker_id}: Executing '{case_name}'")

                    # Execute test case via agent worker
                    # Focused mode allows longer timeout for deep E2E journeys
                    case_timeout = 3600.0 if planning_mode == 'focused' else 1800.0
                    case_timeout_minutes = int(case_timeout / 60)
                    worker_input_state = {
                        **state,
                        'test_case': case,
                        '_case_start_time': datetime.datetime.now(),  # For step budget calculation
                        '_case_timeout': case_timeout,
                    }

                    # Create case recorder OUTSIDE wait_for so it survives timeout
                    case_recorder = CentralCaseRecorder()
                    case_recorder.start_case(case_name, case_data=case)

                    # 执行 case 并添加超时
                    try:
                        result = await asyncio.wait_for(
                            agent_worker_node(
                                worker_input_state,
                                config={
                                    'configurable': {
                                        'ui_tester_instance': ui_tester,
                                        'results_lock': results_lock,  # Thread safety: Pass lock for state updates
                                        'case_recorder': case_recorder,
                                    }
                                },
                            ),
                            timeout=case_timeout,
                        )
                        logging.debug(
                            f"Worker {worker_id}: Case '{case_name}' completed"
                        )
                    except asyncio.TimeoutError:
                        logging.error(
                            f"Worker {worker_id}: Case '{case_name}' timed out ({case_timeout_minutes} minutes)"
                        )
                        failed = True
                        tracker.result = 'failed'
                        now_str = datetime.datetime.now().strftime('%Y-%m-%dT%H:%M:%S')
                        timeout_summary = f'Case timed out after {case_timeout_minutes} minutes'

                        # Harvest partial results from externalized recorder
                        lang = state.get('language', 'zh-CN')
                        case_objective = case.get('objective', case.get('name', case_name))
                        _obj = case_objective.rstrip('。！？.!?，,；;：:、… ')
                        user_summary = i18n_select(
                            lang,
                            f'{_obj}，测试运行超时，结果不完整，非产品缺陷。',
                            f'{_obj} test timed out, results incomplete, not a product defect.',
                        )
                        case_recorder.finish_case(
                            final_status='timeout',
                            final_summary=timeout_summary,
                            user_summary=user_summary,
                        )
                        partial_data = case_recorder.get_case_data() or {}
                        partial_steps = partial_data.get('steps', [])
                        total_planned = len(case.get('steps', []))
                        completed_count = len(partial_steps)

                        case_result = {
                            'case_name': case_name,
                            'case_id': case_id,
                            'status': 'failed',
                            'failure_type': 'timeout',
                            'user_summary': user_summary,
                            'reason': (
                                f'{timeout_summary}. '
                                f'{completed_count}/{total_planned} steps completed.'
                            ),
                        }
                        timeout_recorded = {
                            'name': case_name,
                            'case_id': case_id,
                            'status': 'timeout',
                            'steps': partial_steps,
                            'timed_out_at_step': completed_count + 1 if completed_count > 0 else None,
                            'total_planned_steps': total_planned,
                            'final_summary': (
                                f'{timeout_summary}. '
                                f'{completed_count} steps completed before timeout.'
                            ),
                            'user_summary': user_summary,
                            'start_time': partial_data.get('start_time', now_str),
                            'end_time': now_str,
                        }
                        # Save timeout case result to disk (consistent with normal path)
                        try:
                            report_dir = _resolve_report_dir(state)
                            # Parse case index from case_id format "case_N"
                            parts = case_id.split('_')
                            case_idx = (
                                int(parts[1]) if len(parts) > 1 and parts[1].isdigit()
                                else _completed_case_count + 1
                            )
                            await asyncio.to_thread(
                                save_test_result_json,
                                test_result=timeout_recorded,
                                report_dir=report_dir,
                                index=case_idx,
                                name=case_name,
                                category='function',
                                mode='gen',
                                sub_test_id=case_id,
                                llm_config=state.get('llm_config'),
                                browser_config=state.get('browser_config', {}),
                                target_url=state.get('url', ''),
                            )
                        except Exception as save_err:
                            logging.error(
                                f'Failed to save timeout case file for {case_name}: {save_err}'
                            )

                        async with results_lock:
                            completed_cases.append(case_result)
                            recorded_cases.append(timeout_recorded)
                            _completed_case_count += 1
                        continue

                    # 处理执行结果
                    case_result = result.get('case_result')
                    if case_result and 'case_id' not in case_result:
                        case_result['case_id'] = case_id
                    modified_case = result.get('modified_case')
                    recorded_case = result.get('recorded_case')

                    # Handle case modification when dynamic steps were added
                    if modified_case:
                        logging.info(
                            f"Worker {worker_id}: Case '{case_name}' was modified with dynamic steps"
                        )

                    # Check if reflection should be skipped (global config or critical failure)
                    skip_reflection = state.get('skip_reflection', False)

                    if not skip_reflection and case_result:
                        failure_type = case_result.get('failure_type')
                        case_status = case_result.get('status')

                        if failure_type == 'system_error':
                            logging.warning(
                                f"Worker {worker_id}: System error in '{case_name}', skipping reflection"
                            )
                            skip_reflection = True
                        elif case_status == 'failed' and failure_type in ('critical', 'infrastructure'):
                            logging.warning(
                                f"Worker {worker_id}: {failure_type} failure in '{case_name}', skipping reflection"
                            )
                            skip_reflection = True
                        elif case_status == 'failed':
                            logging.info(
                                f"Worker {worker_id}: Recoverable failure in '{case_name}', will reflect"
                            )

                    # 执行反思（非 skip_reflection 时）
                    if not skip_reflection:
                        # Create a state copy with current case_result included
                        # This ensures reflection has access to enriched metrics
                        reflect_state = dict(state)
                        async with results_lock:
                            reflect_state['test_cases'] = list(all_test_cases)
                            reflect_state['completed_cases'] = (
                                list(completed_cases) + ([case_result] if case_result else [])
                            )
                            reflect_state['running_cases'] = list(running_cases - {case_name})

                        reflect_result = await _do_reflection(
                            ui_tester, reflect_state, case_name, case_id
                        )

                        # 处理 REPLAN 结果：将新 cases 加入队列
                        if reflect_result.get('is_replan') and reflect_result.get(
                            'replanned_cases'
                        ):
                            async with results_lock:
                                if replan_count < max_replan_count:
                                    new_cases = reflect_result['replanned_cases']

                                    # 硬约束：入队前去重（对照最新 all_test_cases）
                                    existing_sigs = {_case_signature(c) for c in all_test_cases}
                                    unique_cases = []
                                    for nc in new_cases:
                                        sig = _case_signature(nc)
                                        if sig not in existing_sigs:
                                            unique_cases.append(nc)
                                            existing_sigs.add(sig)
                                        else:
                                            logging.info(
                                                f'Worker {worker_id}: Skipped duplicate '
                                                f"replanned case '{nc.get('name')}'"
                                            )

                                    if not unique_cases:
                                        logging.info(
                                            f'Worker {worker_id}: All replanned cases from '
                                            f"'{case_name}' are duplicates, skipping"
                                        )
                                    else:
                                        replan_count += 1

                                        # 为新 cases 添加元数据
                                        for new_case in unique_cases:
                                            new_case['status'] = 'pending'
                                            new_case['execution_steps'] = []
                                            new_case['url'] = state['url']
                                            new_case['case_id'] = (
                                                await get_next_case_id()
                                            )
                                            new_case['_is_replanned'] = True
                                            new_case['_replan_source'] = case_name

                                        # 加入队列供 workers 消费
                                        for new_case in unique_cases:
                                            await case_queue.put(new_case)
                                            all_test_cases.append(new_case)
                                        record_data_flow_event(
                                            stage='agent_execution',
                                            event_type='replan_enqueue',
                                            payload={
                                                'case_id': case_id,
                                                'case_name': case_name,
                                                'replan_count': replan_count,
                                                'max_replan_count': max_replan_count,
                                                'new_cases_count': len(unique_cases),
                                                'new_cases': unique_cases,
                                            },
                                            report_dir=_resolve_report_dir(state),
                                        )

                                        logging.info(
                                            f"Worker {worker_id}: REPLAN triggered by '{case_name}', "
                                            f'added {len(unique_cases)} new cases to queue '
                                            f'(replan #{replan_count}/{max_replan_count})'
                                        )

                                        # 保存更新后的 cases.json
                                        try:
                                            report_dir = _resolve_report_dir(state)
                                            os.makedirs(report_dir, exist_ok=True)
                                            cases_path = os.path.join(
                                                report_dir, 'cases.json'
                                            )
                                            await asyncio.to_thread(
                                                _write_json_sync, cases_path, list(all_test_cases)
                                            )
                                            logging.debug(
                                                f'Saved updated test cases with replanned cases to {cases_path}'
                                            )
                                        except Exception as save_err:
                                            logging.error(
                                                f'Failed to save replanned cases: {save_err}'
                                            )
                                else:
                                    logging.warning(
                                        f"Worker {worker_id}: REPLAN requested by '{case_name}' but "
                                        f'max replan count ({max_replan_count}) reached, skipping'
                                    )

                    # Set tracker result for progress reporting
                    if case_result:
                        tracker.result = case_result.get('status', 'failed')
                    else:
                        tracker.result = 'failed'

                    # 保存 case 结果
                    try:
                        report_dir = _resolve_report_dir(state)

                        # 从 case_id 提取索引
                        try:
                            case_idx = int(case_id.split('_')[1])
                        except (IndexError, ValueError):
                            case_idx = _completed_case_count + 1

                        if recorded_case:
                            if isinstance(recorded_case, dict):
                                recorded_case['sub_test_id'] = case_id

                            await asyncio.to_thread(
                                save_test_result_json,
                                test_result=recorded_case,
                                report_dir=report_dir,
                                index=case_idx,
                                name=case_name,
                                category='function',
                                mode='gen',
                                sub_test_id=case_id,
                                llm_config=state.get('llm_config'),
                                browser_config=state.get('browser_config', {}),
                                target_url=state.get('url', ''),
                            )
                    except Exception as save_err:
                        logging.error(
                            f'Failed to save individual case file for {case_name}: {save_err}'
                        )

                    async with results_lock:
                        if case_result:
                            completed_cases.append(case_result)
                        if recorded_case:
                            recorded_cases.append(recorded_case)

                        _completed_case_count += 1
                        total = len(all_test_cases)
                        pending = case_queue.qsize()
                        logging.info(
                            f"{icon['hourglass']} Progress: {_completed_case_count}/{total} cases completed ({pending} pending)"
                        )

            except Exception as e:
                logging.error(
                    f"Worker {worker_id}: Exception during '{case_name}': {e}",
                    exc_info=True,
                )
                failed = True
                err_status, err_failure_type = (
                    ('warning', 'system_error') if is_system_error(e)
                    else ('failed', 'unexpected_error')
                )
                tracker.result = err_status
                lang = state.get('language', 'zh-CN')
                case_objective = case.get('objective', case.get('name', case_name))

                if err_status == 'warning':
                    user_summary = make_user_summary(lang, 'warning', case_objective, exception=e)
                else:
                    err_reason = i18n_select(
                        lang, '测试执行异常终止。', 'Test execution terminated unexpectedly.',
                    )
                    user_summary = make_user_summary(
                        lang, 'failed', case_objective, reason=err_reason,
                    )

                now_str = datetime.datetime.now().strftime('%Y-%m-%dT%H:%M:%S')
                err_summary = f'{type(e).__name__}: {str(e)}'

                # Persist partial data via case_recorder (mirrors timeout handler)
                case_recorder.finish_case(
                    final_status=err_status,
                    final_summary=err_summary,
                    user_summary=user_summary,
                )
                partial_data = case_recorder.get_case_data() or {}
                partial_steps = partial_data.get('steps', [])

                case_result = {
                    'case_name': case_name,
                    'case_id': case_id,
                    'status': err_status,
                    'failure_type': err_failure_type,
                    'user_summary': user_summary,
                    'reason': err_summary,
                }
                exception_recorded = {
                    'name': case_name,
                    'case_id': case_id,
                    'status': err_status,
                    'failure_type': err_failure_type,
                    'steps': partial_steps,
                    'final_summary': err_summary,
                    'user_summary': user_summary,
                    'start_time': partial_data.get('start_time', now_str),
                    'end_time': now_str,
                }

                # Save exception case result to disk (consistent with timeout path)
                try:
                    report_dir = _resolve_report_dir(state)
                    # Parse case index from case_id format "case_N"
                    parts = case_id.split('_')
                    case_idx = (
                        int(parts[1]) if len(parts) > 1 and parts[1].isdigit()
                        else _completed_case_count + 1
                    )
                    await asyncio.to_thread(
                        save_test_result_json,
                        test_result=exception_recorded,
                        report_dir=report_dir,
                        index=case_idx,
                        name=case_name,
                        category='function',
                        mode='gen',
                        sub_test_id=case_id,
                        llm_config=state.get('llm_config'),
                        browser_config=state.get('browser_config', {}),
                        target_url=state.get('url', ''),
                    )
                except Exception as save_err:
                    logging.error(
                        f'Failed to save exception case file for {case_name}: {save_err}'
                    )

                async with results_lock:
                    completed_cases.append(case_result)
                    recorded_cases.append(exception_recorded)
                    _completed_case_count += 1

            finally:
                # 从运行列表中移除
                async with results_lock:
                    running_cases.discard(case_name)

                # 重置日志上下文
                test_id_var.reset(token)
                screenshot_prefix_var.reset(prefix_token)

                # Cleanup UITester resources (LLM client, browser listeners, etc.)
                if ui_tester:
                    try:
                        await asyncio.wait_for(ui_tester.cleanup(), timeout=10.0)
                    except asyncio.TimeoutError:
                        logging.warning(
                            f'Worker {worker_id}: UITester cleanup timed out after 10s'
                        )
                    except Exception as cleanup_err:
                        logging.warning(
                            f'Worker {worker_id}: UITester cleanup failed: {cleanup_err}'
                        )

                # Release or close session based on remaining work
                if s:
                    # Check if there are more cases waiting in the queue
                    # If queue is empty, close the session to free browser resources
                    # If queue has pending cases, release back to pool for reuse
                    if case_queue.qsize() == 0:
                        # Use keep_alive=False to close session AND release semaphore
                        await sp.release(s, keep_alive=False)
                        logging.info(
                            f"Worker {worker_id}: Released and closed session for '{case_name}' (no more pending cases)"
                        )
                    else:
                        await sp.release(s, failed=failed)
                        logging.debug(
                            f"Worker {worker_id}: Released session for '{case_name}' to pool (failed={failed})"
                        )

                # Mark task as done AFTER session is handled, so join() only unblocks
                # when all resources are properly managed
                case_queue.task_done()

    # 启动 K 个 workers
    workers = [
        asyncio.create_task(worker(i), name=f'worker-{i}') for i in range(pool_size)
    ]

    # Wait for all items in the queue to be processed (including replanned cases)
    # This blocks until task_done() has been called for every item that was put into the queue
    await case_queue.join()

    # All work is done - send sentinel values (None) to signal workers to exit
    for _ in range(pool_size):
        await case_queue.put(None)

    # Wait for all workers to cleanly exit after receiving sentinel
    await asyncio.gather(*workers, return_exceptions=True)

    logging.info(
        f'Worker pool completed: {len(completed_cases)} cases executed '
        f'(initial: {len(test_cases)}, replanned: {len(all_test_cases) - len(test_cases)}, '
        f'replan count: {replan_count}/{max_replan_count})'
    )
    record_data_flow_event(
        stage='summary',
        event_type='run_test_cases_summary',
        payload={
            'initial_test_cases_count': len(test_cases),
            'all_test_cases_count': len(all_test_cases),
            'completed_cases_count': len(completed_cases),
            'recorded_cases_count': len(recorded_cases),
            'replan_count': replan_count,
            'max_replan_count': max_replan_count,
            'all_test_cases': all_test_cases,
            'completed_cases': completed_cases,
        },
        report_dir=_resolve_report_dir(state),
    )
    # Synchronize execution results to cases.json
    # This ensures cases.json reflects actual execution status
    try:
        from pathlib import Path

        from webqa_agent.executor.gen.utils.case_synchronizer import \
            CaseJsonSynchronizer

        # Get report directory
        report_dir = _resolve_report_dir(state)

        cases_json_path = Path(report_dir) / 'cases.json'

        # Only sync if cases.json exists and we have recorded cases
        if cases_json_path.exists() and recorded_cases:
            synchronizer = CaseJsonSynchronizer(cases_json_path)
            await asyncio.to_thread(synchronizer.sync_cases, all_test_cases, recorded_cases)
            logging.info(
                f'Synchronized {len(recorded_cases)} execution results to cases.json'
            )
        elif not recorded_cases:
            logging.warning('No recorded cases to sync to cases.json')
        else:
            logging.warning(f'cases.json not found at {cases_json_path}, skipping sync')

    except Exception as sync_err:
        # Don't fail the entire execution if sync fails
        logging.error(f'Failed to synchronize cases.json: {sync_err}', exc_info=True)

    return {
        'completed_cases': completed_cases,
        'recorded_cases': recorded_cases,
        'test_cases': all_test_cases,  # 包含所有 test cases（原始 + replanned）
        'replan_count': replan_count,
    }


async def _do_reflection(
    ui_tester: UITester, state: dict, case_name: str, case_id: str
) -> dict:
    """单个 case 的反思分析，在 execute_single_case 内部调用实现并发反思。"""
    try:
        page = await ui_tester.get_current_page()
        dp = DeepCrawler(page)
        curr = await dp.crawl(highlight=True, viewport_only=False)

        reflect_template = [
            str(ElementKey.TAG_NAME),
            str(ElementKey.INNER_TEXT),
            str(ElementKey.ATTRIBUTES),
            str(ElementKey.CENTER_X),
            str(ElementKey.CENTER_Y),
        ]
        page_content_summary = curr.clean_dict(reflect_template)
        screenshot, _ = await ui_tester._actions.b64_page_screenshot(
            full_page=True, file_name=f'reflection_{case_name}', context='agent'
        )
        await dp.remove_marker()

        language = state.get('language', 'zh-CN')
        enabled_custom_tools = state.get('enabled_custom_tools')
        planning_mode = state.get('planning_mode', 'explore')
        if planning_mode == 'focused':
            system_prompt, user_prompt = get_focused_reflection_prompt(
                focused_objective=state.get('business_objectives'),
                current_plan=state.get('test_cases', []),
                completed_cases=state.get('completed_cases', []),
                page_content_summary=page_content_summary,
                language=language,
                enabled_custom_tools=enabled_custom_tools,
                running_cases=state.get('running_cases', []),
            )
        else:
            system_prompt, user_prompt = get_reflection_prompt(
                business_objectives=state.get('business_objectives'),
                current_plan=state.get('test_cases', []),
                completed_cases=state.get('completed_cases', []),
                page_content_summary=page_content_summary,
                language=language,
                enabled_custom_tools=enabled_custom_tools,
                running_cases=state.get('running_cases', []),
            )
        report_dir = _resolve_report_dir(state)
        record_data_flow_event(
            stage='planning',
            event_type='reflection_request',
            payload={
                'case_id': case_id,
                'case_name': case_name,
                'system_prompt': system_prompt,
                'user_prompt': user_prompt,
            },
            report_dir=report_dir,
        )

        logging.info(f'[{case_name}] Sending reflection request to LLM...')
        reflection_start = datetime.datetime.now()
        response_str = await ui_tester.llm.get_llm_response(
            system_prompt=system_prompt, prompt=user_prompt, images=screenshot
        )
        reflection_duration = (datetime.datetime.now() - reflection_start).total_seconds()
        reflection_llm_metrics = get_last_llm_call_metrics() or {}

        decision_data = json.loads(response_str)
        decision = decision_data.get('decision', 'CONTINUE').upper()
        logging.debug(f'[{case_name}] Reflection decision: {decision}')
        record_data_flow_event(
            stage='planning',
            event_type='reflection_response',
            payload={
                'case_id': case_id,
                'case_name': case_name,
                'decision': decision,
                'response': decision_data,
                'duration_seconds': reflection_duration,
                'llm_metrics': reflection_llm_metrics,
            },
            report_dir=report_dir,
        )

        result = {'reflection_history': [decision_data]}
        if decision == 'REPLAN' and decision_data.get('new_plan'):
            result['is_replan'] = True
            result['replanned_cases'] = decision_data['new_plan']
            logging.info(
                f"[{case_name}] REPLAN with {len(decision_data['new_plan'])} new cases"
            )
        return result

    except json.JSONDecodeError as e:
        logging.error(f'[{case_name}] Failed to parse reflection response: {e}')
        # reflection_duration already computed before json.loads
        record_data_flow_event(
            stage='planning',
            event_type='reflection_response',
            payload={
                'case_id': case_id,
                'case_name': case_name,
                'decision': 'CONTINUE',
                'duration_seconds': reflection_duration,
                'error': str(e),
            },
            report_dir=_resolve_report_dir(state),
        )
        return {
            'reflection_history': [
                {
                    'decision': 'CONTINUE',
                    'reasoning': f'JSON error: {e}',
                    'new_plan': [],
                }
            ]
        }
    except Exception as e:
        reflection_duration = (datetime.datetime.now() - reflection_start).total_seconds()
        logging.error(f'[{case_name}] Reflection error: {e}')
        record_data_flow_event(
            stage='planning',
            event_type='reflection_response',
            payload={
                'case_id': case_id,
                'case_name': case_name,
                'decision': 'CONTINUE',
                'duration_seconds': reflection_duration,
                'error': str(e),
            },
            report_dir=_resolve_report_dir(state),
        )
        return {
            'reflection_history': [
                {'decision': 'CONTINUE', 'reasoning': str(e), 'new_plan': []}
            ]
        }


async def aggregate_results(state: MainGraphState) -> Dict[str, Dict[str, Any]]:
    """Aggregates the results from all test case workers."""
    logging.debug('Aggregating test results...')
    total_cases = len(state.get('test_cases', []))
    summary = {
        'total_cases': total_cases,
        'completed_summary': state['completed_cases'],
    }
    logging.debug(f'Final summary: {json.dumps(summary, indent=2)}')
    return {'final_report': summary}


async def cleanup_session(state: MainGraphState) -> Dict:
    """Cleanup hook for graph workflow completion.

    Closes any remaining browser sessions in the pool. Workers close their
    sessions directly when no more pending cases exist, or release back to pool
    for reuse when more cases are waiting. This node serves as a safety net for
    any sessions that weren't closed during normal execution.
    """
    logging.debug('Graph workflow cleanup node reached')

    # Close any remaining sessions in the pool (safety net)
    sp = state.get('session_pool')
    if sp:
        await sp.close_all()
        logging.info('Closed all remaining browser sessions in session pool')

    return {}


# Define the main graph
workflow = StateGraph(MainGraphState)

# Add nodes
workflow.add_node('plan_test_cases', plan_test_cases)
workflow.add_node('run_test_cases', run_test_cases)  # 新增：worker pool 节点
workflow.add_node('aggregate_results', aggregate_results)
workflow.add_node('cleanup_session', cleanup_session)

# Add edges - 简化的图结构
workflow.set_entry_point('plan_test_cases')
workflow.add_edge('plan_test_cases', 'run_test_cases')  # 直接进入 worker pool
workflow.add_edge('run_test_cases', 'aggregate_results')  # worker pool 完成后聚合结果
workflow.add_edge('aggregate_results', 'cleanup_session')
workflow.add_edge('cleanup_session', END)

# Compile the graph
app = workflow.compile()

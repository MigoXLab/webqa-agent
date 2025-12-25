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

from langgraph.graph import END, StateGraph

from webqa_agent.crawler.deep_crawler import (DeepCrawler, ElementKey,
                                              ElementMap)
from webqa_agent.testers.case_gen.agents.execute_agent import agent_worker_node
from webqa_agent.testers.case_gen.prompts.planning_prompts import (
    get_element_filtering_system_prompt, get_element_filtering_user_prompt,
    get_planning_prompt, get_reflection_prompt)
from webqa_agent.testers.case_gen.state.schemas import MainGraphState
from webqa_agent.utils import Display
from webqa_agent.testers.function_tester import UITester
from webqa_agent.utils.log_icon import icon


_completed_case_count = 0  # 全局已完成 case 计数


async def plan_test_cases(state: MainGraphState) -> Dict[str, List[Dict[str, Any]]]:
    """Analyzes the initial page and generates test cases."""
    ui_tester = None
    s = None  # session
    sp = state.get("session_pool", None)
    llm_cfg = state.get("llm_config", None)
    business_objectives = state.get("business_objectives", "No specific business objectives provided.")
    language = state.get('language', 'zh-CN')

    logging.debug("=== Stage 0: Generating initial test plan with two-stage architecture ===")

    # === Stage 0: Data Collection ===
    logging.info("Stage 0: Collecting full-page data...")
    s = await sp.acquire(timeout=120.0)
    try:
        await s.navigate_to(state["url"], cookies=state.get("cookies"))
        ui_tester = UITester(llm_config=llm_cfg, browser_session=s)
        await ui_tester.initialize()
        page = await ui_tester.get_current_page()
        dp = DeepCrawler(page)

        # Full-page crawl with highlights
        crawl_result = await dp.crawl(highlight=True, viewport_only=False)

        # Check for unsupported page types at the start
        if hasattr(crawl_result, 'page_status') and crawl_result.page_status == "UNSUPPORTED_PAGE":
            page_type = getattr(crawl_result, 'page_type', 'unknown')
            logging.warning(f"Initial page type ({page_type}) is unsupported, cannot generate test cases")
            return {"test_cases": []}
        screenshot = await ui_tester._actions.b64_page_screenshot(
            full_page=True,
            file_name="plan_full_page",
            context="agent"
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
            page_text_array,
            max_tokens=3000
        )

        logging.info(
            f"Stage 0: Collected {len(all_elements)} interactive elements, "
            f"{len(page_text_array)} text segments "
            f"(using {page_text_info.get('estimated_tokens', 0)} tokens)"
        )

        # === Stage 1: LLM-Driven Element Filtering ===
        logging.info("Stage 1: LLM-driven element filtering...")
        filter_system = get_element_filtering_system_prompt(language)
        filter_user = get_element_filtering_user_prompt(
            url=state["url"],
            business_objectives=business_objectives,
            elements=filtered_elements_for_llm,
            max_elements=50
        )

        # Use lightweight model for filtering (cost-effective)
        filter_model = ui_tester.llm.filter_model
        primary_model = ui_tester.llm.model
        if filter_model == primary_model:
            logging.debug(f"Using filter model: {filter_model} (same as primary model)")
        else:
            logging.debug(f"Using filter model: {filter_model} (lightweight model for cost efficiency, primary: {primary_model})")

        stage1_start = datetime.datetime.now()
        filter_response = await ui_tester.llm.get_llm_response(
            system_prompt=filter_system,
            prompt=filter_user,
            images=None,  # No image needed for filtering
            model_override=filter_model
        )
        stage1_duration = (datetime.datetime.now() - stage1_start).total_seconds()
        logging.debug(f"Stage 1 completed in {stage1_duration:.2f} seconds")

        # Parse filtering result
        try:
            selected_elements = json.loads(filter_response)
            selected_ids = [item["id"] for item in selected_elements]
            logging.info(f"Stage 1: LLM selected {len(selected_ids)}/{len(all_elements)} priority elements")

            # Build priority elements map (keep full info for Stage 2)
            priority_elements = {
                elem_id: all_elements[elem_id]
                for elem_id in selected_ids
                if elem_id in all_elements
            }
        except Exception as e:
            logging.error(f"Stage 1: Element filtering failed: {e}, using fallback strategy")
            logging.error(f"Stage 1: Raw response: {filter_response[:500]}...")
            # Fallback: use first 50 elements
            priority_elements = dict(list(all_elements.items())[:50])
            logging.info(f"Stage 1: Fallback to first {len(priority_elements)} elements")

        # === Stage 2: Test Case Planning with Enhanced Context ===
        logging.info("Stage 2: Test case planning with enhanced context...")
        system_prompt, user_prompt = get_planning_prompt(
            business_objectives=business_objectives,
            state_url=state["url"],
            language=language,
            page_text_summary=page_text_info,
            priority_elements=priority_elements,
        )

        logging.info("Stage 2: Sending request to primary LLM...")
        start_time = datetime.datetime.now()

        # Get max_tokens from config or use default
        configured_max_tokens = ui_tester.llm.llm_config.get("max_tokens", 8192)

        response = await ui_tester.llm.get_llm_response(
            system_prompt=system_prompt,
            prompt=user_prompt,
            images=screenshot,
            max_tokens=configured_max_tokens  # Use config value for flexibility
        )

        end_time = datetime.datetime.now()
        stage2_duration = (end_time - start_time).total_seconds()
        total_duration = stage1_duration + stage2_duration
        logging.info(f"Two-stage planning completed: Stage 1 ({stage1_duration:.2f}s) + Stage 2 ({stage2_duration:.2f}s) = Total {total_duration:.2f}s")

        try:
            # Extract only the JSON part of the response, ignoring the scratchpad
            json_part_match = re.search(r"```json\s*([\s\S]*?)\s*```", response)
            if not json_part_match:
                # Fallback for responses that might not have the json markdown
                json_str = ""
                # A more robust way to find the JSON array
                start_bracket = response.find("[")
                end_bracket = response.rfind("]")
                if start_bracket != -1 and end_bracket != -1 and end_bracket > start_bracket:
                    json_str = response[start_bracket : end_bracket + 1]
                else:  # Try with curly braces for single object
                    start_brace = response.find("{")
                    end_brace = response.rfind("}")
                    if start_brace != -1 and end_brace != -1 and end_brace > start_brace:
                        # Wrap in array brackets if it's a single object
                        json_str = f"[{response[start_brace:end_brace + 1]}]"
                if not json_str:
                    raise ValueError("No JSON array or object found in the response.")
            else:
                json_str = json_part_match.group(1)

            # Wrap single object in a list if necessary
            if json_str.strip().startswith("{"):
                json_str = f"[{json_str}]"

            test_cases = json.loads(json_str)

            for case in test_cases:
                case["status"] = "pending"
                case["completed_steps"] = []
                case["test_context"] = {}
                case["url"] = state["url"]

            try:
                timestamp = os.getenv("WEBQA_REPORT_TIMESTAMP")
                report_dir = f"./reports/test_{timestamp}"
                os.makedirs(report_dir, exist_ok=True)
                cases_path = os.path.join(report_dir, "cases.json")
                with open(cases_path, "w", encoding="utf-8") as f:
                    json.dump(test_cases, f, ensure_ascii=False, indent=4)
                logging.debug(f"Successfully saved initial test cases to {cases_path}")
            except Exception as e:
                logging.error(f"Failed to save initial test cases to file: {e}")

            logging.debug(f"Generated {len(test_cases)} test cases.")
            logging.info(f"{icon['rocket']} Designed {len(test_cases)} functional test cases")
            return {"test_cases": test_cases}
        except (json.JSONDecodeError, IndexError, ValueError) as e:
            logging.error(f"Failed to parse test cases from LLM response: {e}\nResponse: {response}")
            return {"test_cases": []}
    finally:
        # Release session back to pool after planning is complete
        if s and sp:
            await sp.release(s)
            logging.debug(f"[plan_test_cases] Released session {s.session_id} back to pool")


async def run_test_cases(state: MainGraphState) -> Dict[str, Any]:
    """使用 asyncio worker pool 模式并发执行所有 test cases，实现真正的动态补位。"""
    # 重置全局计数（每次新的测试运行从0开始）
    global _completed_case_count
    _completed_case_count = 0

    # 支持 generate_only 模式：仅生成测试用例，不执行
    if state.get("generate_only"):
        logging.info("'generate_only' is True, skipping test case execution")
        return {
            "completed_cases": [],
            "recorded_cases": [],
            "test_cases": state.get("test_cases", []),
        }

    test_cases = state.get("test_cases", [])
    if not test_cases:
        logging.info("No test cases to execute")
        return {"completed_cases": [], "recorded_cases": []}

    sp = state["session_pool"]
    pool_size = sp.pool_size
    max_replan_count = state.get("max_replan_count", 3)  # 限制最大 replan 次数，防止无限循环

    logging.info(f"Starting worker pool with {pool_size} workers for {len(test_cases)} cases")

    # 创建共享队列并填充 test cases
    case_queue = asyncio.Queue()
    for case in test_cases:
        await case_queue.put(case)

    # 共享结果存储
    completed_cases = []
    recorded_cases = []
    all_test_cases = list(test_cases)  # 跟踪所有 test cases（包括 replanned 的）
    replan_count = 0  # 全局 replan 计数
    results_lock = asyncio.Lock()

    # Worker 函数：持续从队列拉取 case 并执行
    async def worker(worker_id: int):
        nonlocal replan_count, all_test_cases  # 声明需要修改外部变量

        while True:
            case = await case_queue.get()  # wait for new cases (including replanned ones)

            # Check for sentinel value(None) to exit
            if case is None:
                logging.debug(f"Worker {worker_id}: Received sentinel, exiting")
                break

            case_name = case.get("name", "UNNAMED")
            is_replanned = case.get("_is_replanned", False)  # 标记是否为 replan 生成的 case
            logging.info(f"Worker {worker_id}: Starting case '{case_name}'" + (" [REPLANNED]" if is_replanned else ""))

            s = None
            failed = False

            try:
                # 获取 session（阻塞直到有可用 session）
                s = await sp.acquire(timeout=120.0)
                logging.debug(f"Worker {worker_id}: Acquired session for '{case_name}'")

                await s.navigate_to(state["url"], cookies=state.get("cookies"))

                ui_tester = UITester(llm_config=state["llm_config"], browser_session=s)
                await ui_tester.initialize()

                # Set testcase context
                ui_tester.current_test_objective = case.get("objective", case.get("name"))
                ui_tester.current_success_criteria = case.get("success_criteria", [])
                ui_tester.execution_history.clear()
                ui_tester.last_action_context = None

                lang = state.get('language', 'zh-CN')
                default_text = '智能功能测试' if lang == 'zh-CN' else 'AI Function Test'

                with Display.display(f"{default_text} - {case_name}"):
                    logging.debug(f"Worker {worker_id}: Executing '{case_name}'")

                    # Execute test case via agent worker
                    worker_input_state = {
                        "test_case": case,
                        "completed_cases": state.get("completed_cases", []),
                        "dynamic_step_generation": state.get("dynamic_step_generation", {
                            "enabled": False,
                            "max_dynamic_steps": 0,
                            "min_elements_threshold": 2
                        })
                    }

                    # 执行 case 并添加超时
                    try:
                        result = await asyncio.wait_for(
                            agent_worker_node(worker_input_state, config={"configurable": {"ui_tester_instance": ui_tester}}),
                            timeout=1800
                        )
                        logging.debug(f"Worker {worker_id}: Case '{case_name}' completed")
                    except asyncio.TimeoutError:
                        logging.error(f"Worker {worker_id}: Case '{case_name}' timed out (30 minutes)")
                        failed = True
                        case_result = {
                            "case_name": case_name,
                            "status": "failed",
                            "failure_type": "timeout",
                            "reason": "Case execution timed out after 30 minutes"
                        }
                        async with results_lock:
                            completed_cases.append(case_result)
                        continue

                    # 处理执行结果
                    case_result = result.get("case_result")
                    modified_case = result.get("modified_case")
                    recorded_case = result.get("recorded_case")

                    # Handle case modification when dynamic steps were added
                    if modified_case:
                        logging.info(f"Worker {worker_id}: Case '{case_name}' was modified with dynamic steps")

                    # Check if this is a critical failure that should skip reflection
                    skip_reflection = False
                    if case_result and case_result.get("status") == "failed":
                        failure_type = case_result.get("failure_type")
                        if failure_type == "critical":
                            logging.warning(f"Worker {worker_id}: Critical failure in '{case_name}', skipping reflection")
                            skip_reflection = True
                        else:
                            logging.info(f"Worker {worker_id}: Recoverable failure in '{case_name}', will reflect")

                    # 执行反思（非 skip_reflection 时）
                    if not skip_reflection:
                        reflect_result = await _do_reflection(ui_tester, dict(state), case_name)

                        # 处理 REPLAN 结果：将新 cases 加入队列
                        if reflect_result.get("is_replan") and reflect_result.get("replanned_cases"):
                            async with results_lock:
                                if replan_count < max_replan_count:
                                    new_cases = reflect_result["replanned_cases"]
                                    replan_count += 1

                                    # 为新 cases 添加元数据
                                    for new_case in new_cases:
                                        new_case["status"] = "pending"
                                        new_case["completed_steps"] = []
                                        new_case["test_context"] = {}
                                        new_case["url"] = state["url"]
                                        new_case["_is_replanned"] = True  # 标记为 replan 生成
                                        new_case["_replan_source"] = case_name  # 记录来源 case

                                    # 加入队列供 workers 消费
                                    for new_case in new_cases:
                                        await case_queue.put(new_case)  # 计数器+1
                                        all_test_cases.append(new_case)

                                    logging.info(
                                        f"Worker {worker_id}: REPLAN triggered by '{case_name}', "
                                        f"added {len(new_cases)} new cases to queue "
                                        f"(replan #{replan_count}/{max_replan_count})"
                                    )

                                    # 保存更新后的 cases.json
                                    try:
                                        timestamp = os.getenv("WEBQA_REPORT_TIMESTAMP")
                                        report_dir = f"./reports/test_{timestamp}"
                                        os.makedirs(report_dir, exist_ok=True)
                                        cases_path = os.path.join(report_dir, "cases.json")
                                        with open(cases_path, "w", encoding="utf-8") as f:
                                            json.dump(all_test_cases, f, ensure_ascii=False, indent=4)
                                        logging.debug(f"Saved updated test cases with replanned cases to {cases_path}")
                                    except Exception as save_err:
                                        logging.error(f"Failed to save replanned cases: {save_err}")
                                else:
                                    logging.warning(
                                        f"Worker {worker_id}: REPLAN requested by '{case_name}' but "
                                        f"max replan count ({max_replan_count}) reached, skipping"
                                    )

                    # 收集结果
                    async with results_lock:
                        if case_result:
                            completed_cases.append(case_result)
                        if recorded_case:
                            recorded_cases.append(recorded_case)

                        # 更新进度
                        global _completed_case_count
                        _completed_case_count += 1
                        total = len(all_test_cases)
                        pending = case_queue.qsize()
                        logging.info(f"{icon['hourglass']} Progress: {_completed_case_count}/{total} cases completed ({pending} pending)")

            except Exception as e:
                logging.error(f"Worker {worker_id}: Exception during '{case_name}': {e}", exc_info=True)
                failed = True
                async with results_lock:
                    completed_cases.append({
                        "case_name": case_name,
                        "status": "failed",
                        "failure_type": "unexpected_error",
                        "reason": f"Unexpected error: {str(e)}"
                    })
                    _completed_case_count += 1

            finally:
                # Release or close session based on remaining work
                if s:
                    # Check if there are more cases waiting in the queue
                    # If queue is empty, close the session to free browser resources
                    # If queue has pending cases, release back to pool for reuse
                    if case_queue.qsize() == 0:
                        await s.close()
                        logging.info(f"Worker {worker_id}: Closed session for '{case_name}' (no more pending cases)")
                    else:
                        await sp.release(s, failed=failed)
                        logging.debug(f"Worker {worker_id}: Released session for '{case_name}' to pool (failed={failed})")

                # Mark task as done AFTER session is handled, so join() only unblocks
                # when all resources are properly managed
                case_queue.task_done()

    # 启动 K 个 workers
    workers = [asyncio.create_task(worker(i), name=f"worker-{i}") for i in range(pool_size)]

    # Wait for all items in the queue to be processed (including replanned cases)
    # This blocks until task_done() has been called for every item that was put into the queue
    await case_queue.join()

    # All work is done - send sentinel values (None) to signal workers to exit
    for _ in range(pool_size):
        await case_queue.put(None)

    # Wait for all workers to cleanly exit after receiving sentinel
    await asyncio.gather(*workers, return_exceptions=True)

    logging.info(
        f"Worker pool completed: {len(completed_cases)} cases executed "
        f"(initial: {len(test_cases)}, replanned: {len(all_test_cases) - len(test_cases)}, "
        f"replan count: {replan_count}/{max_replan_count})"
    )

    return {
        "completed_cases": completed_cases,
        "recorded_cases": recorded_cases,
        "test_cases": all_test_cases,  # 包含所有 test cases（原始 + replanned）
        "replan_count": replan_count,
    }


async def _do_reflection(ui_tester: UITester, state: dict, case_name: str) -> dict:
    """单个 case 的反思分析，在 execute_single_case 内部调用实现并发反思。"""
    try:
        page = await ui_tester.get_current_page()
        dp = DeepCrawler(page)
        curr = await dp.crawl(highlight=True, viewport_only=False)

        reflect_template = [
            str(ElementKey.TAG_NAME), str(ElementKey.INNER_TEXT),
            str(ElementKey.ATTRIBUTES), str(ElementKey.CENTER_X), str(ElementKey.CENTER_Y)
        ]
        page_content_summary = curr.clean_dict(reflect_template)
        screenshot = await ui_tester._actions.b64_page_screenshot(
            full_page=True, file_name=f"reflection_{case_name}", context="agent"
        )
        await dp.remove_marker()

        language = state.get('language', 'zh-CN')
        system_prompt, user_prompt = get_reflection_prompt(
            business_objectives=state.get("business_objectives"),
            current_plan=state.get("test_cases", []),
            completed_cases=state.get("completed_cases", []),
            page_content_summary=page_content_summary,
            language=language,
        )

        logging.info(f"[{case_name}] Sending reflection request to LLM...")
        response_str = await ui_tester.llm.get_llm_response(
            system_prompt=system_prompt, prompt=user_prompt, images=screenshot
        )

        decision_data = json.loads(response_str)
        decision = decision_data.get("decision", "CONTINUE").upper()
        logging.debug(f"[{case_name}] Reflection decision: {decision}")

        result = {"reflection_history": [decision_data]}
        if decision == "REPLAN" and decision_data.get("new_plan"):
            result["is_replan"] = True
            result["replanned_cases"] = decision_data["new_plan"]
            logging.info(f"[{case_name}] REPLAN with {len(decision_data['new_plan'])} new cases")
        return result

    except json.JSONDecodeError as e:
        logging.error(f"[{case_name}] Failed to parse reflection response: {e}")
        return {"reflection_history": [{"decision": "CONTINUE", "reasoning": f"JSON error: {e}", "new_plan": []}]}
    except Exception as e:
        logging.error(f"[{case_name}] Reflection error: {e}")
        return {"reflection_history": [{"decision": "CONTINUE", "reasoning": str(e), "new_plan": []}]}



async def aggregate_results(state: MainGraphState) -> Dict[str, Dict[str, Any]]:
    """Aggregates the results from all test case workers."""
    logging.debug("Aggregating test results...")
    total_cases = len(state.get("test_cases", []))
    summary = {
        "total_cases": total_cases,
        "completed_summary": state["completed_cases"],
    }
    logging.debug(f"Final summary: {json.dumps(summary, indent=2)}")
    return {"final_report": summary}


async def cleanup_session(state: MainGraphState) -> Dict:
    """Cleanup hook for graph workflow completion.

    Closes any remaining browser sessions in the pool. Workers close their sessions
    directly when no more pending cases exist, or release back to pool for reuse
    when more cases are waiting. This node serves as a safety net for any sessions
    that weren't closed during normal execution.
    """
    logging.debug("Graph workflow cleanup node reached")

    # Close any remaining sessions in the pool (safety net)
    sp = state.get("session_pool")
    if sp:
        await sp.close_all()
        logging.info("Closed all remaining browser sessions in session pool")

    return {}


# Define the main graph
workflow = StateGraph(MainGraphState)

# Add nodes
workflow.add_node("plan_test_cases", plan_test_cases)
workflow.add_node("run_test_cases", run_test_cases)  # 新增：worker pool 节点
workflow.add_node("aggregate_results", aggregate_results)
workflow.add_node("cleanup_session", cleanup_session)

# Add edges - 简化的图结构
workflow.set_entry_point("plan_test_cases")
workflow.add_edge("plan_test_cases", "run_test_cases")  # 直接进入 worker pool
workflow.add_edge("run_test_cases", "aggregate_results")  # worker pool 完成后聚合结果
workflow.add_edge("aggregate_results", "cleanup_session")
workflow.add_edge("cleanup_session", END)

# Compile the graph
app = workflow.compile()
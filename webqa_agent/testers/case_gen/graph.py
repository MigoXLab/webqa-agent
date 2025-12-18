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

from webqa_agent.actions.action_handler import ActionHandler
from webqa_agent.crawler.deep_crawler import (DeepCrawler, ElementKey,
                                              ElementMap)
from webqa_agent.testers.case_gen.agents.execute_agent import agent_worker_node
from webqa_agent.testers.case_gen.prompts.planning_prompts import (
    get_element_filtering_system_prompt, get_element_filtering_user_prompt,
    get_planning_prompt, get_reflection_prompt)
from webqa_agent.testers.case_gen.state.schemas import MainGraphState
from webqa_agent.utils import Display
from webqa_agent.utils.log_icon import icon

from webqa_agent.testers.function_tester import UITester


_pending_case_queue: deque[dict] = deque()
_queue_lock = asyncio.Lock()
_completed_case_count = 0  # 全局已完成 case 计数


async def setup_session(state: MainGraphState) -> Dict[str, Any]:
    """Uses the provided UITester instance to start the browser session."""
    logging.debug("Setting up browser session...")
    return {"is_replan": False, "replan_count": 0}


async def plan_test_cases(state: MainGraphState) -> Dict[str, List[Dict[str, Any]]]:
    """Analyzes the initial page and generates test cases.

    If is_replan is True, it appends the replanned cases instead of generating
    new ones.
    """
    ui_tester = None
    s = None  # session
    sp = state.get("session_pool", None)
    llm_cfg = state.get("llm_config", None)
    is_replan = state.get("is_replan", False)
    business_objectives = state.get("business_objectives", "No specific business objectives provided.")
    language = state.get('language', 'zh-CN')

    # 重置完成计数（仅初始规划时）
    if not is_replan:
        global _completed_case_count
        _completed_case_count = 0

    if is_replan:
        logging.debug("Appending replanned test cases to the existing plan.")
        existing_cases = state.get("test_cases", [])
        new_cases = state.get("replanned_cases", [])
        replan_count = state.get("replan_count", 0) + 1
        logging.debug(f"Replan attempt #{replan_count}.")

        # Add metadata to new cases
        for case in new_cases:
            case["status"] = "pending"
            case["completed_steps"] = []
            case["test_context"] = {}
            case["url"] = state["url"]

        # Add new cases to pending queue
        async with _queue_lock:
            for c in new_cases:
                _pending_case_queue.append(c)

        current_index = state.get("current_test_case_index", 0)
        updated_cases = existing_cases[:current_index] + new_cases + existing_cases[current_index:]
        logging.debug(f"Inserted {len(new_cases)} new cases. Total: {len(updated_cases)}")

        # Save updated cases to cases.json
        try:
            timestamp = os.getenv("WEBQA_REPORT_TIMESTAMP")
            report_dir = f"./reports/test_{timestamp}"
            os.makedirs(report_dir, exist_ok=True)
            cases_path = os.path.join(report_dir, "cases.json")
            with open(cases_path, "w", encoding="utf-8") as f:
                json.dump(updated_cases, f, ensure_ascii=False, indent=4)
            logging.debug(f"Successfully saved updated test cases (including replanned cases) to {cases_path}")
        except Exception as e:
            logging.error(f"Failed to save updated test cases to file: {e}")

        # Reset the replan flag and clear the temporary list
        return {"test_cases": updated_cases, "is_replan": False, "replan_count": replan_count, "replanned_cases": []}

    # If not a replan, proceed with two-stage LLM-driven planning
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
            return {
                "test_cases": [],
                "is_replan": False,
                "replan_count": 0,
                "replanned_cases": []
            }
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
            temperature=0.3,
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
            temperature=0.1,
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

            # Initialize queue with test cases
            async with _queue_lock:
                _pending_case_queue.clear()
                for c in test_cases:
                    _pending_case_queue.append(c)

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
            # Ensure the current_test_case_index is initialized if not present
            if "current_test_case_index" not in state:
                return {"test_cases": test_cases, "current_test_case_index": 0}
            return {"test_cases": test_cases}
        except (json.JSONDecodeError, IndexError, ValueError) as e:
            logging.error(f"Failed to parse test cases from LLM response: {e}\nResponse: {response}")
            return {"test_cases": []}
    finally:
        # Release session back to pool after planning is complete
        if s and sp:
            await sp.release(s)
            logging.debug(f"[plan_test_cases] Released session {s.session_id} back to pool")


async def should_start_cases(state: MainGraphState) -> List[Send]:
    """Determines if there are test cases to run.

    If so, it routes to a node that will start execution loop.
    """
    if state.get('generate_only'):
        logging.debug("'generate_only' is True, ending process after planning.")
        return [Send("cleanup_session", {})]
    if state.get("test_cases"):
        logging.debug("Test cases found, starting execution.")
        return await schedule_next_batch(state)
    else:
        logging.debug("No test cases generated, finishing up.")
        return [Send("cleanup_session", {})]


async def schedule_next_batch(state: MainGraphState) -> List[Send]:
    """
    Schedule next batch of test cases for parallel execution.
    Returns multiple Send objects - LangGraph will execute them in parallel.
    """
    sp = state["session_pool"]

    # get next batch of test cases
    async with _queue_lock:
        batch_size = min(sp.pool_size, len(_pending_case_queue))
        if batch_size <= 0:
            logging.debug("No more test cases to run.")
            return []
        case_batch = [_pending_case_queue.popleft() for _ in range(batch_size)]
        logging.debug(f"Scheduling {len(case_batch)} cases for parallel execution, {len(_pending_case_queue)} remaining")

    # Create multiple Sends - LangGraph will execute them in parallel
    sends = []
    for case in case_batch:
        logging.info(f"[Parallel] Creating Send for case: {case.get('name', 'UNNAMED')}")
        send_data = {
            "current_case": case,
            "session_pool": sp,
            "llm_config": state.get("llm_config"),
            "language": state.get("language", "zh-CN"),
            "url": state.get("url"),
            "cookies": state.get("cookies"),
            "test_cases": state.get("test_cases", []),
            "completed_cases": state.get("completed_cases", []),
            "dynamic_step_generation": state.get("dynamic_step_generation", {
                "enabled": False,
                "max_dynamic_steps": 0,
                "min_elements_threshold": 2
            }),
            "case_ui_testers": {},
        }
        sends.append(Send("execute_single_case", send_data))

    return sends


async def execute_single_case(state: MainGraphState) -> dict:
    """Executes a single test case using the agent worker node.
    Each case gets its own session from the pool, executes independently, and releases the session back when done.
    """
    case = state["current_case"]
    case_name = case.get("name")
    s = None
    sp = state["session_pool"]
    failed = False

    try:
        s = await sp.acquire(timeout=120.0)
        await s.navigate_to(state["url"], cookies=state.get("cookies", {}))

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
            logging.debug(f"Executing functional test: {case_name}")

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

            # add timeout
            try:
                result = await  asyncio.wait_for(
                    agent_worker_node(worker_input_state, config={"configurable": {"ui_tester_instance": ui_tester}}),
                    timeout=1800
                )
                logging.debug(f"Case completed: {case_name}")
            except asyncio.TimeoutError:
                logging.error(f"Case '{case_name}' timed out (30 minutes)")
                failed = True
                return {
                    "completed_cases": None
                }

            # The result from the worker now contains the single case result
            case_result = result.get("case_result")
            modified_case = result.get("modified_case")
            recorded_case = result.get("recorded_case")  # recorded_case contains all step data

            # Handle case modification when dynamic steps were added
            if modified_case:
                logging.info(f"Test case '{case_name}' was modified with dynamic steps, updating test_cases and saving to case.json")
                try:
                    timestamp = os.getenv("WEBQA_REPORT_TIMESTAMP")
                    report_dir = f"./reports/test_{timestamp}"
                    os.makedirs(report_dir, exist_ok=True)
                    cases_path = os.path.join(report_dir, "cases.json")
                    with open(cases_path, "w", encoding="utf-8") as f:
                        json.dump(state.get("test_cases", []), f, ensure_ascii=False, indent=4)
                    logging.info(f"Successfully updated case.json with {modified_case.get('_dynamic_steps_count', 0)} dynamic steps")
                except Exception as e:
                    logging.error(f"Failed to save modified cases to case.json: {e}")

            # Check if this is a critical failure that should skip reflection
            if case_result and case_result.get("status") == "failed":
                failure_type = case_result.get("failure_type")
                case_name = case_result.get("case_name", "Unknown")

                if failure_type == "critical":
                    logging.warning(f"Critical failure detected in test case '{case_name}'. Skipping reflection and moving to next case.")
                    return_value = {"completed_cases": [case_result], "skip_reflection": True}
                else:
                    logging.info(f"Recoverable failure in test case '{case_name}'. Will proceed with reflection for potential replan.")
                    return_value = {"completed_cases": [case_result] if case_result else []}
            else:
                return_value = {"completed_cases": [case_result] if case_result else []}

            # Include updated test_cases if case was modified
            if modified_case:
                return_value["test_cases"] = state.get("test_cases", [])

            # Store recorded_case data from CentralCaseRecorder into graph state
            if recorded_case:
                return_value["recorded_cases"] = [recorded_case]

            # 执行反思（非 skip_reflection 时）
            if not return_value.get("skip_reflection"):
                reflect_result = await _do_reflection(ui_tester, state, case_name)
                return_value.update(reflect_result)

            return return_value

    except Exception as e:
        logging.error(f"execute_single_case 执行异常 for '{case_name}': {e}", exc_info=True)
        failed = True
        return {
            "completed_cases": [{
                "case_name": case_name,
                "status": "failed",
                "failure_type": "unexpected_error",
                "reason": f"Unexpected error: {str(e)}"
            }],
            "skip_reflection": True
        }

    finally:
        # 无论成功失败，执行+反思完成后立即释放 session
        if s:
            await sp.release(s, failed=failed)
            logging.debug(f"Case '{case_name}': released session (failed={failed})")
        # 增加全局完成计数
        global _completed_case_count
        _completed_case_count += 1


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


async def should_replan_or_continue(state: MainGraphState) -> List[Send]:
    """路由函数：检查是否还有待执行的 case。反思已在 execute_single_case 中完成。"""

    # 显示进度（使用全局计数）
    global _completed_case_count
    total_planned = len(state.get("test_cases", []))
    logging.info(f"{icon['hourglass']} Progress: {_completed_case_count}/{total_planned} cases completed")

    # 检查是否还有待执行的 case
    async with _queue_lock:
        has_pending = len(_pending_case_queue) > 0

    if has_pending:
        logging.debug(f"Still have pending cases, scheduling next batch")
        return await schedule_next_batch(state)
    else:
        logging.debug(f"No more pending cases, aggregating results")
        return [Send("aggregate_results", {
            "test_cases": state.get("test_cases", []),
            "completed_cases": state.get("completed_cases", [])
        })]



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
    
    Note: Browser session cleanup is handled by test_runners.py to collect
    monitoring data. This node serves as a graph completion marker.
    """
    logging.debug("Graph workflow cleanup node reached")
    async with _queue_lock:
        _pending_case_queue.clear()
    return {}


# Define the main graph
workflow = StateGraph(MainGraphState)

# Add nodes
workflow.add_node("setup_session", setup_session)
workflow.add_node("plan_test_cases", plan_test_cases)
workflow.add_node("execute_single_case", execute_single_case)
workflow.add_node("aggregate_results", aggregate_results)
workflow.add_node("cleanup_session", cleanup_session)

# Add edges
workflow.set_entry_point("setup_session")
workflow.add_edge("setup_session", "plan_test_cases")

workflow.add_conditional_edges(
    "plan_test_cases",
    should_start_cases,
)

# execute_single_case 内部完成反思，直接路由到下一步
workflow.add_conditional_edges(
    "execute_single_case",
    should_replan_or_continue,
)

# After execution, the results are aggregated.
workflow.add_edge("aggregate_results", "cleanup_session")
workflow.add_edge("cleanup_session", END)

# Compile the graph
app = workflow.compile()
"""This module defines the main graph for the LangGraph-based UI testing
application.

It includes the definitions for all nodes and edges in the orchestrator graph.
"""

import datetime
import json
import logging
import os
import re
from typing import Any, Dict, List

from langgraph.graph import END, StateGraph

from webqa_agent.actions.action_handler import ActionHandler
from webqa_agent.crawler.deep_crawler import DeepCrawler
from webqa_agent.testers.langgraph.agents.execute_agent import agent_worker_node
from webqa_agent.testers.langgraph.prompts.planning_prompts import get_reflection_prompt, get_test_case_planning_system_prompt, get_test_case_planning_user_prompt
from webqa_agent.testers.langgraph.state.schemas import MainGraphState


async def setup_session(state: MainGraphState) -> Dict[str, Any]:
    """Uses the provided UITester instance to start the browser session."""
    logging.debug("Setting up browser session...")
    ui_tester = state["ui_tester_instance"]
    await ui_tester.start_session(state["url"])
    page = await ui_tester.get_current_page()
    action_handler = ActionHandler()
    await action_handler.go_to_page(page, state["url"], cookies=state["cookies"])
    # Initialize the loop counter and replan flag
    return {"current_test_case_index": 0, "is_replan": False, "replan_count": 0}


async def plan_test_cases(state: MainGraphState) -> Dict[str, List[Dict[str, Any]]]:
    """Analyzes the initial page and generates test cases.

    If is_replan is True, it appends the replanned cases instead of generating
    new ones.
    """
    is_replan = state.get("is_replan", False)

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

        # Insert the new cases immediately after the current index
        current_index = state["current_test_case_index"]
        updated_cases = existing_cases[:current_index] + new_cases + existing_cases[current_index:]

        logging.debug(
            f"Inserted {len(new_cases)} new cases at index {current_index}. Total cases are now {len(updated_cases)}."
        )

        # Save updated cases to cases.json
        try:
            timestamp = os.getenv("WEBQA_TIMESTAMP")
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

    # If not a replan, proceed with the original logic
    logging.debug("Generating initial test plan.")
    ui_tester = state["ui_tester_instance"]

    page = await ui_tester.get_current_page()
    dp = DeepCrawler(page)
    _, page_content_summary = await dp.crawl(highlight=True, viewport_only=True)
    screenshot = await ui_tester._actions.b64_page_screenshot(
        file_name="plan_or_replan", save_to_log=False, full_page=False
    )
    await dp.remove_marker()
    await dp.crawl(highlight=False, highlight_text=True, viewport_only=True)
    page_structure = dp.get_text()
    logging.debug(f"----- plan cases ---- Page structure: {page_structure}")

    business_objectives = state.get("business_objectives", "No specific business objectives provided.")
    completed_cases = state.get("completed_cases")

    system_prompt = get_test_case_planning_system_prompt(
        business_objectives=business_objectives,
        completed_cases=completed_cases,
        reflection_history=state.get("reflection_history"),
        remaining_objectives=state.get("remaining_objectives"),
    )
    
    user_prompt = get_test_case_planning_user_prompt(
        state_url=state["url"],
        page_content_summary=page_content_summary,
        page_structure=page_structure,
        completed_cases=completed_cases,
        reflection_history=state.get("reflection_history"),
        remaining_objectives=state.get("remaining_objectives"),
    )

    logging.debug("Generating initial test plan - Sending request to LLM...")
    start_time = datetime.datetime.now()

    response = await ui_tester.llm.get_llm_response(
        system_prompt=system_prompt, prompt=user_prompt, images=screenshot, temperature=0.1
    )

    end_time = datetime.datetime.now()
    duration = (end_time - start_time).total_seconds()
    logging.debug(f"LLM planning request completed in {duration:.2f} seconds")

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
            timestamp = os.getenv("WEBQA_TIMESTAMP")
            report_dir = f"./reports/test_{timestamp}"
            os.makedirs(report_dir, exist_ok=True)
            cases_path = os.path.join(report_dir, "cases.json")
            with open(cases_path, "w", encoding="utf-8") as f:
                json.dump(test_cases, f, ensure_ascii=False, indent=4)
            logging.debug(f"Successfully saved initial test cases to {cases_path}")
        except Exception as e:
            logging.error(f"Failed to save initial test cases to file: {e}")

        logging.debug(f"Generated {len(test_cases)} test cases.")
        # Ensure the current_test_case_index is initialized if not present
        if "current_test_case_index" not in state:
            return {"test_cases": test_cases, "current_test_case_index": 0}
        return {"test_cases": test_cases}
    except (json.JSONDecodeError, IndexError, ValueError) as e:
        logging.error(f"Failed to parse test cases from LLM response: {e}\nResponse: {response}")
        return {"test_cases": []}


def should_start_cases(state: MainGraphState) -> str:
    """Determines if there are test cases to run.

    If so, it routes to a node that will start the sequential execution loop.
    """
    if state.get("generate_only"):
        logging.debug("'generate_only' is True, ending process after planning.")
        return "end"
    if state.get("test_cases"):
        logging.debug("Test cases found, starting sequential execution loop.")
        return "get_next_test_case"
    else:
        logging.debug("No test cases generated, finishing up.")
        return "end"


async def get_next_test_case(state: MainGraphState) -> dict[str, Any]:
    """Selects the next test case from the list based on the current index."""
    index = state["current_test_case_index"]
    case = state["test_cases"][index]
    case_name = case.get("name")
    logging.debug(f"Preparing to execute test case #{index + 1}: {case_name}")

    return {"current_case": case}


async def reflect_and_replan(state: MainGraphState) -> dict:
    """Analyzes execution, increments index, and decides on the next strategic
    move."""
    logging.debug("=== Starting Reflection and Replanning Analysis ===")

    # CRITICAL: Increment the test case index here to ensure progress
    # This guarantees that whether we continue, replan, or finish, we are always moving forward.
    new_index = state["current_test_case_index"] + 1
    logging.debug(
        f"Test case #{state['current_test_case_index'] + 1} has been processed. Incrementing index to {new_index}."
    )
    update = {"current_test_case_index": new_index}

    # FUSE MECHANISM: Check if the replan limit has been reached.
    MAX_REPLANS = 2
    if state.get("replan_count", 0) >= MAX_REPLANS:
        logging.warning(f"Maximum replan limit of {MAX_REPLANS} reached. Forcing FINISH to avoid infinite loops.")
        update["reflection_history"] = [
            {
                "decision": "FINISH",
                "reasoning": f"Maximum replan limit of {MAX_REPLANS} reached. The agent was unable to resolve the issue after multiple replanning attempts. Terminating workflow to prevent infinite loops.",
                "new_plan": [],
            }
        ]
        return update

    # 详细的状态分析
    completed_cases = state.get("completed_cases", [])
    test_cases = state.get("test_cases", [])

    logging.debug("State Analysis:")
    logging.debug(f"  - Total planned test cases: {len(test_cases)}")
    logging.debug(f"  - Completed test cases: {len(completed_cases)}")
    # Use the length of completed_cases for a more accurate progress count
    logging.debug(f"  - Current progress: {len(completed_cases)} / {len(test_cases)} cases completed.")

    # 分析最后完成的测试用例
    if completed_cases:
        last_case = completed_cases[-1]
        logging.debug(f"  - Last completed case: {last_case.get('case_name', 'Unknown')}")
        logging.debug(f"  - Last case status: {last_case.get('status', 'Unknown')}")
    else:
        logging.debug("  - No completed cases yet")

    # 分析进度情况
    if len(completed_cases) < len(test_cases):
        remaining_cases = len(test_cases) - len(completed_cases)
        logging.debug(f"  - Remaining test cases to execute: {remaining_cases}")
        # The next case is determined by the number of completed cases, not the old index
        next_case_index = len(completed_cases)
        if next_case_index < len(test_cases):
            next_case = test_cases[next_case_index]
            logging.debug(f"  - Next planned case: {next_case.get('name', 'Unknown')}")
    else:
        logging.debug("  - All planned test cases appear to be completed")

    ui_tester = state["ui_tester_instance"]

    # Get current UI state for analysis with enhanced visual information
    page = await ui_tester.get_current_page()

    # Use DeepCrawler to get interactive elements mapping and highlighted screenshot
    logging.debug("Using DeepCrawler to obtain visual element mapping for reflection analysis")
    dp = DeepCrawler(page)
    _, page_content_summary = await dp.crawl(highlight=True, viewport_only=True)
    screenshot = await ui_tester._actions.b64_page_screenshot(file_name="reflection", save_to_log=False, full_page=False)
    await dp.remove_marker()
    await dp.crawl(highlight=False, highlight_text=True, viewport_only=True)
    page_structure = dp.get_text()
    logging.debug(f"----- reflection ---- Page structure: {page_structure}")

    logging.debug(f"Reflection analysis enhanced with {len(page_content_summary)} interactive elements")

    # 使用新的反思提示词函数，传入page_content_summary
    system_prompt, user_prompt = get_reflection_prompt(
        business_objectives=state.get("business_objectives"),
        current_plan=state["test_cases"],
        completed_cases=state["completed_cases"],
        page_structure=page_structure,
        page_content_summary=page_content_summary,
    )

    logging.debug("Sending reflection request to LLM (this may take a moment)...")
    start_time = datetime.datetime.now()

    response_str = await ui_tester.llm.get_llm_response(
        system_prompt=system_prompt, prompt=user_prompt, images=screenshot, temperature=0.1
    )

    end_time = datetime.datetime.now()
    duration = (end_time - start_time).total_seconds()
    logging.debug(f"LLM reflection request completed in {duration:.2f} seconds")
    logging.debug(f"Raw LLM response length: {len(response_str)} characters")
    logging.debug(f"Raw LLM response preview: {response_str[:500]}...")

    try:
        decision_data = json.loads(response_str)
        decision = decision_data.get("decision", "CONTINUE").upper()
        reasoning = decision_data.get("reasoning", "No reasoning provided")
        new_plan = decision_data.get("new_plan")

        logging.debug(f"Parsed reflection decision: {decision}")
        logging.debug(f"Decision reasoning: {reasoning}")

        update["reflection_history"] = [decision_data]

        if decision == "REPLAN" and new_plan:
            logging.debug(f"REPLAN decision confirmed. New plan has {len(new_plan)} cases.")
            logging.debug("Setting is_replan flag and storing new cases. The plan will be updated in the next cycle.")
            # Set the replan flag and store the new cases. Do NOT modify the main list here.
            update["is_replan"] = True
            update["replanned_cases"] = new_plan

            for i, case in enumerate(new_plan):
                logging.debug(f"  New case {i + 1}: {case.get('name', 'Unnamed')}")
        else:
            if decision == "REPLAN":
                logging.warning("REPLAN decision made but no new_plan provided. Treating as CONTINUE.")
                # 修正决策数据
                update["reflection_history"] = [
                    {
                        "decision": "CONTINUE",
                        "reasoning": "REPLAN was requested but no new plan was provided, defaulting to CONTINUE",
                        "new_plan": [],
                    }
                ]

        logging.debug("=== Reflection Analysis Complete ===")
        return update

    except json.JSONDecodeError as e:
        logging.error(f"Failed to decode JSON from reflection LLM: {e}")
        logging.error(f"Full response: {response_str}")
        # Default to continuing if reflection fails
        fallback_decision = {
            "decision": "CONTINUE",
            "reasoning": f"Failed to parse LLM response due to JSON decode error: {str(e)}",
            "new_plan": [],
        }
        logging.debug("Using fallback decision: CONTINUE")
        update["reflection_history"] = [fallback_decision]
        return update


async def execute_single_case(state: MainGraphState) -> dict:
    """Executes a single test case using the agent worker node.

    This node is the core of the execution loop.
    """
    case = state["current_case"]
    ui_tester_instance = state["ui_tester_instance"]
    case_name = case.get("name")

    # === 开始跟踪case数据 ===
    # 使用start_case来同时设置名称和开始数据跟踪
    ui_tester_instance.start_case(case_name, case)

    # Conditionally reset the session based on the test case flag
    if case.get("reset_session", False):
        logging.debug(f"Resetting session: navigation to {case.get('url')}.")
        await ui_tester_instance.start_session(case.get("url"))
        page = await ui_tester_instance.get_current_page()
        action_handler = ActionHandler()
        await action_handler.go_to_page(page, state["url"], cookies=state["cookies"])
        logging.debug("Navigation was performed as part of session reset.")
    else:
        await ui_tester_instance.start_session(case.get("url"))
        page = await ui_tester_instance.get_current_page()
        action_handler = ActionHandler()
        await action_handler.go_to_page(page, state["url"], cookies=state["cookies"])
        logging.debug("Continuing with the existing session state.")

    # Invoke the agent worker for the single case
    # Pass the current completed cases to the worker so it can append
    worker_input_state = {"test_case": case, "completed_cases": state.get("completed_cases", [])}
    result = await agent_worker_node(
        worker_input_state, config={"configurable": {"ui_tester_instance": ui_tester_instance}}
    )

    # The result from the worker now contains the single case result
    case_result = result.get("case_result")

    # === 结束case跟踪并获取详细数据 ===
    final_status = case_result.get("status", "completed") if case_result else "failed"
    final_summary = case_result.get("final_summary", "") if case_result else "No summary available"

    ui_tester_instance.finish_case(final_status, final_summary)

    # Return the single result in a list to be appended by the graph state
    return {"completed_cases": [case_result] if case_result else []}


def should_replan_or_continue(state: MainGraphState) -> str:
    """Checks the latest reflection decision to route the graph.

    Enhanced with detailed state checking and logging.
    """
    # 获取状态信息
    completed_count = len(state.get("completed_cases", []))
    total_planned = len(state.get("test_cases", []))
    current_index = state.get("current_test_case_index", 0)

    # 详细的状态日志
    logging.debug("=== Decision Context Analysis ===")
    logging.debug(f"Completed cases count: {completed_count}")
    logging.debug(f"Total planned cases: {total_planned}")
    logging.debug(f"Current test case index (for loop control): {current_index}")

    # The primary condition for finishing should be the reflection decision itself.
    reflection_history = state.get("reflection_history", [])
    if not reflection_history:
        logging.warning("No reflection history found, defaulting to CONTINUE")
        # Fallback to simple index check if reflection fails
        if current_index >= total_planned:
            return "aggregate_results"
        else:
            return "get_next_test_case"

    last_reflection = reflection_history[-1]
    decision = last_reflection.get("decision", "CONTINUE").upper()
    reasoning = last_reflection.get("reasoning", "No reasoning provided")

    # 详细的决策日志
    logging.debug(f"Reflection decision: {decision}")
    logging.debug(f"Reflection reasoning: {reasoning}")

    if decision == "FINISH":
        logging.debug("Reflection resulted in FINISH. Aggregating results.")
        return "aggregate_results"

    if decision == "REPLAN":
        logging.debug("Reflection resulted in REPLAN. Routing back to the planner to append new cases.")
        return "plan_test_cases"

    # For 'CONTINUE' decision, we check if we've run out of cases.
    # This is the main safeguard against loops.
    # NOTE: The index was already incremented inside reflect_and_replan
    if state["current_test_case_index"] >= total_planned:
        logging.debug("All planned test cases have been completed. Aggregating results.")
        return "aggregate_results"

    # If we are here, it means decision is CONTINUE and there are more cases to run.
    logging.debug("Reflection resulted in CONTINUE. Moving to the next test case.")
    return "get_next_test_case"


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
    """Closes the browser session."""
    logging.debug("Cleaning up browser session...")
    ui_tester = state["ui_tester_instance"]
    if ui_tester:
        browser_results = await ui_tester.end_session()
    return browser_results


# Define the main graph
workflow = StateGraph(MainGraphState)

# Add nodes
workflow.add_node("setup_session", setup_session)
workflow.add_node("plan_test_cases", plan_test_cases)
workflow.add_node("get_next_test_case", get_next_test_case)
workflow.add_node("execute_single_case", execute_single_case)
workflow.add_node("reflect_and_replan", reflect_and_replan)

workflow.add_node("aggregate_results", aggregate_results)
workflow.add_node("cleanup_session", cleanup_session)

# Add edges
workflow.set_entry_point("setup_session")
workflow.add_edge("setup_session", "plan_test_cases")

workflow.add_conditional_edges(
    "plan_test_cases",
    should_start_cases,
    {
        "get_next_test_case": "get_next_test_case",
        "end": "cleanup_session",
    },
)

# Execution loop
workflow.add_edge("get_next_test_case", "execute_single_case")
workflow.add_edge("execute_single_case", "reflect_and_replan")

workflow.add_conditional_edges(
    "reflect_and_replan",
    should_replan_or_continue,
    {
        "get_next_test_case": "get_next_test_case",
        "plan_test_cases": "plan_test_cases",
        "aggregate_results": "aggregate_results",
    },
)

# After sequential execution, the results are aggregated.
workflow.add_edge("aggregate_results", "cleanup_session")
workflow.add_edge("cleanup_session", END)

# Compile the graph
app = workflow.compile()

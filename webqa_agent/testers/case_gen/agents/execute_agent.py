"""This module defines the agent worker node for the LangGraph-based UI testing
application.

The agent worker is responsible for executing a single test case.
"""

import datetime
import logging
import re

from langchain.agents import AgentExecutor, create_tool_calling_agent
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage
from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder
from langchain_openai import ChatOpenAI

from webqa_agent.crawler.deep_crawler import DeepCrawler
from webqa_agent.testers.case_gen.prompts.agent_prompts import get_execute_system_prompt
from webqa_agent.testers.case_gen.tools.element_action_tool import UIAssertTool, UITool
from webqa_agent.testers.case_gen.utils.message_converter import convert_intermediate_steps_to_messages
from webqa_agent.utils.log_icon import icon

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

    # Instantiate the custom tool with the ui_tester_instance
    tools = [
        UITool(ui_tester_instance=ui_tester_instance),
        UIAssertTool(ui_tester_instance=ui_tester_instance),
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

                if "[failure]" in tool_output.lower():
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
    total_steps = len(case.get("steps", []))
    failed_steps = []  # Track failed steps for summary generation

    for i, step in enumerate(case.get("steps", [])):
        instruction_to_execute = step.get("action") or step.get("verify")
        step_type = "Action" if step.get("action") else "Assertion"

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
        step_message = HumanMessage(
            content=[
                {"type": "text", "text": formatted_instruction},
                {
                    "type": "image_url",
                    "image_url": {"url": f"{screenshot}", "detail": "low"},
                },
            ]
        )

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

            # Check for failures in the tool output
            if "[failure]" in tool_output.lower() or "failed" in tool_output.lower():
                failed_steps.append(i + 1)
                logging.warning(f"Step {i+1} detected as failed based on output")

            # Check for max iterations, which indicates a failure to complete the step.
            if "Agent stopped due to max iterations." in tool_output:
                failed_steps.append(i + 1)
                final_summary = f"FINAL_SUMMARY: Step '{instruction_to_execute}' failed after multiple retries. The agent could not complete the instruction. Last output: {tool_output}"
                logging.error(f"Step {i+1} failed due to max iterations.")
                break

            logging.debug(f"Step {i+1} completed {'successfully' if (i+1) not in failed_steps else 'with issues'}.")

        except Exception as e:
            logging.error(f"Exception during step {i+1} execution: {str(e)}")
            failed_steps.append(i + 1)
            final_summary = f"FINAL_SUMMARY: Step '{instruction_to_execute}' raised an exception: {str(e)}"
            break

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

    logging.debug(f"Test case '{case_name}' final status: {status} (success indicators: {has_success}, failure indicators: {has_failure})")

    case_result = {
        "case_name": case_name,
        "final_summary": final_summary,
        "status": status,
    }

    logging.debug(f"=== Agent Worker Completed for {case_name}. ===")

    # Return only the result of the current case
    return {"case_result": case_result}


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
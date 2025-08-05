"""
This module defines the agent worker node for the LangGraph-based UI testing application.
The agent worker is responsible for executing a single test case.
"""
from webqa_agent.testers.langgraph.tools.element_action_tool import UITool, UIAssertTool
from webqa_agent.testers.langgraph.prompts.agent_prompts import get_execute_system_prompt
from langchain_core.messages import BaseMessage, HumanMessage, AIMessage
from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder
from langchain_openai import ChatOpenAI
from langchain.agents import AgentExecutor, create_tool_calling_agent
import logging
import re
import datetime
from webqa_agent.crawler.deep_crawler import DeepCrawler


# The node function that will be used in the graph
async def agent_worker_node(state: dict, config: dict) -> dict:
    """
    Dynamically creates and invokes the execution agent for a single test case.
    This node is mapped over the list of test cases.
    """
    case = state["test_case"]
    case_name = case.get("name", "Unnamed Test Case")
    completed_cases = state.get("completed_cases", [])

    logging.info(f"=== Starting Agent Worker for Test Case: {case_name} ===")
    logging.info(f"Test case objective: {case.get('objective', 'Not specified')}")
    logging.info(f"Test case steps count: {len(case.get('steps', []))}")
    logging.info(f"Preamble actions count: {len(case.get('preamble_actions', []))}")
    logging.info(f"Previously completed cases: {len(completed_cases)}")
    
    ui_tester_instance = config['configurable']['ui_tester_instance']
    
    # Note: case tracking is managed by execute_single_case node via start_case/finish_case
    # No need to set test name here as it's already handled

    system_prompt_string = get_execute_system_prompt(case)
    logging.debug(f"Generated system prompt length: {len(system_prompt_string)} characters")

    llm_config = ui_tester_instance.llm.llm_config

    # Use ChatOpenAI directly for better integration with LangChain
    llm = ChatOpenAI(
        model=llm_config.get("model", "gpt-4o-mini"),
        api_key=llm_config.get("api_key"),
        base_url=llm_config.get("base_url"),
        temperature=0.0
    )
    logging.info(f"LLM configured: {llm_config.get('model')} at {llm_config.get('base_url')}")

    # Instantiate the custom tool with the ui_tester_instance
    tools = [
        UITool(ui_tester_instance=ui_tester_instance),
        UIAssertTool(ui_tester_instance=ui_tester_instance),
    ]
    logging.info(f"Tools initialized: {[tool.name for tool in tools]}")

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
    agent_executor = AgentExecutor(agent=agent, tools=tools, verbose=True, max_iterations=2)
    logging.info("AgentExecutor created successfully")

    # --- Execute Preamble Actions to Restore State ---
    preamble_actions = case.get("preamble_actions", [])
    if preamble_actions:
        logging.info(f"=== Executing {len(preamble_actions)} Preamble Actions ===")
        preamble_messages: list[BaseMessage] = [HumanMessage(content="The test has started. Before the main test steps, I need to perform some setup actions to restore the UI state. Please execute the first preamble action.")]
        
        for i, step in enumerate(preamble_actions):
            if isinstance(step, dict):
                instruction_to_execute = step.get('action')
            else:
                instruction_to_execute = step
            if not instruction_to_execute:
                logging.warning(f"Preamble action {i+1} has no instruction, skipping")
                continue

            # 智能检查：如果preamble action是导航指令且已经在目标页面，则跳过
            if case.get("reset_session", False) and _is_navigation_instruction(instruction_to_execute):
                # 检查是否已经在目标页面
                try:
                    page = ui_tester_instance.driver.get_page()
                    current_url = page.url
                    target_url = case.get('url', '')
                    
                    def normalize_url(u):
                        from urllib.parse import urlparse
                        try:
                            parsed = urlparse(u)
                            # 处理域名变体：移除www前缀，统一小写
                            netloc = parsed.netloc.lower()
                            if netloc.startswith('www.'):
                                netloc = netloc[4:]  # 移除www.
                            
                            # 标准化路径：去除尾部斜杠
                            path = parsed.path.rstrip('/')
                            
                            # 构建标准化URL
                            normalized = f"{parsed.scheme}://{netloc}{path}"
                            return normalized
                        except Exception:
                            # 如果解析失败，返回原URL的小写形式
                            return u.lower()
                    
                    # 更灵活的URL匹配
                    def extract_domain(u):
                        try:
                            from urllib.parse import urlparse
                            parsed = urlparse(u)
                            domain = parsed.netloc.lower()
                            if domain.startswith('www.'):
                                domain = domain[4:]
                            return domain
                        except Exception:
                            return ""
                    
                    def extract_path(u):
                        try:
                            from urllib.parse import urlparse
                            parsed = urlparse(u)
                            return parsed.path.rstrip('/')
                        except Exception:
                            return ""
                    
                    current_normalized = normalize_url(current_url)
                    target_normalized = normalize_url(target_url)
                    
                    # 基础标准化匹配
                    if current_normalized == target_normalized:
                        logging.info(f"Skipping preamble navigation action - already on target page (normalized match)")
                        continue
                    
                    # 更灵活的域名路径匹配
                    current_domain = extract_domain(current_url)
                    target_domain = extract_domain(target_url)
                    current_path = extract_path(current_url)
                    target_path = extract_path(target_url)
                    
                    if (current_domain == target_domain and 
                        (current_path == target_path or 
                         current_path == "" and target_path == "" or
                         current_path == "/" and target_path == "" or
                         current_path == "" and target_path == "/")):
                        logging.info(f"Skipping preamble navigation action - domain and path match detected ({current_domain}{current_path})")
                        continue
                        
                except Exception as e:
                    logging.warning(f"Could not check current URL for preamble action: {e}, proceeding with execution")

            logging.info(f"Executing preamble action {i+1}/{len(preamble_actions)}: {instruction_to_execute}")
            preamble_messages.append(HumanMessage(content=f"Now, execute this preamble action: {instruction_to_execute}"))
            
            try:
                # Use a simple invoke, as preamble steps should be straightforward
                logging.info(f"Executing preamble action {i+1} - Calling Agent...")
                start_time = datetime.datetime.now()
                
                result = await agent_executor.ainvoke({"messages": preamble_messages})
                preamble_messages = result.get("messages", [])
                
                end_time = datetime.datetime.now()
                duration = (end_time - start_time).total_seconds()
                
                tool_output = result.get("output", "")
                logging.info(f"Preamble action {i+1} completed in {duration:.2f} seconds")
                logging.debug(f"Preamble action {i+1} result: {tool_output[:200]}...")
                preamble_messages.append(AIMessage(content=tool_output))

                if "[failure]" in tool_output.lower():
                    final_summary = f"FINAL_SUMMARY: Preamble action '{instruction_to_execute}' failed, cannot proceed with the test case. Error: {tool_output}"
                    case_result = { "case_name": case_name, "final_summary": final_summary, "status": "failed" }
                    logging.error(f"Preamble action {i+1} failed, aborting test case")
                    return {"case_result": case_result, "current_case_steps": []}
                    
                logging.info(f"Preamble action {i+1} completed successfully")
            except Exception as e:
                logging.error(f"Exception during preamble action {i+1}: {str(e)}")
                final_summary = f"FINAL_SUMMARY: Preamble action '{instruction_to_execute}' raised exception: {str(e)}"
                case_result = { "case_name": case_name, "final_summary": final_summary, "status": "failed" }
                return {"case_result": case_result, "current_case_steps": []}
        
        logging.info("=== All Preamble Actions Completed Successfully ===")

    # --- Main Execution Loop ---
    logging.info("=== Starting Main Test Steps Execution ===")
    messages: list[BaseMessage] = [HumanMessage(content="The test has started. I will provide you with one instruction at a time. Please execute the action or assertion described in each instruction.")]
    final_summary = "No summary provided."
    total_steps = len(case.get("steps", []))

    for i, step in enumerate(case.get("steps", [])):
        instruction_to_execute = step.get('action') or step.get('verify')
        step_type = "Action" if step.get('action') else "Assertion"
        
        logging.info(f"=== Executing Step {i+1}/{total_steps} ({step_type}) ===")
        logging.info(f"Step instruction: {instruction_to_execute}")

        # Define instruction templates for variation
        instruction_templates = [
            "Now, execute this instruction: {instruction}",
            "Please proceed with the following step: {instruction}",
            "The next task is to perform this action: {instruction}",
            "Execute the instruction as follows: {instruction}"
        ]
        # Vary the instruction prompt to avoid repetitive context
        prompt_template = instruction_templates[i % len(instruction_templates)]
        formatted_instruction = prompt_template.format(instruction=instruction_to_execute)

        # --- Multi-Modal Context Generation ---
        page = ui_tester_instance.driver.get_page()
        dp = DeepCrawler(page)
        await dp.crawl(highlight=True, viewport_only=True)
        screenshot = await ui_tester_instance._actions.b64_page_screenshot(file_name="agent_step_vision", save_to_log=False)
        await dp.remove_marker()
        logging.info("Generated highlighted screenshot for the agent.")
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
                text_content = next((item['text'] for item in msg.content if item['type'] == 'text'), '')
                pruned_messages.append(HumanMessage(content=text_content))
            else:
                # It's an AI message, a simple HumanMessage, or the last message; keep as is.
                pruned_messages.append(msg)
        logging.debug(f"Pruned message history for token optimization. Original length: {len(current_messages)}, Pruned length: {len(pruned_messages)}")
        # ---------------------------------------------

        # --- Tool Choice Masking ---
        tool_choice = None
        if step_type == "Action":
            tool_choice = {"type": "function", "function": {"name": "execute_ui_action"}}
            logging.info("Forcing tool choice: execute_ui_action")
        elif step_type == "Assertion":
            tool_choice = {"type": "function", "function": {"name": "execute_ui_assertion"}}
            logging.info("Forcing tool choice: execute_ui_assertion")
        # -------------------------

        try:
            # The agent's history includes all prior messages
            logging.info(f"Step {i+1} - Calling Agent to execute {step_type}...")
            start_time = datetime.datetime.now()
            
            result = await agent_executor.ainvoke(
                {"messages": pruned_messages},
                config={"configurable": {"tool_choice": tool_choice}} if tool_choice else {}
            )
            
            end_time = datetime.datetime.now()
            duration = (end_time - start_time).total_seconds()
            
            messages = result.get("messages", [])
            tool_output = result.get("output", "")
            
            logging.info(f"Step {i+1} {step_type} completed in {duration:.2f} seconds")
            logging.debug(f"Step {i+1} tool output: {tool_output}")
            messages.append(AIMessage(content=tool_output))

            # Check for max iterations, which indicates a failure to complete the step.
            if "Agent stopped due to max iterations." in tool_output:
                final_summary = f"FINAL_SUMMARY: Step '{instruction_to_execute}' failed after multiple retries. The agent could not complete the instruction. Last output: {tool_output}"
                logging.error(f"Step {i+1} failed due to max iterations.")
                break

            logging.info(f"Step {i+1} completed successfully.")

        except Exception as e:
            logging.error(f"Exception during step {i+1} execution: {str(e)}")
            final_summary = f"FINAL_SUMMARY: Step '{instruction_to_execute}' raised an exception: {str(e)}"
            break

    # If the loop finishes without an early exit, get a final summary
    if "FINAL_SUMMARY:" not in final_summary:
        logging.debug("All test steps completed, requesting final summary")
        messages.append(HumanMessage(content="All planned steps have been executed. Please provide a final summary of the test case execution, assessing whether the overall objective was met based on the results."))
        try:
            summary_result = await agent_executor.ainvoke({"messages": messages})
            final_summary = summary_result.get("output", "Completed all steps, but no summary was generated.")
            logging.debug(f"Final summary received: {final_summary}")
        except Exception as e:
            logging.error(f"Exception during final summary generation: {str(e)}")
            final_summary = f"Completed all steps, but summary generation failed: {str(e)}"

    # Determine test case status
    status = "passed" if "success" in final_summary.lower() or "passed" in final_summary.lower() else "failed"
    logging.info(f"Test case '{case_name}' final status: {status}")

    case_result = {
        "case_name": case_name,
        "final_summary": final_summary,
        "status": status,
    }

    logging.info(f"=== Agent Worker Completed for {case_name}. ===")
    
    # Return only the result of the current case
    return {"case_result": case_result}


def _is_navigation_instruction(instruction: str) -> bool:
    """
    判断指令是否为导航指令
    
    Args:
        instruction: 要检查的指令文本
        
    Returns:
        bool: 如果是导航指令返回True，否则返回False
    """
    if not instruction:
        return False
        
    # 导航关键词列表
    navigation_keywords = [
        "navigate", "go to", "open", "visit", "browse", "load", 
        "导航", "打开", "访问", "跳转", "前往"
    ]
    
    # 将指令转换为小写进行匹配
    instruction_lower = instruction.lower()
    
    # 检查是否包含导航关键词
    for keyword in navigation_keywords:
        if keyword in instruction_lower:
            return True
    
    # 检查URL模式
    url_patterns = [
        r'https?://[^\s]+',
        r'www\.[^\s]+',
        r'\.com|\.org|\.net|\.edu|\.gov'
    ]
    
    for pattern in url_patterns:
        if re.search(pattern, instruction_lower):
            return True
    
    return False
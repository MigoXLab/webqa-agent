import json
import time
import asyncio
import logging
from typing import Optional, Dict, Any, Tuple, List
from datetime import datetime

from webqa_agent.browser.session import BrowserSession
from webqa_agent.actions.action_executor import ActionExecutor
from webqa_agent.actions.action_handler import ActionHandler
from webqa_agent.browser.check import NetworkCheck, ConsoleCheck
from webqa_agent.llm.llm_api import LLMAPI
from webqa_agent.llm.prompt import LLMPrompt
from webqa_agent.crawler.deep_crawler import DeepCrawler


class UITester:
    
    def __init__(self, llm_config: Dict[str, Any], browser_session: BrowserSession = None):
        self.llm_config = llm_config
        self.browser_session = browser_session
        self.page = None
        self.network_check = None
        self.console_check = None

        # Create component instances
        self._actions = ActionHandler()
        self._action_executor = ActionExecutor(self._actions)
        self.llm = LLMAPI(llm_config)

        # Execution status
        self.is_initialized = False
        self.test_results = []

        self.driver = None

        # Data storage related properties
        self.current_test_name: Optional[str] = None
        self.current_case_data: Optional[Dict[str, Any]] = None
        self.current_case_steps: List[Dict[str, Any]] = []
        self.all_cases_data: List[Dict[str, Any]] = []  # Store complete data for all cases
        self.step_counter: int = 0  # Used to generate step ID

    async def initialize(self, browser_session: BrowserSession = None):
        if browser_session:
            self.browser_session = browser_session

        if not self.browser_session:
            raise ValueError("Browser session is required")

        self.page = self.browser_session.get_page()
        self.driver = self.browser_session.driver

        await self._actions.initialize(page=self.page, driver=self.browser_session.driver)
        await self._action_executor.initialize()
        await self.llm.initialize()

        self.is_initialized = True
        return self

    async def start_session(self, url: str):
        if not self.is_initialized:
            raise RuntimeError("ParallelUITester not initialized")

        # # Simplify URL validation
        # if not url.startswith(("http://", "https://", "file://")):
        #     url = f"https://{url}"

        # Page navigation
        # await self._actions.go_to_page(self.page, url, cookies=cookies)
        await asyncio.sleep(2)  # Wait for page to load

        self.network_check = NetworkCheck(self.page)
        self.console_check = ConsoleCheck(self.page)




    async def action(self, test_step: str, file_path: str = None) -> Tuple[Dict[str, Any], Dict[str, Any]]:
        """
        执行AI驱动的测试指令并返回 (step_dict, summary_dict)

        Args:
            test_step: 测试步骤描述
            file_path: 文件路径（用于上传操作）

        Returns:
            Tuple (step_dict, summary_dict)
        """
        if not self.is_initialized:
            raise RuntimeError("ParallelUITester not initialized")

        start_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        
        try:
            logging.info(f"Executing AI instruction: {test_step}")

            # 爬取当前页面状态
            dp = DeepCrawler(self.page)
            _, id_map = await dp.crawl(highlight=True, viewport_only=True)
            await self._actions.update_element_buffer(id_map)

            # 步骤 2: 获取完整的页面文本结构
            await dp.crawl(highlight=False, highlight_text=True, viewport_only=True)
            page_structure = dp.get_text()

            # 截屏
            marker_screenshot = await self._actions.b64_page_screenshot(file_name="marker")

            # 移除标记
            await dp.remove_marker()

            # 准备LLM输入
            user_prompt = self._prepare_prompt(
                test_step,
                id_map,
                LLMPrompt.planner_output_prompt,
                page_structure
            )

            # 生成计划
            plan_json = await self._generate_plan(
                LLMPrompt.planner_system_prompt,
                user_prompt,
                marker_screenshot
            )

            logging.info(f"Generated plan: {plan_json}")

            # 执行计划
            execution_steps, execution_result = await self._execute_plan(test_step, plan_json, file_path)

            end_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

            # 聚合截图列表：第一个为页面标记截图，其余为每个动作后的截图
            screenshots_list = [{"type": "base64", "data": marker_screenshot}] + [
                {"type": "base64", "data": step.get("screenshot")}
                for step in execution_steps if step.get("screenshot")
            ]

            # 构建符合用例步骤格式的结构体
            status_str = "passed" if execution_result.get("success") else "failed"
            execution_steps_dict = {
                # id 与 number 将由外层流程（如 LangGraph 节点）补充
                "description": f"action: {test_step}",
                "actions": execution_steps,              # 所有动作聚合在一起
                "screenshots": screenshots_list,          # 所有截图聚合在一起
                "modelIO": json.dumps(plan_json, indent=2, ensure_ascii=False) if isinstance(plan_json, dict) else "",
                "status": status_str,
                "start_time": start_time,
                "end_time": end_time,
            }
            
            # 自动存储step数据
            self.add_step_data(execution_steps_dict, step_type="action")
            
            return execution_steps_dict, execution_result

        except Exception as e:
            error_msg = f"AI instruction failed: {str(e)}"
            logging.error(error_msg)

            end_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

            # 安全获取可能未定义的变量
            safe_marker_screenshot = locals().get('marker_screenshot')
            safe_plan_json = locals().get('plan_json', {})

            # 构建错误情况下的执行步骤字典结构
            error_screenshots = [{"type": "base64", "data": safe_marker_screenshot}] if safe_marker_screenshot else []

            error_execution_steps = {
                "description": f"action: {test_step}",
                "actions": [],
                "screenshots": error_screenshots,
                "modelIO": "",  # 无有效模型交互输出
                "status": "failed",
                "error": str(e),
                "start_time": start_time,
                "end_time": end_time,
            }

            # 自动存储错误step数据
            self.add_step_data(error_execution_steps, step_type="action")

            return error_execution_steps, {"success": False, "message": f"An exception occurred in action: {str(e)}"}

    async def verify(self, assertion: str) -> tuple[Dict[str, Any], Dict[str, Any]]:
        """
        执行AI驱动的断言验证

        Args:
            assertion: 断言描述

        Returns:
            Tuple (step_dict, model_output)
        """
        if not self.is_initialized:
            raise RuntimeError("ParallelUITester not initialized")

        start_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        
        try:
            logging.info(f"Executing AI assertion: {assertion}")

            # 爬取当前页面
            dp = DeepCrawler(self.page)
            _, id_map = await dp.crawl(highlight=True, viewport_only=True)

            marker_screenshot = await self._actions.b64_page_screenshot(file_name="marker")
            await dp.remove_marker()

            screenshot = await self._actions.b64_page_screenshot(file_name="assert")

            # 获取页面结构
            await dp.crawl(highlight=False, highlight_text=True, viewport_only=True)
            page_structure = dp.get_text()

            # 准备LLM输入
            user_prompt = self._prepare_prompt(
                f"assertion: {assertion}",
                f"page label: {id_map}",
                LLMPrompt.verification_prompt,
                page_structure
            )

            result = await self.llm.get_llm_response(
                LLMPrompt.verification_system_prompt,
                user_prompt,
                images=[marker_screenshot, screenshot]
            )

            # 处理结果
            if isinstance(result, str):
                try:
                    model_output = json.loads(result)
                except json.JSONDecodeError:
                    model_output = {
                        "Validation Result": "Validation Failed",
                        "Details": f"LLM returned invalid JSON: {result}"
                    }
            elif isinstance(result, dict):
                model_output = result
            else:
                model_output = {
                    "Validation Result": "Validation Failed",
                    "Details": f"LLM returned unexpected type: {type(result)}"
                }

            # 确定状态
            is_passed = model_output.get("Validation Result") == "Validation Passed"

            end_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

            # 构建验证结果
            status_str = "passed" if is_passed else "failed"

            verification_step = {
                "description": f"verify: {assertion}",
                "actions": [],  # 断言步骤通常不包含 actions
                "screenshots": [
                    {"type": "base64", "data": marker_screenshot},
                    {"type": "base64", "data": screenshot}
                ],
                "modelIO": result if isinstance(result, str) else json.dumps(result, ensure_ascii=False),
                "status": status_str,
                "start_time": start_time,
                "end_time": end_time,
            }

            # 自动存储assertion step数据
            self.add_step_data(verification_step, step_type="assertion")

            return verification_step, model_output

        except Exception as e:
            error_msg = f"AI assertion failed: {str(e)}"
            logging.error(error_msg)

            # 尝试获取基本的页面信息，即使出错了
            try:
                basic_screenshot = await self._actions.b64_page_screenshot(file_name="error_assert")
            except:
                basic_screenshot = None

            end_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

            error_step = {
                "description": f"verify: {assertion}",
                "actions": [],
                "screenshots": [{"type": "base64", "data": basic_screenshot}] if basic_screenshot else [],
                "modelIO": "",
                "status": "failed",
                "error": str(e),
                "start_time": start_time,
                "end_time": end_time,
            }

            # 自动存储错误assertion step数据
            self.add_step_data(error_step, step_type="assertion")

            # 返回 error_step 和 一个表示失败的模型输出
            return error_step, {"Validation Result": "Validation Failed", "Details": error_msg}

    def _prepare_prompt(self, test_step: str, browser_elements: str,
                       prompt_template: str, page_structure: str) -> str:
        """准备LLM提示"""
        return (f"test step: {test_step}\n"
                f"====================\n"
                f"pageDescription (interactive elements): {browser_elements}\n"
                f"====================\n"
                f"page_structure (full text content): {page_structure}\n"
                f"====================\n"
                f"{prompt_template}")

    async def _generate_plan(self, system_prompt: str, prompt: str,
                           browser_screenshot: str) -> Dict[str, Any]:
        """生成测试计划"""
        max_retries = 2

        for attempt in range(max_retries):
            try:
                # 获取LLM响应
                test_plan = await self.llm.get_llm_response(
                    system_prompt,
                    prompt,
                    images=browser_screenshot
                )

                # 处理API错误
                if isinstance(test_plan, dict) and "error" in test_plan:
                    raise ValueError(f"LLM API error: {test_plan['error']}")

                # 验证响应
                if not test_plan or not (isinstance(test_plan, str) and test_plan.strip()):
                    raise ValueError(f"Empty response from LLM: {test_plan}")

                try:
                    plan_json = json.loads(test_plan)
                except json.JSONDecodeError as je:
                    raise ValueError(f"Invalid JSON response: {str(je)}")

                if not plan_json.get('actions'):
                    raise ValueError(f"No valid actions found in plan")

                return plan_json

            except (ValueError, json.JSONDecodeError) as e:
                if attempt == max_retries - 1:
                    raise ValueError(f"Failed to generate valid plan after {max_retries} attempts: {str(e)}")

                logging.warning(f"Plan generation attempt {attempt + 1} failed: {str(e)}, retrying...")
                await asyncio.sleep(1)

    async def _execute_plan(self, user_case: str, plan_json: Dict[str, Any],
                          file_path: str = None) -> Dict[str, Any]:
        """执行测试计划"""
        execute_results = []
        action_count = len(plan_json.get('actions', []))

        for index, action in enumerate(plan_json.get('actions', []), 1):
            action_desc = f"{action.get('type', 'Unknown')}"
            logging.info(f"Executing step {index}/{action_count}: {action_desc}")

            try:
                # 执行动作
                if action.get("type") == "Upload" and file_path:
                    execution_result = await self._action_executor._execute_upload(action, file_path)
                else:
                    execution_result = await self._action_executor.execute(action)

                # 处理执行结果
                if isinstance(execution_result, dict):
                    success = execution_result.get("success", False)
                    message = execution_result.get("message", "No message provided")
                else:
                    success = bool(execution_result)
                    message = "Legacy boolean result"

                # 等待页面稳定
                try:
                    await self.page.wait_for_load_state('networkidle', timeout=10000)
                    await asyncio.sleep(1.5)
                except Exception as e:
                    logging.warning(f"Page did not become network idle: {e}")
                    await asyncio.sleep(1)

                # 截屏
                post_action_ss = await self._actions.b64_page_screenshot(
                    file_name=f"action_{action_desc}_{index}"
                )

                action_result = {
                    "description": action_desc,
                    "success": success,
                    "message": message,
                    "screenshot": post_action_ss,
                    "index": index
                }

                execute_results.append(action_result)

                if not success:
                    logging.error(f"Action {index} failed: {message}")
                    return execute_results, action_result

            except Exception as e:
                error_msg = f"Action {index} failed with error: {str(e)}"
                logging.error(error_msg)
                failure_result = {"success": False, "message": f"Exception occurred: {str(e)}", "screenshot": None}
                return execute_results, failure_result

        logging.info("All actions executed successfully")
        post_action_ss = await self._actions.b64_page_screenshot(file_name="final_success")
        return execute_results, {"success": True, "message": "All actions executed successfully", "screenshot": post_action_ss}


    def get_monitoring_results(self) -> Dict[str, Any]:
        """获取监控结果"""
        results = {}

        if self.network_check:
            results["network"] = self.network_check.get_messages()

        if self.console_check:
            results["console"] = self.console_check.get_messages()

        return results

    async def end_session(self):
        """结束会话: 关闭监控、回收资源（简化实现）"""
        try:
            results = self.get_monitoring_results()

            if self.console_check:
                self.console_check.remove_listeners()
            if self.network_check:
                self.network_check.remove_listeners()
            
            return results
        except Exception as e:
            logging.warning(f"ParallelUITester end_session cleanup warning: {e}")

    async def cleanup(self):
        """Lightweight wrapper so external callers can always call cleanup()."""
        try:
            await self.end_session()
        except Exception as e:
            logging.warning(f"UITester.cleanup encountered an error: {e}")

    def set_current_test_name(self, name: str):
        """Set the current test case name (stub for compatibility with LangGraph workflow)."""
        self.current_test_name = name

    # === 数据存储管理方法 ===
    def start_case(self, case_name: str, case_data: Optional[Dict[str, Any]] = None):
        """开始一个新的测试case"""
        # 同时设置current_test_name，确保兼容性
        self.current_test_name = case_name
        
        # 如果有现有的case数据，先完成它
        if self.current_case_data:
            logging.warning(f"Starting new case '{case_name}' while previous case '{self.current_case_data.get('name')}' is still active. Finishing previous case.")
            self.finish_case("interrupted", "Case was interrupted by new case start")
        
        self.current_case_data = {
            "name": case_name,
            "start_time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "case_info": case_data or {},
            "steps": [],
            "status": "running",
            # "messages": {
            #     "console": [],
            #     "network": {
            #         "failed_requests": [],
            #         "responses": []
            #     }
            # },
            "report": []
        }
        self.current_case_steps = []
        self.step_counter = 0  # 重置step计数器
        logging.info(f"Started tracking case: {case_name} (step counter reset)")

    def add_step_data(self, step_data: Dict[str, Any], step_type: str = "action"):
        """添加step数据到当前case"""
        if not self.current_case_data:
            logging.warning("No active case to add step data to")
            return
            
        self.step_counter += 1
        
        # 处理actions数据，移除其中的截图
        original_actions = step_data.get("actions", [])
        cleaned_actions = []
        
        for action in original_actions:
            # 复制action数据，但移除screenshot字段
            cleaned_action = {}
            for key, value in action.items():
                if key != "screenshot":  # 移除screenshot字段
                    cleaned_action[key] = value
            cleaned_actions.append(cleaned_action)
        
        # 转换为符合runner格式的step结构
        formatted_step = {
            "id": self.step_counter,
            "number": self.step_counter,
            "description": step_data.get("description", ""),
            "screenshots": step_data.get("screenshots", []),
            "modelIO": step_data.get("modelIO", "") if isinstance(step_data.get("modelIO", ""), str) else json.dumps(step_data.get("modelIO", ""), ensure_ascii=False),
            "actions": cleaned_actions,  # 使用清理后的actions
            "status": step_data.get("status", "passed"),
            "end_time": step_data.get("end_time", datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
        }
        
        # 如果有错误信息，添加到step中
        if "error" in step_data:
            formatted_step["error"] = step_data["error"]
        
        self.current_case_steps.append(formatted_step)
        self.current_case_data["steps"].append(formatted_step)
        logging.info(f"Added step {formatted_step['id']} to case {self.current_test_name}")

    def finish_case(self, final_status: str = "completed", final_summary: Optional[str] = None):
        """结束当前case并保存数据"""
        if not self.current_case_data:
            logging.warning("No active case to finish")
            return
            
        case_name = self.current_case_data.get("name", "Unknown")
        steps_count = len(self.current_case_steps)
        
        # 获取监控数据
        # monitoring_data = self.get_monitoring_results()
        
        self.current_case_data.update({
            "end_time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "status": final_status,
            "final_summary": final_summary or "",
            "total_steps": steps_count
        })
        
        # # 更新监控数据
        # if monitoring_data:
        #     if "network" in monitoring_data:
        #         self.current_case_data["messages"]["network"] = monitoring_data["network"]
        #         logging.info(f"Added network monitoring data for case '{case_name}'")
        #     if "console" in monitoring_data:
        #         self.current_case_data["messages"]["console"] = monitoring_data["console"]
        #         logging.info(f"Added console monitoring data for case '{case_name}'")
        
        # 验证steps数据
        stored_steps = self.current_case_data.get("steps", [])
        if len(stored_steps) != steps_count:
            logging.error(f"Steps count mismatch for case '{case_name}': stored={len(stored_steps)}, tracked={steps_count}")
        
        # 保存到全部案例数据中
        self.all_cases_data.append(self.current_case_data.copy())
        logging.info(f"Finished case: '{case_name}' with status: {final_status}, {steps_count} steps, total cases: {len(self.all_cases_data)}")
        
        # 清理当前case数据
        self.current_case_data = None
        self.current_case_steps = []
        self.step_counter = 0

    def get_current_case_steps(self) -> List[Dict[str, Any]]:
        """获取当前case的所有step数据"""
        return self.current_case_steps.copy()

    def get_all_cases_data(self) -> List[Dict[str, Any]]:
        """获取所有case的完整数据"""
        return self.all_cases_data.copy()

    def get_case_summary(self) -> Dict[str, Any]:
        """获取测试执行的汇总信息"""
        total_cases = len(self.all_cases_data)
        passed_cases = sum(1 for case in self.all_cases_data if case.get("status") == "passed")
        failed_cases = sum(1 for case in self.all_cases_data if case.get("status") == "failed")
        total_steps = sum(case.get("total_steps", 0) for case in self.all_cases_data)
        
        return {
            "total_cases": total_cases,
            "passed_cases": passed_cases,
            "failed_cases": failed_cases,
            "total_steps": total_steps,
            "success_rate": passed_cases / total_cases if total_cases > 0 else 0,
            "all_cases_data": self.all_cases_data
        }
        
    def generate_runner_format_report(self, test_id: str = None, test_name: str = None) -> Dict[str, Any]:
        """生成符合runner标准格式的完整测试报告"""
        import uuid
        from datetime import datetime
        
        if not self.all_cases_data:
            logging.warning("No case data available for report generation")
            return {}
            
        # 验证数据完整性
        total_steps = 0
        for i, case in enumerate(self.all_cases_data):
            case_steps = case.get("steps", [])
            case_name = case.get("name", f"Case_{i}")
            total_steps += len(case_steps)
            logging.info(f"Report validation - Case '{case_name}': {len(case_steps)} steps, status: {case.get('status', 'unknown')}")
            
        logging.info(f"Report generation - Total cases: {len(self.all_cases_data)}, Total steps: {total_steps}")
            
        # 计算整体测试时间
        start_times = [case.get("start_time") for case in self.all_cases_data if case.get("start_time")]
        end_times = [case.get("end_time") for case in self.all_cases_data if case.get("end_time")]
        
        overall_start = min(start_times) if start_times else datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        overall_end = max(end_times) if end_times else datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        
        # 计算持续时间（简化计算，实际可以更精确）
        try:
            start_dt = datetime.strptime(overall_start, "%Y-%m-%d %H:%M:%S")
            end_dt = datetime.strptime(overall_end, "%Y-%m-%d %H:%M:%S")
            duration = (end_dt - start_dt).total_seconds()
        except:
            duration = 0.0
        
        # 判断整体状态
        overall_status = "completed"
        if any(case.get("status") == "failed" for case in self.all_cases_data):
            overall_status = "failed"
        
        summary = self.get_case_summary()
        
        runner_format = {
            "test_id": test_id or str(uuid.uuid4()),
            "test_type": "UI_Agent",
            "test_name": test_name or "UI Agent Test Suite",
            "category": "function",
            "status": overall_status,
            "start_time": overall_start,
            "end_time": overall_end,
            "duration": duration,
            "results": {
                "total_cases": summary["total_cases"],
                "passed_cases": summary["passed_cases"],
                "failed_cases": summary["failed_cases"],
                "total_steps": summary["total_steps"],
                "success_rate": summary["success_rate"]
            },
            "sub_tests": self.all_cases_data,  # 这里包含了所有符合格式的case数据
            "logs": [],  # 可以根据需要添加日志
            "traces": [],  # 可以根据需要添加追踪信息
            "error_message": "",
            "error_details": {},
            "metrics": {}
        }
        
        return runner_format


    async def get_current_page(self):
        try:
            if self.driver:
                return await self.driver.get_new_page()
        except Exception as e:
            logging.warning(f"UITester.get_current_page failed to detect new page: {e}")
        return self.driver.get_page()

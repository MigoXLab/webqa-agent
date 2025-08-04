import logging
from abc import ABC, abstractmethod
from typing import Dict, Any
from datetime import datetime

from webqa_agent.data import TestStatus, TestConfiguration, TestResult
from webqa_agent.browser.session import BrowserSession
from webqa_agent.testers import (
    WebAccessibilityTest, PageTextTest,
    PageContentTest, PageButtonTest, LighthouseMetricsTest
)
from webqa_agent.data.test_structures import SubTestResult, TestCategory


class BaseTestRunner(ABC):
    """Base class for test runners"""

    @abstractmethod
    async def run_test(self, session: BrowserSession, test_config: TestConfiguration,
                       llm_config: Dict[str, Any], target_url: str) -> TestResult:
        """Run the test and return results"""
        pass


class UIAgentLangGraphRunner(BaseTestRunner):
    """Runner for UIAgent LangGraph tests"""

    async def run_test(self, session: BrowserSession, test_config: TestConfiguration,
                       llm_config: Dict[str, Any], target_url: str) -> TestResult:
        """Run UIAgent LangGraph test using LangGraph workflow with ParallelUITester"""
        import asyncio
        from webqa_agent.testers.ui_tester import UITester
        from webqa_agent.testers.langgraph.graph import app as graph_app

        logging.info(f"Running UIAgent LangGraph test: {test_config.test_name}")

        result = TestResult(
            test_id=test_config.test_id,
            test_type=test_config.test_type,
            test_name=test_config.test_name,
            status=TestStatus.RUNNING,
            category=TestCategory.FUNCTION
        )

        parallel_tester: UITester | None = None
        try:
            parallel_tester = UITester(llm_config=llm_config, browser_session=session)
            await parallel_tester.initialize()

            business_objectives = test_config.test_specific_config.get("business_objectives", "")

            cookies = test_config.test_specific_config.get("cookies")

            initial_state = {
                "url": target_url,
                "business_objectives": business_objectives,
                "cookies": cookies,
                "completed_cases": [],
                "reflection_history": [],
                "remaining_objectives": business_objectives,
                "ui_tester_instance": parallel_tester,
                "current_test_case_index": 0,
            }

            graph_config = {
                "configurable": {"ui_tester_instance": parallel_tester},
                "recursion_limit": 100
            }

            # Mapping from case name to status obtained from LangGraph aggregate_results
            graph_case_status_map: Dict[str, str] = {}

            # 执行LangGraph工作流
            graph_completed = False
            async for event in graph_app.astream(initial_state, config=graph_config):
                # Each event is a dict where keys are node names and values are their outputs
                for node_name, node_output in event.items():
                    if node_name == "aggregate_results":
                        # Capture final report to retrieve authoritative case statuses
                        final_report = node_output.get("final_report", {})
                        for idx, case_res in enumerate(final_report.get("completed_summary", [])):
                            case_name = case_res.get("case_name") or case_res.get("name") or f"Case_{idx + 1}"
                            graph_case_status_map[case_name] = case_res.get("status", "failed").lower()

                    if node_name == "__end__":
                        logging.info("Graph execution completed successfully")
                        graph_completed = True
                        break
                    else:
                        logging.debug(f"Node '{node_name}' completed")

                # Break out of the outer loop if we found __end__
                if graph_completed:
                    break

            # === 使用UITester的新数据存储机制 ===
            sub_tests = []
            runner_format_report = {}

            if parallel_tester:
                # 生成符合runner标准格式的完整报告
                test_name = f"UI Agent Test - {target_url}"
                runner_format_report = parallel_tester.generate_runner_format_report(
                    test_id=test_config.test_id,
                    test_name=test_name
                )

                sub_tests_data = runner_format_report.get("sub_tests", [])
                logging.info(f"Generated runner format report with {len(sub_tests_data)} cases")

                if not sub_tests_data:
                    logging.warning("No sub_tests data found in runner format report")

                # 将runner格式的sub_tests转换为TestResult.SubTestResult
                for i, case in enumerate(sub_tests_data):
                    case_name = case.get("name", f"Unnamed test case - {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
                    case_steps = case.get("steps", [])

                    # 验证case数据完整性
                    logging.info(f"Processing case {i + 1}: '{case_name}' with {len(case_steps)} steps")
                    if not case_steps:
                        logging.warning(f"Case '{case_name}' has no steps data")

                    # Prefer status from graph aggregation if available
                    sub_status = graph_case_status_map.get(case_name, case.get("status", "failed")).lower()
                    status_mapping = {
                        "pending": TestStatus.PENDING,
                        "running": TestStatus.RUNNING,
                        "passed": TestStatus.PASSED,
                        "completed": TestStatus.PASSED,
                        "failed": TestStatus.FAILED,
                        "cancelled": TestStatus.CANCELLED,
                    }
                    status_enum = status_mapping.get(sub_status, TestStatus.FAILED)

                    sub_tests.append(
                        SubTestResult(
                            name=case_name,
                            status=status_enum,
                            metrics={},
                            steps=case_steps,
                            messages=case.get("messages", {}),
                            start_time=case.get("start_time"),
                            end_time=case.get("end_time"),
                            final_summary=case.get("final_summary", ""),
                            report=case.get("report", [])
                        )
                    )

                result.sub_tests = sub_tests

                # 从runner格式报告提取汇总指标
                results_data = runner_format_report.get("results", {})
                result.add_metric("test_case_count", results_data.get("total_cases", 0))
                result.add_metric("passed_test_cases", results_data.get("passed_cases", 0))
                result.add_metric("failed_test_cases", results_data.get("failed_cases", 0))
                result.add_metric("total_steps", results_data.get("total_steps", 0))
                result.add_metric("success_rate", results_data.get("success_rate", 0))

                # 从每个case的messages中提取网络和控制台数据并汇总
                total_failed_requests = 0
                total_requests = 0
                total_console_errors = 0

                for case in runner_format_report.get("sub_tests", []):
                    case_messages = case.get("messages", {})
                    if isinstance(case_messages, dict):
                        network_data = case_messages.get("network", {})
                        if isinstance(network_data, dict):
                            failed_requests = network_data.get("failed_requests", [])
                            responses = network_data.get("responses", [])
                            total_failed_requests += len(failed_requests)
                            total_requests += len(responses)

                        console_data = case_messages.get("console", [])
                        if isinstance(console_data, list):
                            total_console_errors += len(console_data)

                result.add_metric("network_failed_requests_count", total_failed_requests)
                result.add_metric("network_total_requests_count", total_requests)
                result.add_metric("console_error_count", total_console_errors)

                # 设置整体状态
                runner_status = runner_format_report.get("status", "failed")
                if runner_status == "completed":
                    result.status = TestStatus.PASSED
                else:
                    result.status = TestStatus.FAILED
                    result.error_message = runner_format_report.get("error_message", "Test execution failed")

            else:
                logging.error("No UITester instance available for data extraction")
                result.status = TestStatus.FAILED
                result.error_message = "No test cases were executed or results were not available"

            logging.info(f"UIAgent LangGraph test completed via LangGraph workflow: {test_config.test_name}")

        except Exception as e:
            error_msg = f"UIAgent LangGraph test failed: {str(e)}"
            result.status = TestStatus.FAILED
            result.error_message = error_msg
            logging.error(error_msg)
            raise e

        finally:
            # Cleanup parallel tester
            if parallel_tester:
                try:
                    # UITester现在已经自动管理监控数据，只需要清理资源
                    await parallel_tester.cleanup()
                    logging.info("UITester cleanup completed")
                except Exception as e:
                    logging.error(f"Error cleaning up UITester: {e}")

        return result


class UXTestRunner(BaseTestRunner):
    """Runner for UX tests using parallel-friendly test classes without GetLog dependencies"""

    async def run_test(self, session: BrowserSession, test_config: TestConfiguration,
                       llm_config: Dict[str, Any], target_url: str) -> TestResult:
        """Run UX tests with enhanced screenshot and data collection"""

        logging.info(f"Running UX test: {test_config.test_name}")

        result = TestResult(
            test_id=test_config.test_id,
            test_type=test_config.test_type,
            test_name=test_config.test_name,
            status=TestStatus.RUNNING,
            category=TestCategory.UI
        )

        try:
            page = session.get_page()
            browser_config = session.browser_config

            text_test = PageTextTest(llm_config)
            text_result: SubTestResult = await text_test.run(page=page)

            # Run ParallelPageContentTest
            content_test = PageContentTest(llm_config)
            content_result: SubTestResult = await content_test.run(page=page)

            result.sub_tests = [content_result, text_result]

            # Extract metrics
            content_status = content_result.status
            text_status = text_result.status

            # Determine overall status
            if text_status == "passed" and content_status == "passed":
                result.status = TestStatus.PASSED
            else:
                result.status = TestStatus.FAILED

                # Collect errors from both tests
                errors = [r.messages["page"] for r in [text_result, content_result] if "page" in r.messages]

                if errors:
                    result.error_message = "; ".join(errors)

            logging.info(f"UX test completed: {test_config.test_name}")

        except Exception as e:
            error_msg = f"UX test failed: {str(e)}"
            result.status = TestStatus.FAILED
            result.error_message = error_msg
            logging.error(error_msg)
            raise e

        return result


class LighthouseTestRunner(BaseTestRunner):
    """Runner for Lighthouse"""

    async def run_test(self, session: BrowserSession, test_config: TestConfiguration,
                       llm_config: Dict[str, Any], target_url: str) -> TestResult:
        """Run  tests"""
        logging.info(f"Running Lighthouse test: {test_config.test_name}")

        result = TestResult(
            test_id=test_config.test_id,
            test_type=test_config.test_type,
            test_name=test_config.test_name,
            status=TestStatus.RUNNING,
            category=TestCategory.PERFORMANCE
        )

        try:
            browser_config = session.browser_config

            # Only run Lighthouse on Chromium browsers
            if browser_config.get("browser_type") != "chromium":
                logging.warning("Lighthouse tests require Chromium browser, skipping")
                result.status = TestStatus.INCOMPLETED
                result.results = {"skipped": "Lighthouse requires Chromium browser"}
                return result

            # Run Lighthouse test
            lighthouse_test = LighthouseMetricsTest()
            lighthouse_results: SubTestResult = await lighthouse_test.run(target_url, browser_config=browser_config)

            result.sub_tests = [lighthouse_results]
            result.status = lighthouse_results.status
            logging.info(f"Lighthouse test completed: {test_config.test_name}")

        except Exception as e:
            error_msg = f"Lighthouse test failed: {str(e)}"
            result.status = TestStatus.FAILED
            result.error_message = error_msg
            logging.error(error_msg)
            raise e

        return result


class ButtonTestRunner(BaseTestRunner):
    """Runner dedicated to button click tests"""

    async def run_test(self, session: BrowserSession, test_config: TestConfiguration,
                       llm_config: Dict[str, Any], target_url: str) -> TestResult:
        logging.info(f"Running Button test: {test_config.test_name}")

        result = TestResult(
            test_id=test_config.test_id,
            test_type=test_config.test_type,
            test_name=test_config.test_name,
            status=TestStatus.RUNNING,
            category=TestCategory.FUNCTION
        )

        try:
            page = session.get_page()
            browser_config = session.browser_config

            # Discover clickable elements via crawler
            from webqa_agent.crawler.crawl import CrawlHandler
            crawler = CrawlHandler(target_url)
            clickable_elements = await crawler.clickable_elements_detection(page)
            logging.info(f"Clickable elements number: {len(clickable_elements)}")

            button_test = PageButtonTest()
            button_test_result = await button_test.run(
                target_url, page=page, clickable_elements=clickable_elements,
                browser_config=browser_config
            )

            # Second subtest: each clickable result? keep detailed reports if needed; here we only include traverse test
            result.sub_tests = [button_test_result]

            # Overall metrics/status
            result.status = button_test_result.status

            logging.info(f"Button test completed: {test_config.test_name}")

        except Exception as e:
            error_msg = f"Button test failed: {str(e)}"
            result.status = TestStatus.FAILED
            result.error_message = error_msg
            logging.error(error_msg)
            raise e

        return result


class WebBasicCheckRunner(BaseTestRunner):
    """Runner for Web Basic Check tests"""

    async def run_test(self, session: BrowserSession, test_config: TestConfiguration,
                       llm_config: Dict[str, Any], target_url: str) -> TestResult:
        """Run Web Basic Check tests"""
        logging.info(f"Running Web Basic Check test: {test_config.test_name}")

        result = TestResult(
            test_id=test_config.test_id,
            test_type=test_config.test_type,
            test_name=test_config.test_name,
            status=TestStatus.RUNNING,
            category=TestCategory.FUNCTION
        )

        try:
            page = session.get_page()

            # Discover page elements
            from webqa_agent.crawler.crawl import CrawlHandler
            crawler = CrawlHandler(target_url)
            links = await crawler.extract_links(page)

            # WebAccessibilityTest
            accessibility_test = WebAccessibilityTest()
            accessibility_result = await accessibility_test.run(target_url, links)

            result.sub_tests = [accessibility_result]
            result.status = accessibility_result.status
            logging.info(f"Web Basic Check test completed: {test_config.test_name}")

        except Exception as e:
            error_msg = f"Web Basic Check test failed: {str(e)}"
            result.status = TestStatus.FAILED
            result.error_message = error_msg
            logging.error(error_msg)
            raise e

        return result

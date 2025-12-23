import asyncio
import json
import logging
import time
from abc import ABC, abstractmethod
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List

from webqa_agent.browser import BrowserSession
from webqa_agent.data import TestConfiguration, TestResult, TestStatus
from webqa_agent.data.test_structures import (SubTestReport, SubTestResult,
                                              get_category_for_test_type)
from webqa_agent.testers import (LighthouseMetricsTest, PageButtonTest,
                                 PageContentTest, PageTextTest,
                                 WebAccessibilityTest)
from webqa_agent.utils import Display
from webqa_agent.utils.log_icon import icon
from webqa_agent.utils import i18n


class BaseTestRunner(ABC):
    """Base class for test runners."""

    @abstractmethod
    async def run_test(
        self, session: BrowserSession, test_config: TestConfiguration, llm_config: Dict[str, Any], target_url: str,
        session_pool=None
    ) -> TestResult:
        """Run the test and return results."""
        pass


class UIAgentLangGraphRunner(BaseTestRunner):
    """Runner for UIAgent LangGraph tests."""

    async def run_test(
        self, session: BrowserSession, test_config: TestConfiguration, llm_config: Dict[str, Any], target_url: str,
        session_pool=None
    ) -> TestResult:
        """Run UIAgent LangGraph test using LangGraph workflow with
        ParallelUITester."""

        with Display.display(test_config.test_name):
            from webqa_agent.testers.case_gen.graph import app as graph_app

            result = TestResult(
                test_id=test_config.test_id,
                test_type=test_config.test_type,
                test_name=test_config.test_name,
                status=TestStatus.RUNNING,
                category=get_category_for_test_type(test_config.test_type),
            )

            try:
                business_objectives = test_config.test_specific_config.get('business_objectives', '')
                logging.info(f"{icon['running']} Running test: {test_config.test_name} with business objectives: {business_objectives}")

                # Extract dynamic step generation configuration
                dynamic_step_config = test_config.test_specific_config.get('dynamic_step_generation', {
                    "enabled": False,
                    "max_dynamic_steps": 5,
                    "min_elements_threshold": 2
                })

                cookies = test_config.test_specific_config.get('cookies')

                initial_state = {
                    # Core configuration
                    'url': target_url,
                    'business_objectives': business_objectives,
                    'cookies': cookies,
                    'language': test_config.report_config.get('language', 'zh-CN'),

                    # Test data
                    'test_cases': [],  # Will be populated by plan_test_cases
                    'completed_cases': [],
                    'recorded_cases': [],

                    # Control flags
                    'generate_only': False,
                    'skip_reflection': False,

                    # Feature configuration
                    'dynamic_step_generation': dynamic_step_config,

                    # Infrastructure
                    'session_pool': session_pool,
                    'llm_config': llm_config,
                }

                graph_config = {'recursion_limit': 100}

                # Mapping from case name to status obtained from LangGraph aggregate_results
                graph_case_status_map: Dict[str, str] = {}
                recorded_cases_from_graph: List[dict] = []

                # 执行LangGraph工作流，直接使用 ainvoke 获取最终状态
                final_state = await graph_app.ainvoke(initial_state, config=graph_config)
                
                # 从最终状态获取 recorded_cases
                recorded_cases_from_graph = final_state.get('recorded_cases', [])
                logging.info(f"Retrieved {len(recorded_cases_from_graph)} recorded cases from final graph state")
                
                # 从最终状态获取 completed_cases 用于状态映射
                completed_cases = final_state.get('completed_cases', [])
                for idx, case_res in enumerate(completed_cases):
                    case_name = case_res.get('case_name') or case_res.get('name') or f'Case_{idx + 1}'
                    graph_case_status_map[case_name] = case_res.get('status', 'failed').lower()
                
                # === 使用recorded_cases中的数据构建测试结果 ===
                sub_tests = []
                
                if recorded_cases_from_graph:
                    logging.debug(f'Processing {len(recorded_cases_from_graph)} cases from recorded_cases')
                    
                    # 将recorded_cases转换为TestResult.SubTestResult
                    for i, recorded_case in enumerate(recorded_cases_from_graph):
                        case_name = recorded_case.get('name', f"Unnamed test case - {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
                        case_steps_raw = recorded_case.get('steps', [])
                        
                        # 验证case数据完整性
                        logging.debug(f"Processing case {i + 1}: '{case_name}' with {len(case_steps_raw)} steps")
                        if not case_steps_raw:
                            logging.warning(f"Case '{case_name}' has no steps data")
                        
                        # 转换步骤数据为SubTestStep格式
                        from webqa_agent.data.test_structures import SubTestStep, SubTestScreenshot, SubTestReport
                        
                        case_steps = []
                        for step_data in case_steps_raw:
                            # 转换截图数据
                            screenshots = []
                            for scr in step_data.get('screenshots', []):
                                if isinstance(scr, dict) and scr.get('type') == 'base64':
                                    screenshots.append(SubTestScreenshot(type='base64', data=scr.get('data', '')))
                            
                            # 转换状态
                            step_status_str = step_data.get('status', 'passed').lower()
                            step_status = TestStatus.PASSED
                            if step_status_str in ['failed', 'error', 'failure']:
                                step_status = TestStatus.FAILED
                            elif step_status_str in ['warning', 'warn']:
                                step_status = TestStatus.WARNING
                            
                            case_steps.append(SubTestStep(
                                id=step_data.get('id', 0),
                                description=step_data.get('description', ''),
                                screenshots=screenshots,
                                modelIO=step_data.get('modelIO', ''),
                                actions=step_data.get('actions', []),
                                status=step_status,
                            ))
                        
                        # 获取case的整体状态
                        case_status_str = recorded_case.get('status', 'failed').lower()
                        # Prefer status from graph aggregation if available
                        if case_name in graph_case_status_map:
                            case_status_str = graph_case_status_map[case_name]
                        
                        status_mapping = {
                            'pending': TestStatus.PENDING,
                            'running': TestStatus.RUNNING,
                            'passed': TestStatus.PASSED,
                            'completed': TestStatus.PASSED,
                            'warning': TestStatus.WARNING,
                            'failed': TestStatus.FAILED,
                            'cancelled': TestStatus.CANCELLED,
                        }
                        status_enum = status_mapping.get(case_status_str, TestStatus.FAILED)
                        
                        # 构建报告
                        reports = []
                        if recorded_case.get('final_summary'):
                            reports.append(SubTestReport(title='Summary', issues=recorded_case.get('final_summary', '')))
                        
                        sub_tests.append(
                            SubTestResult(
                                name=case_name,
                                status=status_enum,
                                metrics={},
                                steps=case_steps,
                                messages={},  # recorded_cases不包含messages数据，设为空字典
                                start_time=recorded_case.get('start_time'),
                                end_time=recorded_case.get('end_time'),
                                final_summary=recorded_case.get('final_summary', ''),
                                report=reports,
                            )
                        )
                    
                    result.sub_tests = sub_tests
                    
                    # 计算汇总指标
                    total_cases = len(recorded_cases_from_graph)
                    passed_cases = sum(1 for case in recorded_cases_from_graph if case.get('status', '').lower() in ['passed', 'completed'])
                    failed_cases = total_cases - passed_cases
                    total_steps = sum(len(case.get('steps', [])) for case in recorded_cases_from_graph)
                    success_rate = (passed_cases / total_cases * 100) if total_cases > 0 else 0
                    
                    result.add_metric('test_case_count', total_cases)
                    result.add_metric('passed_test_cases', passed_cases)
                    result.add_metric('failed_test_cases', failed_cases)
                    result.add_metric('total_steps', total_steps)
                    result.add_metric('success_rate', success_rate)
                    
                    # 设置整体状态
                    if failed_cases == 0:
                        result.status = TestStatus.PASSED
                    else:
                        result.status = TestStatus.FAILED
                        result.error_message = f'{failed_cases} out of {total_cases} test cases failed'
                    
                else:
                    logging.error('No recorded_cases data found in graph state')
                    result.status = TestStatus.FAILED
                    result.error_message = 'No test cases were executed or recorded_cases data was not available'

                logging.info(f"{icon['check']} Test completed: {test_config.test_name}")

            except Exception as e:
                error_msg = f'AI Functional Test failed: {str(e)}'
                result.status = TestStatus.FAILED
                result.error_message = error_msg
                logging.error(error_msg)
                raise

            finally:
                # Note: Browser session cleanup is handled by graph internally
                logging.debug('LangGraph test cleanup completed')

            return result


class UXTestRunner(BaseTestRunner):
    """Runner for UX tests using parallel-friendly test classes without GetLog
    dependencies."""

    async def run_test(
        self, session: BrowserSession, test_config: TestConfiguration, llm_config: Dict[str, Any], target_url: str,
        session_pool=None
    ) -> TestResult:
        """Run UX tests with enhanced screenshot and data collection."""

        with Display.display(test_config.test_name):
            result = TestResult(
                test_id=test_config.test_id,
                test_type=test_config.test_type,
                test_name=test_config.test_name,
                status=TestStatus.RUNNING,
                category=get_category_for_test_type(test_config.test_type),
            )

            try:
                logging.info(f"{icon['running']} Running UX test: {test_config.test_name}")
                page = session.page

                text_test = PageTextTest(llm_config, report_config=test_config.report_config)
                text_result: SubTestResult = await text_test.run(page=page)

                # Run ParallelPageContentTest
                content_test = PageContentTest(llm_config, report_config=test_config.report_config)
                content_results: List[SubTestResult] = await content_test.run(page=page)

                result.sub_tests = content_results + [text_result]

                # Extract metrics
                content_statuses = [r.status for r in content_results]
                text_status = text_result.status

                # Determine overall status
                if text_status == 'passed' and all(status == 'passed' for status in content_statuses):
                    result.status = TestStatus.PASSED
                else:
                    result.status = TestStatus.FAILED

                    # Collect errors from all tests
                    all_results = content_results + [text_result]
                    errors = [r.messages['page'] for r in all_results if 'page' in r.messages]

                    if errors:
                        result.error_message = '; '.join(errors)

                logging.info(f"{icon['check']} Test completed: {test_config.test_name}")

            except Exception as e:
                error_msg = f'UX test failed: {str(e)}'
                result.status = TestStatus.FAILED
                result.error_message = error_msg
                logging.error(error_msg)
                raise

            return result


class LighthouseTestRunner(BaseTestRunner):
    """Runner for Lighthouse."""

    async def run_test(
        self, session: BrowserSession, test_config: TestConfiguration, llm_config: Dict[str, Any], target_url: str,
        session_pool=None  # Not used - Lighthouse manages its own Chrome instance
    ) -> TestResult:
        """Run Lighthouse tests."""

        with Display.display(test_config.test_name):
            result = TestResult(
                test_id=test_config.test_id,
                test_type=test_config.test_type,
                test_name=test_config.test_name,
                status=TestStatus.RUNNING,
                category=get_category_for_test_type(test_config.test_type),
            )

            try:
                logging.info(f"{icon['running']} Running test: {test_config.test_name}")
                # Get browser config from test_config instead of session (session is None for performance tests)
                browser_config = test_config.browser_config

                # Only run Lighthouse on Chromium browsers
                if browser_config.get('browser_type') != 'chromium':
                    logging.warning('Lighthouse tests require Chromium browser, skipping')
                    result.status = TestStatus.INCOMPLETED
                    result.results = {'skipped': 'Lighthouse requires Chromium browser'}
                    return result

                # Run Lighthouse test
                lighthouse_test = LighthouseMetricsTest(report_config=test_config.report_config)
                lighthouse_results: SubTestResult = await lighthouse_test.run(target_url, browser_config=browser_config)

                result.sub_tests = [lighthouse_results]
                result.status = lighthouse_results.status
                logging.info(f"{icon['check']} Test completed: {test_config.test_name}")

            except Exception as e:
                error_msg = f'Lighthouse test failed: {str(e)}'
                result.status = TestStatus.FAILED
                result.error_message = error_msg
                logging.error(error_msg)
                raise

            return result


class BasicTestRunner(BaseTestRunner):
    """Runner for Traversal tests."""

    async def run_test(
        self, session: BrowserSession, test_config: TestConfiguration, llm_config: Dict[str, Any], target_url: str,
        session_pool=None
    ) -> TestResult:
        """Run UX tests with enhanced screenshot and data collection."""

        with Display.display(test_config.test_name):
            result = TestResult(
                test_id=test_config.test_id,
                test_type=test_config.test_type,
                test_name=test_config.test_name,
                status=TestStatus.RUNNING,
                category=get_category_for_test_type(test_config.test_type),
            )

            try:
                logging.info(f"{icon['running']} Running test: {test_config.test_name}")
                page = session.page
                browser_config = session.browser_config

                # Discover clickable elements via crawler
                from webqa_agent.crawler.crawl import CrawlHandler

                crawler = CrawlHandler(target_url)
                clickable_elements = await crawler.clickable_elements_detection(page)
                logging.info(f'Crawled {len(clickable_elements)} clickable elements')
                if len(clickable_elements) > 50:
                    from itertools import islice
                    clickable_elements = dict(islice(clickable_elements.items(), 50))
                    logging.warning(f'Clickable elements number is too large, only keep the first 50')

                button_test = PageButtonTest(report_config=test_config.report_config)
                button_test_result = await button_test.run(
                    target_url, page=page, clickable_elements=clickable_elements, browser_config=browser_config
                )

                crawler = CrawlHandler(target_url)
                links = await crawler.extract_links(page)
                logging.info(f'Crawled {len(links)} links')
                # WebAccessibilityTest
                accessibility_test = WebAccessibilityTest(report_config=test_config.report_config)
                accessibility_result = await accessibility_test.run(target_url, links)


                # Combine test results into a list
                result.sub_tests = [button_test_result, accessibility_result]

                # Extract metrics
                button_status = button_test_result.status if button_test_result else TestStatus.FAILED
                accessibility_status = accessibility_result.status if accessibility_result else TestStatus.FAILED

                # Determine overall status
                if button_status == TestStatus.PASSED and accessibility_status == TestStatus.PASSED:
                    result.status = TestStatus.PASSED
                else:
                    result.status = TestStatus.FAILED

                    # Collect errors from all tests
                    all_results = [button_test_result, accessibility_result]
                    errors = [r.messages.get('page') for r in all_results if r and r.messages and 'page' in r.messages]

                    if errors:
                        result.error_message = '; '.join(errors)

                logging.info(f"{icon['check']} Test completed: {test_config.test_name}")

            except Exception as e:
                error_msg = f'Button test failed: {str(e)}'
                result.status = TestStatus.FAILED
                result.error_message = error_msg
                logging.error(error_msg)
                raise

            return result

# class ButtonTestRunner(BaseTestRunner):
#     """Runner dedicated to button click tests."""

#     async def run_test(
#         self, session: BrowserSession, test_config: TestConfiguration, llm_config: Dict[str, Any], target_url: str
#     ) -> TestResult:
#         """Run Button test."""

#         with Display.display(test_config.test_name):
#             result = TestResult(
#                 test_id=test_config.test_id,
#                 test_type=test_config.test_type,
#                 test_name=test_config.test_name,
#                 status=TestStatus.RUNNING,
#                 category=get_category_for_test_type(test_config.test_type),
#             )

#             try:
#                 logging.info(f"{icon['running']} Running test: {test_config.test_name}")
#                 page = session.page
#                 browser_config = session.browser_config

#                 # Discover clickable elements via crawler
#                 from webqa_agent.crawler.crawl import CrawlHandler

#                 crawler = CrawlHandler(target_url)
#                 clickable_elements = await crawler.clickable_elements_detection(page)
#                 logging.info(f'Crawled {len(clickable_elements)} clickable elements')
#                 if len(clickable_elements) > 50:
#                     from itertools import islice
#                     clickable_elements = dict(islice(clickable_elements.items(), 50))
#                     logging.warning(f'Clickable elements number is too large, only keep the first 50')

#                 button_test = PageButtonTest()
#                 button_test_result = await button_test.run(
#                     target_url, page=page, clickable_elements=clickable_elements, browser_config=browser_config
#                 )

#                 # Second subtest: each clickable result? keep detailed reports if needed; here we only include traverse test
#                 result.sub_tests = [button_test_result]

#                 # Overall metrics/status
#                 result.status = button_test_result.status

#                 logging.info(f"{icon['check']} Test completed: {test_config.test_name}")

#             except Exception as e:
#                 error_msg = f'Button test failed: {str(e)}'
#                 result.status = TestStatus.FAILED
#                 result.error_message = error_msg
#                 logging.error(error_msg)
#                 raise

#             return result


# class WebBasicCheckRunner(BaseTestRunner):
#     """Runner for Web Basic Check tests."""

#     async def run_test(
#         self, session: BrowserSession, test_config: TestConfiguration, llm_config: Dict[str, Any], target_url: str
#     ) -> TestResult:
#         """Run Web Basic Check tests."""

#         with Display.display(test_config.test_name):
#             result = TestResult(
#                 test_id=test_config.test_id,
#                 test_type=test_config.test_type,
#                 test_name=test_config.test_name,
#                 status=TestStatus.RUNNING,
#                 category=get_category_for_test_type(test_config.test_type),
#             )

#             try:
#                 logging.info(f"{icon['running']} Running test: {test_config.test_name}")
#                 page = session.page

#                 # Discover page elements
#                 from webqa_agent.crawler.crawl import CrawlHandler

#                 crawler = CrawlHandler(target_url)
#                 links = await crawler.extract_links(page)
#                 logging.info(f'Crawled {len(links)} links')
#                 # WebAccessibilityTest
#                 accessibility_test = WebAccessibilityTest(self.llm_config, report_config=self.report_config)
#                 accessibility_result = await accessibility_test.run(target_url, links)

#                 result.sub_tests = [accessibility_result]
#                 result.status = accessibility_result.status
#                 logging.info(f"{icon['check']} Test completed: {test_config.test_name}")

#             except Exception as e:
#                 error_msg = f'Web Basic Check test failed: {str(e)}'
#                 result.status = TestStatus.FAILED
#                 result.error_message = error_msg
#                 logging.error(error_msg)
#                 raise

#             return result

class SecurityTestRunner(BaseTestRunner):
    """Runner for Security tests using Nuclei-based scanning."""

    def __init__(self):
        super().__init__()
        self.language = 'zh-CN'  # Default language
        self.localized_strings = {
            'zh-CN': i18n.get_lang_data('zh-CN').get('testers', {}).get('security', {}),
            'en-US': i18n.get_lang_data('en-US').get('testers', {}).get('security', {}),
        }

    def _get_text(self, key: str) -> str:
        """Get localized text for the current language."""
        return self.localized_strings.get(self.language, {}).get(key, key)

    def get_scan_tags(self, language: str) -> Dict[str, str]:
        """Get scan tags with localized descriptions."""
        return {
            'cve': self._get_text('cve_scan'),
            'xss': self._get_text('xss_scan'),
            'sqli': self._get_text('sqli_scan'),
            'rce': self._get_text('rce_scan'),
            'lfi': self._get_text('lfi_scan'),
            'ssrf': self._get_text('ssrf_scan'),
            'redirect': self._get_text('redirect_scan'),
            'exposure': self._get_text('exposure_scan'),
            'config': self._get_text('config_scan'),
            'default-login': self._get_text('default_login_scan'),
            'ssl': self._get_text('ssl_scan'),
            'dns': self._get_text('dns_scan'),
            'subdomain-takeover': self._get_text('subdomain_takeover_scan'),
            'tech': self._get_text('tech_scan'),
            'panel': self._get_text('panel_scan'),
        }

    def get_protocol_scans(self, language: str) -> Dict[str, str]:
        """Get protocol scans with localized descriptions."""
        return {
            'http': self._get_text('http_protocol'),
            'dns': self._get_text('dns_protocol'),
            'tcp': self._get_text('tcp_protocol'),
            'ssl': self._get_text('ssl_protocol'),
        }

    async def run_test(
        self, session: BrowserSession, test_config: TestConfiguration, llm_config: Dict[str, Any], target_url: str,
        session_pool=None  # Not used - Nuclei manages its own scanning
    ) -> TestResult:
        """Run Security tests using Nuclei scanning."""

        self.language = test_config.report_config.get('language', 'zh-CN')
        with Display.display(test_config.test_name):
            result = TestResult(
                test_id=test_config.test_id,
                test_type=test_config.test_type,
                test_name=test_config.test_name,
                status=TestStatus.RUNNING,
                category=get_category_for_test_type(test_config.test_type),
            )

            try:
                # 安全测试不需要浏览器会话，使用Nuclei进行独立扫描
                logging.info(f"{icon['running']} Running test: {test_config.test_name}")

                # 检查nuclei是否安装
                nuclei_available = await self._check_nuclei_available()

                if not nuclei_available:
                    result.status = TestStatus.FAILED
                    result.error_message = self._get_text('nuclei_not_found')
                    return result

                # 执行安全扫描
                scan_results = await self._run_security_scan(target_url, test_config)

                # 处理扫描结果
                findings = await self._process_scan_results(scan_results)

                # 生成子测试结果
                sub_tests = []

                # 按严重程度分类结果
                severity_counts = {}
                finding_details = []

                for finding in findings:
                    severity = finding.get('info', {}).get('severity', 'unknown')
                    severity_counts[severity] = severity_counts.get(severity, 0) + 1
                    finding_details.append(
                        {
                            'template_id': finding.get('template-id', 'unknown'),
                            'name': finding.get('info', {}).get('name', 'Unknown'),
                            'severity': severity,
                            'description': finding.get('info', {}).get('description', ''),
                            'matched_at': finding.get('matched-at', ''),
                            'extracted_results': finding.get('extracted-results', []),
                        }
                    )

                # 创建按严重程度的子测试
                for severity in ['critical', 'high', 'medium', 'low', 'info']:
                    count = severity_counts.get(severity, 0)

                    # 获取该严重程度的具体发现
                    severity_findings = [f for f in finding_details if f.get('severity') == severity]

                    # 构建报告内容
                    if count == 0:
                        issues_text = self._get_text('no_severity_issues').format(severity=severity.upper())
                    else:
                        # 取前3个问题的名称作为示例
                        sample_issues = [f['name'] for f in severity_findings[:3]]
                        issues_text = self._get_text('found_severity_issues').format(count=count, severity=severity.upper())
                        if sample_issues:
                            issues_text += f": {', '.join(sample_issues)}"
                            if count > 3:
                                issues_text += f" {self._get_text('and_more')}"

                    sub_tests.append(
                        SubTestResult(
                            name=self._get_text('severity_level_scan').format(severity=severity.upper()),
                            status=TestStatus.PASSED,
                            metrics={'findings_count': count},
                            report=[SubTestReport(
                                title=self._get_text('severity_level_vulnerability').format(severity=severity.upper()),
                                issues=issues_text
                            )],
                        )
                    )

                # 创建扫描类型的子测试
                scan_tags = self.get_scan_tags(self.language)
                protocol_scans = self.get_protocol_scans(self.language)
                for scan_type, description in {**scan_tags, **protocol_scans}.items():
                    type_findings = [f for f in finding_details if scan_type in f.get('template_id', '').lower()]
                    type_count = len(type_findings)

                    # 构建扫描类型报告内容
                    if type_count == 0:
                        issues_text = f"{description}: {self._get_text('no_security_issues')}"
                    else:
                        # 按严重程度统计该类型的发现
                        type_severity_counts = {}
                        for finding in type_findings:
                            severity = finding.get('severity', 'unknown')
                            type_severity_counts[severity] = type_severity_counts.get(severity, 0) + 1

                        severity_summary = []
                        for sev in ['critical', 'high', 'medium', 'low', 'info']:
                            if type_severity_counts.get(sev, 0) > 0:
                                severity_summary.append(f"{sev.upper()} {i18n.t(self.language, 'common.level', 'level')} {type_severity_counts[sev]} {i18n.t(self.language, 'common.issues', 'issues')}")

                        issues_text = f"{description}: {self._get_text('found_issues').format(count=type_count)}"
                        if severity_summary:
                            issues_text += f" ({', '.join(severity_summary)})"

                        # 添加具体问题示例（最多3个）
                        if type_findings:
                            sample_names = [f['name'] for f in type_findings[:2]]
                            if sample_names:
                                issues_text += f", {self._get_text('including')}: {', '.join(sample_names)}"
                                if type_count > 2:
                                    issues_text += f" {self._get_text('and_more')}"

                    combined_reports = []
                    if not finding_details:
                        # No security issues found
                        combined_reports.append(SubTestReport(
                            title=self._get_text('security_check'),
                            issues=self._get_text('no_issues_found')
                        ))
                    else:
                        for fd in finding_details:
                            title = f"[{fd.get('severity', 'unknown').upper()}] {fd.get('name')}"
                            details_parts = []
                            if fd.get('description'):
                                details_parts.append(fd['description'])
                            if fd.get('matched_at'):
                                details_parts.append(f"{self._get_text('matched_at')}: {fd['matched_at']}")
                            if fd.get('extracted_results'):
                                details_parts.append(f"{self._get_text('extracted')}: {', '.join(map(str, fd['extracted_results']))}")
                            issues_text = ' | '.join(details_parts) if details_parts else self._get_text('no_details')
                            combined_reports.append(SubTestReport(title=title, issues=issues_text))

                    sub_tests = [
                        SubTestResult(
                            name=self._get_text('nuclei_check'),
                            status=TestStatus.PASSED,
                            metrics={
                                'total_findings': len(finding_details),
                                **severity_counts
                            },
                            report=combined_reports
                        )
                    ]

                    result.sub_tests = sub_tests
                result.status = TestStatus.PASSED

                # 添加总体指标
                total_findings = len(findings)
                critical_findings = severity_counts.get('critical', 0)
                high_findings = severity_counts.get('high', 0)

                result.add_metric('total_findings', total_findings)
                result.add_metric('critical_findings', critical_findings)
                result.add_metric('high_findings', high_findings)
                result.add_metric('security_score', max(0, 100 - (critical_findings * 20 + high_findings * 10)))

                # 添加详细结果
                result.add_data('security_findings', finding_details)
                result.add_data('severity_summary', severity_counts)

                # 清理临时文件
                await self._cleanup_temp_files(scan_results.get('output_path'))

                logging.info(f"{icon['check']} Test completed: {test_config.test_name}")

            except Exception as e:
                error_msg = f'Security test failed: {str(e)}'
                logging.error(error_msg)
                result.status = TestStatus.FAILED
                result.error_message = error_msg

                # 即使失败也要清理临时文件
                try:
                    scan_results = locals().get('scan_results', {})
                    await self._cleanup_temp_files(scan_results.get('output_path'))
                except:
                    pass

            return result

    async def _check_nuclei_available(self) -> bool:
        """检查nuclei工具是否可用."""
        try:
            process = await asyncio.create_subprocess_exec(
                'nuclei', '-version', stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
            )
            stdout, stderr = await process.communicate()
            logging.debug(f'Nuclei check - return code: {process.returncode}')
            logging.debug(f'Nuclei check - stdout: {stdout.decode()}')
            logging.debug(f'Nuclei check - stderr: {stderr.decode()}')
            return process.returncode == 0
        except Exception as e:
            logging.error(f'Error checking nuclei availability: {e}')
            return False

    async def _run_security_scan(self, target_url: str, test_config: TestConfiguration) -> Dict[str, Any]:
        """执行安全扫描."""
        # 创建临时输出目录，使用测试ID确保唯一性
        import tempfile

        temp_dir = Path(tempfile.gettempdir()) / 'webqa_agent_security' / test_config.test_id
        temp_dir.mkdir(parents=True, exist_ok=True)

        # 配置扫描任务
        scan_configs = {'tag': self.get_scan_tags(self.language), 'protocol': self.get_protocol_scans(self.language)}

        # 从测试配置中获取自定义参数
        custom_config = test_config.test_specific_config or {}
        include_severity_scans = custom_config.get('include_severity_scans', True)

        if include_severity_scans:
            scan_configs['severity'] = {
                'critical': self._get_text('critical_vulnerability'),
                'high': self._get_text('high_risk_vulnerability'),
                'medium': self._get_text('medium_risk_vulnerability')
            }

        # 执行并行扫描
        scan_results = await self._execute_scan_batch(target_url, scan_configs, temp_dir)

        return {'scan_results': scan_results, 'output_path': str(temp_dir)}

    async def _execute_scan_batch(self, target_url: str, scan_configs: Dict[str, Dict], output_path: Path) -> list:
        """并行执行一批安全扫描."""
        tasks = []

        # 创建扫描任务
        for scan_type, scans in scan_configs.items():
            for scan_name, description in scans.items():
                output_file = output_path / f'{scan_type}_{scan_name}_{int(time.time())}.json'
                task = self._run_nuclei_command(target_url, scan_type, scan_name, output_file)
                tasks.append(task)

        # 并行执行所有扫描
        logging.info(f'Start {len(tasks)} security scan tasks...')
        scan_results = await asyncio.gather(*tasks, return_exceptions=True)

        # 处理结果
        results = []
        for result in scan_results:
            if isinstance(result, Exception):
                logging.error(f'Scan task failed: {result}')
                continue
            results.append(result)

        return results

    async def _run_nuclei_command(
        self, target_url: str, scan_type: str, scan_name: str, output_file: Path
    ) -> Dict[str, Any]:
        """运行单个Nuclei扫描命令."""
        cmd = ['nuclei', '-target', target_url, '-json-export', str(output_file), '-silent']

        # 根据扫描类型添加参数
        if scan_type == 'tag':
            cmd.extend(['-tags', scan_name])
        elif scan_type == 'protocol':
            cmd.extend(['-type', scan_name])
        elif scan_type == 'severity':
            cmd.extend(['-severity', scan_name])

        try:
            process = await asyncio.create_subprocess_exec(
                *cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
            )

            stdout, stderr = await process.communicate()

            return {
                'scan_name': scan_name,
                'scan_type': scan_type,
                'stdout': stdout.decode() if stdout else '',
                'stderr': stderr.decode() if stderr else '',
                'returncode': process.returncode,
                'output_file': str(output_file),
            }
        except Exception as e:
            return {
                'scan_name': scan_name,
                'scan_type': scan_type,
                'stdout': '',
                'stderr': str(e),
                'returncode': 1,
                'output_file': str(output_file),
            }

    async def _process_scan_results(self, scan_results: Dict[str, Any]) -> list:
        """读取并合并所有扫描结果."""
        all_results = []
        output_path = Path(scan_results['output_path'])
        json_files = list(output_path.glob('*.json'))

        for json_file in json_files:
            try:
                with open(json_file, 'r', encoding='utf-8') as f:
                    content = f.read().strip()
                    if content:
                        # 处理JSONL格式（每行一个JSON对象）
                        for line in content.split('\n'):
                            if line.strip():
                                try:
                                    result = json.loads(line)
                                    if isinstance(result, dict):
                                        all_results.append(result)
                                    elif isinstance(result, list):
                                        for item in result:
                                            if isinstance(item, dict):
                                                all_results.append(item)
                                except json.JSONDecodeError:
                                    continue
            except Exception as e:
                logging.error(f'Failed to read result file {json_file}: {e}')

        return all_results

    async def _cleanup_temp_files(self, temp_path: str):
        """清理临时扫描文件."""
        if not temp_path:
            return

        try:
            import shutil

            temp_dir = Path(temp_path)
            if temp_dir.exists() and temp_dir.is_dir():
                shutil.rmtree(temp_dir)
                logging.debug(f'Cleaned up temporary security scan files: {temp_path}')
        except Exception as e:
            logging.warning(f'Failed to cleanup temporary files at {temp_path}: {e}')
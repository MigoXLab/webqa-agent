"""Gen mode executor for AI-driven test generation and execution."""

import logging
import os
import uuid
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

from webqa_agent.actions.action_handler import ActionHandler
from webqa_agent.browser import BrowserSessionPool
from webqa_agent.config_models.gen_config import GenConfig
from webqa_agent.data import (ParallelTestSession, SubTestReport,
                              SubTestResult, SubTestScreenshot, SubTestStep,
                              TestCategory, TestResult, TestStatus)
from webqa_agent.executor.gen.utils.case_recorder import get_report_summary
from webqa_agent.executor.result_aggregator import ResultAggregator
from webqa_agent.utils.data_flow_reporter import (generate_data_flow_report,
                                                    set_dataflow_enabled)
from webqa_agent.utils import Display, i18n
from webqa_agent.utils.get_log import GetLog
from webqa_agent.utils.log_icon import icon
from webqa_agent.utils.reporting_utils import save_index_json

logger = logging.getLogger(__name__)


class GenExecutor:
    """Gen mode executor (AI-driven test generation and execution).

    Replaces ParallelMode with simplified config-based execution.
    Directly interfaces with LangGraph workflow for test generation.

    Usage:
        config = GenConfig(...)
        executor = GenExecutor(config)
        results = await executor.execute()
    """

    def __init__(self, config: GenConfig):
        """Initialize GenExecutor with configuration.

        Args:
            config: GenConfig instance with all settings
        """
        self.config = config
        self.result_aggregator = ResultAggregator(config.report_config.model_dump())
        self.session_pool: Optional[BrowserSessionPool] = None

        # Apply dataflow toggle from report config
        set_dataflow_enabled(config.report_config.save_dataflow)

    async def execute(self) -> Tuple[Dict[str, Any], str, str, Dict[str, int]]:
        """Execute gen mode workflow.

        Returns:
            Tuple of (aggregated_results, report_path, html_path, result_count)
        """
        test_session: Optional[ParallelTestSession] = None
        completed_session: Optional[ParallelTestSession] = None
        aggregated_data = None
        html_path = None
        run_error: Optional[Exception] = None
        result = {'total': 0, 'passed': 0, 'failed': 0, 'warning': 0}
        custom_report_dir: Optional[str] = None

        try:
            # Initialize logging and display
            GetLog.get_log(log_level=self.config.log_config.level)
            Display.init(language=self.config.report_config.language)
            Display.display.start()

            logger.info(
                f"{icon['rocket']} Starting gen mode for URL: {self.config.target_url}"
            )

            # Create test session
            test_session = ParallelTestSession(
                session_id=str(uuid.uuid4()),
                target_url=self.config.target_url,
                llm_config=self.config.llm_config.model_dump()
            )

            # Setup report directory
            report_ts = datetime.now().strftime('%Y-%m-%d_%H-%M-%S_%f')
            os.environ['WEBQA_REPORT_TIMESTAMP'] = report_ts

            # Initialize browser session pool (CRITICAL for LangGraph)
            logger.info(f'🌊 Initializing browser session pool (size={self.config.max_concurrent_tests})')
            self.session_pool = BrowserSessionPool(
                pool_size=self.config.max_concurrent_tests,
                browser_config=self.config.browser_config.model_dump()
            )

            # Initialize screenshot directory
            ActionHandler.clear_screenshot_session()

            # Determine report directory
            custom_report_dir = self.config.report_config.report_dir
            if not custom_report_dir or (isinstance(custom_report_dir, str) and custom_report_dir.strip() == ''):
                custom_report_dir = os.path.join('reports', f'test_{report_ts}')

            test_session.report_path = custom_report_dir

            # Start session timing (CRITICAL: must be called before save_index_json)
            test_session.start_session()

            # Configure screenshot saving
            ActionHandler.set_screenshot_config(
                save_screenshots=self.config.report_config.save_screenshots
            )
            ActionHandler.init_screenshot_session(custom_report_dir=custom_report_dir)
            logger.info(f'📸 Screenshot directory initialized for report: {custom_report_dir}')

            # Initialize index.json
            initial_result_count = {'total': 1, 'passed': 0, 'failed': 0, 'warning': 0}
            save_index_json(
                test_session=test_session,
                report_dir=custom_report_dir,
                result_count=initial_result_count,
                llm_config=self.config.llm_config.model_dump(),
                browser_config=self.config.browser_config.model_dump(),
                report_lang=self.config.report_config.language,
                mode='gen'
            )

            # Run LangGraph workflow (AI test generation + execution)
            test_result = await self._run_langgraph_workflow(custom_report_dir)

            # Add result to session
            test_session.test_results[test_result.test_id] = test_result

            # Calculate result statistics from sub-tests
            test_results = [test_result]
            result = ResultAggregator.compute_counts_from_tests(test_results)

            # LLM summary disabled — output was hard to read and added noise to reports
            test_session.llm_summary = ''

            # Complete session BEFORE saving to ensure end_time is recorded
            test_session.complete_session()
            completed_session = test_session

            # Final update of index.json (now includes end_time)
            save_index_json(
                test_session=test_session,
                report_dir=custom_report_dir,
                result_count=result,
                test_results=test_results,
                llm_config=self.config.llm_config.model_dump(),
                browser_config=self.config.browser_config.model_dump(),
                report_lang=self.config.report_config.language,
                mode='gen'
            )

        except BaseException as e:
            logger.error(f'Error in gen executor: {e}')
            run_error = e

        finally:
            # Ensure session end_time is recorded even on exception
            try:
                if test_session and not test_session.end_time:
                    test_session.complete_session()
                    logger.info('Session end_time recorded in finally block')
                    # Persist end_time to index.json on exception path
                    if custom_report_dir:
                        save_index_json(
                            test_session=test_session,
                            report_dir=custom_report_dir,
                            result_count=result,
                            llm_config=self.config.llm_config.model_dump(),
                            browser_config=self.config.browser_config.model_dump(),
                            report_lang=self.config.report_config.language,
                            mode='gen'
                        )
                        logger.info('index.json updated with end_time in finally block')
            except Exception as session_err:
                logger.warning(f'Failed to complete session: {session_err}')

            # Cleanup browser session pool (CRITICAL)
            try:
                if self.session_pool:
                    logger.info('🌊 Closing browser session pool...')
                    await self.session_pool.close_all()
                    logger.info('✅ Browser session pool closed')
            except Exception as pool_err:
                logger.warning(f'Failed to close session pool: {pool_err}')

            try:
                # Aggregate and generate reports
                if custom_report_dir:
                    if aggregated_data is None:
                        aggregated_data, _ = self.result_aggregator.aggregate_report_json(
                            'gen', custom_report_dir
                        )

                    if completed_session is None:
                        completed_session = test_session
                    if completed_session is None:
                        completed_session = ParallelTestSession(
                            session_id=str(uuid.uuid4()),
                            target_url=self.config.target_url,
                            llm_config=self.config.llm_config.model_dump()
                        )

                    if html_path is None:
                        html_path = self.result_aggregator.generate_html_report_fully_inlined(
                            completed_session,
                            report_dir=custom_report_dir,
                            aggregated_data=aggregated_data
                        )
                        completed_session.html_report_path = html_path

                    # Cleanup tmp only when run succeeded
                    has_results = bool(
                        aggregated_data and any(k != 'index' for k in aggregated_data.get('gen', {}))
                    )
                    if run_error is None and has_results:
                        self.result_aggregator.cleanup_tmp_dir(custom_report_dir)

            except Exception as agg_err:
                logger.warning(f'Failed to aggregate/generate report: {agg_err}')

            # Render data flow interactive gantt from captured JSONL events.
            if custom_report_dir and self.config.report_config.save_dataflow:
                try:
                    generate_data_flow_report(custom_report_dir)
                except Exception as dataflow_err:
                    logger.warning(f'Failed to generate data flow report: {dataflow_err}')

            # Cleanup Display
            try:
                await Display.display.stop()
                Display.display.render_summary()
            except Exception as display_err:
                logger.warning(f'Failed to stop display: {display_err}')

        if run_error:
            raise run_error

        if test_session is None:
            test_session = ParallelTestSession(
                session_id=str(uuid.uuid4()),
                target_url=self.config.target_url,
                llm_config=self.config.llm_config.model_dump()
            )
            test_session.report_path = custom_report_dir or ''

        return (
            test_session.aggregated_results,
            test_session.report_path,
            test_session.html_report_path,
            result
        )

    async def _run_langgraph_workflow(self, report_dir: str) -> TestResult:
        """Run LangGraph workflow for AI test generation.

        Args:
            report_dir: Active report directory used by data flow instrumentation.

        Returns:
            TestResult from LangGraph execution
        """
        from webqa_agent.executor.gen.graph import app

        # Get enabled custom tools
        enabled_custom_tools = self.config.custom_tools.enabled

        # Build state for LangGraph
        initial_state = {
            # Core configuration
            'url': self.config.target_url,
            'business_objectives': self.config.business_objectives,
            'cookies': self.config.browser_config.cookies,
            'language': self.config.report_config.language,

            # Test data
            'test_cases': [],  # Will be populated by plan_test_cases
            'completed_cases': [],
            'recorded_cases': [],

            # Control flags
            'generate_only': False,
            'skip_reflection': self.config.skip_reflection,

            # Feature configuration
            'dynamic_step_generation': self.config.dynamic_step_generation.model_dump(),
            'enabled_custom_tools': enabled_custom_tools,  # Pass to LangGraph

            # Infrastructure (CRITICAL: session_pool required by LangGraph)
            'session_pool': self.session_pool,  # BrowserSessionPool instance
            'llm_config': self.config.llm_config.model_dump(),
            'browser_config': self.config.browser_config.model_dump(),
            'report_config': {
                **self.config.report_config.model_dump(),
                'report_dir': report_dir,
            },
        }

        graph_config = {'recursion_limit': 100}

        # Execute LangGraph workflow
        logger.info('Starting LangGraph workflow for test generation...')
        final_state = await app.ainvoke(initial_state, config=graph_config)

        # Extract recorded cases from final state
        recorded_cases = final_state.get('recorded_cases', [])
        planning_error = final_state.get('planning_error')
        logger.info(f'Retrieved {len(recorded_cases)} recorded cases from LangGraph')

        # Extract completed cases for status mapping (keyed by case_id to avoid
        # name collisions when multiple cases share the same display name)
        completed_cases = final_state.get('completed_cases', [])
        graph_case_status_map: Dict[str, str] = {}
        for case_res in completed_cases:
            cid = case_res.get('case_id', '')
            if cid:
                graph_case_status_map[cid] = case_res.get('status', 'failed').lower()

        # Convert recorded_cases to SubTestResult list
        sub_tests = self._convert_recorded_cases_to_sub_tests(recorded_cases, graph_case_status_map)

        # Create TestResult
        lang = self.config.report_config.language
        test_result = TestResult(
            test_id=str(uuid.uuid4()),
            test_name=i18n.t(lang, 'tools.ai_function.display_text', 'Gen Mode'),
            category=TestCategory.FUNCTION,
            sub_tests=sub_tests
        )

        # Calculate metrics
        if recorded_cases:
            total_cases = len(recorded_cases)
            passed_cases = sum(
                1 for case in recorded_cases
                if case.get('status', '').lower() in ['passed', 'completed']
            )
            failed_cases = total_cases - passed_cases
            total_steps = sum(
                (case.get('metrics', {}) or {}).get('total_steps', len(case.get('steps', [])))
                for case in recorded_cases
            )
            success_rate = (passed_cases / total_cases * 100) if total_cases > 0 else 0

            test_result.add_metric('test_case_count', total_cases)
            test_result.add_metric('passed_test_cases', passed_cases)
            test_result.add_metric('failed_test_cases', failed_cases)
            test_result.add_metric('total_steps', total_steps)
            test_result.add_metric('success_rate', success_rate)

            # Set overall status
            if failed_cases == 0:
                test_result.status = TestStatus.PASSED
            else:
                test_result.status = TestStatus.FAILED
                test_result.error_message = f'{failed_cases} out of {total_cases} test cases failed'
        else:
            if planning_error:
                logger.error(f'Test planning failed: {planning_error}')
                test_result.status = TestStatus.FAILED
                test_result.error_message = f'Test planning failed: {planning_error}'
            else:
                logger.error('No recorded_cases data found in LangGraph state')
                test_result.status = TestStatus.FAILED
                test_result.error_message = 'No test cases were executed'

        return test_result

    def _convert_recorded_cases_to_sub_tests(
        self,
        recorded_cases: List[Dict[str, Any]],
        graph_case_status_map: Dict[str, str]
    ) -> List[SubTestResult]:
        """Convert LangGraph recorded_cases to SubTestResult list.

        Args:
            recorded_cases: List of recorded case dictionaries from LangGraph
            graph_case_status_map: Mapping of case_id to status strings

        Returns:
            List of SubTestResult instances
        """
        sub_tests = []

        for recorded_case in recorded_cases:
            case_name = recorded_case.get(
                'name',
                f"Unnamed test case - {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
            )
            case_steps_raw = recorded_case.get('steps', []) or []

            # Convert steps
            case_steps: List[SubTestStep] = []
            for step_data in case_steps_raw:
                screenshots = self._convert_screenshots(step_data)

                step_status = self._parse_step_status(step_data.get('status', 'passed'))

                case_steps.append(SubTestStep(
                    id=step_data.get('id', 0),
                    description=step_data.get('description', ''),
                    screenshots=screenshots,
                    modelIO=step_data.get('modelIO', ''),
                    actions=step_data.get('actions', []),
                    status=step_status,
                    errors=step_data.get('error', ''),
                    error_details=step_data.get('error_details'),
                ))

            # Get case status (use case_id for lookup to avoid name collision)
            case_status_str = recorded_case.get('status', 'failed').lower()
            recorded_case_id = recorded_case.get('case_id', '')
            if recorded_case_id and recorded_case_id in graph_case_status_map:
                case_status_str = graph_case_status_map[recorded_case_id]

            status_enum = self._parse_case_status(case_status_str)

            # Build reports
            reports = []
            report_summary = get_report_summary(recorded_case)
            if report_summary:
                reports.append(SubTestReport(
                    title='Summary',
                    issues=report_summary
                ))

            # Extract metrics
            case_metrics = recorded_case.get('metrics') or {}
            if not case_metrics:
                case_metrics = {'total_steps': len(case_steps)}
            else:
                case_metrics.setdefault('total_steps', len(case_steps))

            sub_tests.append(
                SubTestResult(
                    sub_test_id=recorded_case.get('case_id', ''),
                    name=case_name,
                    status=status_enum,
                    metrics=case_metrics,
                    steps=case_steps,
                    messages={},
                    start_time=recorded_case.get('start_time'),
                    end_time=recorded_case.get('end_time'),
                    final_summary=recorded_case.get('final_summary', ''),
                    user_summary=recorded_case.get('user_summary', ''),
                    report=reports,
                )
            )

        return sub_tests

    def _convert_screenshots(self, step_data: Dict[str, Any]) -> List[SubTestScreenshot]:
        """Convert step screenshots to SubTestScreenshot list."""
        screenshots = []

        # Check both screenshots_paths and screenshots fields
        screenshot_sources = step_data.get('screenshots_paths') or step_data.get('screenshots', [])

        for scr in screenshot_sources:
            sc = self._to_screenshot(scr)
            if sc:
                screenshots.append(sc)

        return screenshots

    def _to_screenshot(self, scr: Any) -> Optional[SubTestScreenshot]:
        """Convert screenshot data to SubTestScreenshot."""
        if isinstance(scr, str):
            return SubTestScreenshot(type='path', data=scr, label=None)

        if not isinstance(scr, dict):
            return None

        data = scr.get('data') or scr.get('path') or scr.get('oss_url') or ''
        if isinstance(data, str) and data.startswith('data:image'):
            # Discard base64, prefer path or URL
            data = scr.get('path') or scr.get('oss_url') or ''

        return SubTestScreenshot(
            type=scr.get('type', 'path'),
            data=data,
            label=scr.get('label')
        )

    def _parse_step_status(self, status_str: str) -> TestStatus:
        """Parse step status string to TestStatus enum."""
        status_lower = status_str.lower()
        if status_lower in ['failed', 'error', 'failure']:
            return TestStatus.FAILED
        elif status_lower in ['warning', 'warn']:
            return TestStatus.WARNING
        else:
            return TestStatus.PASSED

    def _parse_case_status(self, status_str: str) -> TestStatus:
        """Parse case status string to TestStatus enum."""
        status_mapping = {
            'pending': TestStatus.PENDING,
            'running': TestStatus.RUNNING,
            'passed': TestStatus.PASSED,
            'completed': TestStatus.PASSED,
            'warning': TestStatus.WARNING,
            'failed': TestStatus.FAILED,
            'cancelled': TestStatus.CANCELLED,
        }
        return status_mapping.get(status_str, TestStatus.FAILED)

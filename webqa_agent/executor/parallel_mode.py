import logging
import os
import uuid
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

from webqa_agent.actions.action_handler import ActionHandler
from webqa_agent.browser.config import DEFAULT_CONFIG
from webqa_agent.data import (ParallelTestSession, TestConfiguration, TestType,
                              get_default_test_name)
from webqa_agent.executor import ParallelTestExecutor
from webqa_agent.executor.result_aggregator import ResultAggregator
from webqa_agent.utils import Display
from webqa_agent.utils.get_log import GetLog
from webqa_agent.utils.log_icon import icon
from webqa_agent.utils.reporting_utils import save_index_json


class ParallelMode:
    """Parallel test mode - runs tests concurrently with data isolation"""

    def __init__(self, tests: List, max_concurrent_tests: int = 4):
        self.max_concurrent_tests = max_concurrent_tests
        self.executor = ParallelTestExecutor(max_concurrent_tests)

    async def run(
        self,
        url: str,
        llm_config: Dict[str, Any],
        browser_config: Optional[Dict[str, Any]] = None,
        test_configurations: Optional[List[Dict[str, Any]]] = None,
        log_cfg: Optional[Dict[str, Any]] = None,
        report_cfg: Optional[Dict[str, Any]] = None
    ) -> Tuple[Dict[str, Any], str, str, Dict[str, Any]]:
        """Run tests in parallel mode with configurable test types.

        Args:
            url: Target URL to test
            llm_config: Configuration for language models
            browser_config: Default browser configuration
            test_configurations: Custom test configurations for parallel execution
            log_cfg: Configuration for logger
            report_cfg: Configuration for report

        Returns:
            Tuple of (aggregated_results, report_path)
        """
        test_session: Optional[ParallelTestSession] = None
        completed_session: Optional[ParallelTestSession] = None
        aggregated_data = None
        html_path = None
        run_error: Exception | None = None
        result = {'total': 0, 'passed': 0, 'failed': 0, 'warning': 0}
        custom_report_dir: Optional[str] = None
        try:
            # Use default config if none provided
            if not log_cfg:
                log_cfg = {'level': 'info'}
            if not report_cfg:
                report_cfg = {'language': 'en-US'}

            GetLog.get_log(log_level=log_cfg.get('level', 'info'))
            Display.init(language=report_cfg.get('language', 'en-US'))
            Display.display.start()

            logging.info(f"{icon['rocket']} Starting tests for URL: {url}, parallel mode {self.max_concurrent_tests}")

            # Use default config if none provided
            if not browser_config:
                browser_config = DEFAULT_CONFIG.copy()

            # Create test session
            test_session = ParallelTestSession(session_id=str(uuid.uuid4()), target_url=url, llm_config=llm_config)

            # Use a fresh per-task timestamp for reports and keep logs separate
            report_ts = datetime.now().strftime('%Y-%m-%d_%H-%M-%S_%f')
            os.environ['WEBQA_REPORT_TIMESTAMP'] = report_ts

            # Initialize screenshot directory for this test session
            # Clear any existing session state to ensure isolation
            ActionHandler.clear_screenshot_session()

            # Use report_cfg to determine report directory, update it if missing
            custom_report_dir = report_cfg.get('report_dir')
            # Handle null, None, empty string, or missing value
            if not custom_report_dir or (isinstance(custom_report_dir, str) and custom_report_dir.strip() == ''):
                # Use default reports/test_{timestamp}/ directory
                custom_report_dir = os.path.join('reports', f'test_{report_ts}')
                report_cfg['report_dir'] = custom_report_dir

            test_session.report_path = custom_report_dir

            # Configure screenshot saving behavior
            save_screenshots = report_cfg.get('save_screenshots', False)
            ActionHandler.set_screenshot_config(save_screenshots=save_screenshots)

            ActionHandler.init_screenshot_session(custom_report_dir=custom_report_dir)
            logging.info(f'📸 Screenshot directory initialized for report: {custom_report_dir}')

            # Initialize index.json at start
            initial_result_count = {'total': 0, 'passed': 0, 'failed': 0, 'warning': 0}
            if test_configurations:
                initial_result_count['total'] = len(test_configurations)

            save_index_json(
                test_session=test_session,
                report_dir=custom_report_dir,
                result_count=initial_result_count,
                llm_config=llm_config,
                browser_config=browser_config,
                report_lang=report_cfg.get('language', 'zh-CN'),
                mode='gen'
            )

            # Configure tests based on input or legacy test objects
            if test_configurations:
                self._configure_tests_from_config(test_session, test_configurations, browser_config, report_cfg)

            # Execute tests in parallel
            completed_session = await self.executor.execute_parallel_tests(test_session)

            # Calculate result statistics (count by sub-tests for gen mode) using shared aggregator logic
            test_results = list(completed_session.test_results.values())
            result = ResultAggregator.compute_counts_from_tests(test_results)

            # Generate LLM summary if in gen mode
            report_lang = report_cfg.get('language', 'en-US')

            llm_summary = ''
            if hasattr(self.executor, 'result_aggregator'):
                llm_summary = await self.executor.result_aggregator.generate_llm_summary(
                    test_results=test_results,
                    llm_config=llm_config,
                    report_lang=report_lang
                )
            completed_session.llm_summary = llm_summary

            # Final update of index.json
            save_index_json(
                test_session=completed_session,
                report_dir=custom_report_dir,
                result_count=result,
                test_results=test_results,
                llm_config=llm_config,
                browser_config=browser_config,
                report_lang=report_lang,
                mode='gen'
            )

        except BaseException as e:  # Capture KeyboardInterrupt/CancelledError as well
            logging.error(f'Error in parallel mode: {e}')
            run_error = e
        finally:
            try:
                # Prefer aggregator created during execution; fall back to a new one
                aggregator = getattr(self.executor, 'result_aggregator', ResultAggregator(report_cfg))
                if custom_report_dir:
                    if aggregated_data is None:
                        aggregated_data, _ = aggregator.aggregate_report_json('gen', custom_report_dir)

                    if completed_session is None:
                        completed_session = test_session
                    if completed_session is None:
                        completed_session = ParallelTestSession(session_id=str(uuid.uuid4()), target_url=url, llm_config=llm_config)

                    if html_path is None:
                        html_path = aggregator.generate_html_report_fully_inlined(
                            completed_session, report_dir=custom_report_dir, aggregated_data=aggregated_data
                        )
                        completed_session.html_report_path = html_path

                    if completed_session and test_session is None:
                        test_session = completed_session

                    # Cleanup tmp only when run succeeded and we aggregated data
                    has_results = bool(aggregated_data and any(k != 'index' for k in aggregated_data.get('gen', {})))
                    if run_error is None and has_results:
                        aggregator.cleanup_tmp_dir(custom_report_dir)
            except Exception as agg_err:
                logging.warning(f'Failed to aggregate/generate report: {agg_err}')

            # Cleanup Display
            try:
                await Display.display.stop()
                Display.display.render_summary()
            except Exception as display_err:
                logging.warning(f'Failed to stop display: {display_err}')

        if run_error:
            raise run_error

        if test_session is None:
            test_session = ParallelTestSession(session_id=str(uuid.uuid4()), target_url=url, llm_config=llm_config)
            test_session.report_path = custom_report_dir or ''

        return (
            test_session.aggregated_results,
            test_session.report_path,
            test_session.html_report_path,
            result,
        )

    def _configure_tests_from_config(
        self,
        test_session: ParallelTestSession,
        test_configurations: List[Dict[str, Any]],
        default_browser_config: Dict[str, Any],
        report_cfg: Dict[str, Any]
    ):
        """Configure tests from provided configuration."""
        for config in test_configurations:
            test_type_str = config.get('test_type', 'basic_test')

            # Map string to TestType enum
            test_type = self._map_test_type(test_type_str)

            # Merge browser config
            browser_config = {**default_browser_config, **config.get('browser_config', {})}

            test_config = TestConfiguration(
                test_id=str(uuid.uuid4()),
                test_type=test_type,
                test_name=get_default_test_name(test_type, report_cfg.get('language', 'zh-CN')),
                enabled=config.get('enabled', True),
                browser_config=browser_config,
                report_config=report_cfg,
                test_specific_config=config.get('test_specific_config', {}),
                timeout=config.get('timeout', 300),
                retry_count=config.get('retry_count', 0),
                dependencies=config.get('dependencies', []),
            )

            test_session.add_test_configuration(test_config)

    def _map_test_type(self, test_type_str: str) -> TestType:
        """Map string to TestType enum."""
        mapping = {
            'ui_agent_langgraph': TestType.UI_AGENT_LANGGRAPH,
            'ux_test': TestType.UX_TEST,
            'performance': TestType.PERFORMANCE,
            'basic_test': TestType.BASIC_TEST,
            # "web_basic_check": TestType.WEB_BASIC_CHECK,
            # "button_test": TestType.BUTTON_TEST,
            'security': TestType.SECURITY_TEST,
            'security_test': TestType.SECURITY_TEST,
        }

        return mapping.get(test_type_str, TestType.BASIC_TEST)

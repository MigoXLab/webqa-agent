"""Run mode executor for YAML case execution.

Integrated executor combining CaseMode orchestration and CaseRunner execution
logic. Provides symmetry with GenExecutor for clean dual-mode architecture.
"""

import logging
import os
import uuid
from datetime import datetime
from typing import Any, Dict, Optional, Tuple

from pydantic import ValidationError

from webqa_agent.actions.action_handler import ActionHandler
from webqa_agent.browser import AccountPool
from webqa_agent.browser.config import DEFAULT_CONFIG
from webqa_agent.config_models.run_config import RunConfig
from webqa_agent.data import (ParallelTestSession, TestCategory,
                              TestConfiguration, TestResult, TestStatus)
from webqa_agent.data.run_structures import Case
from webqa_agent.executor.result_aggregator import ResultAggregator
from webqa_agent.executor.run.case_runner import CaseRunner
from webqa_agent.utils import Display, i18n
from webqa_agent.utils.config import (load_accounts, load_cookies,
                                      load_yaml_files, resolve_config_dir)
from webqa_agent.utils.data_flow_reporter import (generate_data_flow_report,
                                                  set_dataflow_enabled)
from webqa_agent.utils.get_log import GetLog
from webqa_agent.utils.log_icon import icon
from webqa_agent.utils.reporting_utils import save_index_json

logger = logging.getLogger(__name__)


class RunExecutor:
    """Run mode executor (YAML case execution).

    Integrated executor that combines CaseMode orchestration and CaseRunner execution.
    Replaces the thin wrapper pattern with full self-contained implementation.

    Usage:
        config = RunConfig(...)
        executor = RunExecutor(config)
        results = await executor.execute()
    """

    def __init__(self, config: RunConfig):
        """Initialize RunExecutor with configuration.

        Args:
            config: RunConfig instance with all settings
        """
        self.config = config
        self.result_aggregator = ResultAggregator(config.report_config.model_dump())
        set_dataflow_enabled(config.report_config.save_dataflow)

    async def execute(self) -> Tuple[Dict[str, Any], str, str, Dict[str, int]]:
        """Execute run mode workflow.

        Returns:
            Tuple of (aggregated_results, report_path, html_path, result_count)
        """
        # Load YAML test cases
        configs = load_yaml_files(self.config.cases_path)

        if not configs:
            logger.warning(f'No test cases found in: {self.config.cases_path}')
            return {}, '', '', {'total': 0, 'passed': 0, 'failed': 0, 'warning': 0}

        logger.info(f'Loaded {len(configs)} configuration(s) from: {self.config.cases_path}')

        # Initialize basic variables
        all_cases = []
        all_target_urls = []
        all_ignore_rules = []
        browser_config = DEFAULT_CONFIG.copy()
        test_specific_config = {}

        # Handle multi-config mode: merge cases with their respective configs
        case_id_counter = 0
        for config in configs:
            cfg_cases = config.get('cases', [])
            source_file = config.get('_source_file', 'unknown')
            cfg_url = config.get('url') or config.get('target', {}).get('url', '')
            cfg_ignore_rules = config.get('ignore_rules', {})

            # Collect unique URLs and ignore_rules
            if cfg_url and cfg_url not in all_target_urls:
                all_target_urls.append(cfg_url)
            if cfg_ignore_rules:
                all_ignore_rules.append({
                    'source': source_file,
                    'url': cfg_url,
                    'ignore_rules': cfg_ignore_rules
                })

            raw_cookies = config.get('cookies') or config.get('browser_config', {}).get('cookies')
            resolved_cookies = (
                load_cookies(raw_cookies, config_dir=resolve_config_dir(source_file))
                if raw_cookies else None
            )
            accounts = load_accounts(config.get('accounts'), source_file=source_file)
            account_pool = AccountPool(accounts=accounts, fallback_cookies=resolved_cookies) if accounts else None

            # Attach config info to each case
            for case in cfg_cases:
                case_id_counter += 1
                case_account = case.get('account')
                account_key = (
                    account_pool.resolve_account_name(case_account)
                    if account_pool else None
                ) or ('__fallback__' if resolved_cookies else None)
                case['_config'] = {
                    'url': cfg_url,
                    'cookies': resolved_cookies,
                    'browser_config': config.get('browser') or config.get('browser_config', {}),
                    'ignore_rules': cfg_ignore_rules,
                    'account_pool': account_pool,
                    'account_key': account_key,
                    '_source_file': source_file,
                }
                case['case_id'] = f'case_{case_id_counter}'
                all_cases.append(case)

        if not all_cases:
            raise ValueError('No cases found in any configuration')

        # Use browser config from the first config as default
        if configs[0].get('browser_config'):
            browser_config.update(configs[0].get('browser_config'))

        # Log multi-config summary
        logger.debug(f'Multi-config mode: {len(all_cases)} cases from {len(configs)} config(s)')
        if all_target_urls:
            unique_urls = list(set(all_target_urls))
            if len(unique_urls) > 1:
                logger.debug(f"  Target URLs ({len(unique_urls)} unique): {', '.join(unique_urls)}")

        test_specific_config = {
            'config_count': len(configs),
            'target_urls': all_target_urls,
            'ignore_rules_configs': all_ignore_rules,
        }

        cases = all_cases

        # Initialize logging and display
        log_level = self.config.log_config.level
        stdout = self.config.log_config.stdout
        report_lang = self.config.report_config.language

        GetLog.get_log(log_level=log_level, stdout=stdout)
        Display.init(language=report_lang, no_terminal_ui=stdout)
        Display.display.start()

        mode_str = f'parallel ({self.config.workers} workers)' if self.config.workers > 1 else 'serial'
        logger.info(f"{icon['rocket']} Starting run mode execution ({mode_str})")

        # Create test session
        session_id = str(uuid.uuid4())
        test_session = ParallelTestSession(
            session_id=session_id,
            llm_config=self.config.llm_config.model_dump()
        )
        if all_target_urls:
            test_session.target_url = all_target_urls[0]

        # Set up report directory
        report_ts = datetime.now().strftime('%Y-%m-%d_%H-%M-%S_%f')
        os.environ['WEBQA_REPORT_TIMESTAMP'] = report_ts

        # Initialize screenshot directory for this test session
        ActionHandler.clear_screenshot_session()

        # Get report_dir or use default
        report_dir = self.config.report_config.report_dir
        if not report_dir or (isinstance(report_dir, str) and not report_dir.strip()):
            # Use default reports/{timestamp}/ directory
            report_dir = os.path.join('reports', f'test_{report_ts}')

        test_session.report_path = report_dir

        # Configure screenshot saving behavior
        save_screenshots = self.config.report_config.save_screenshots
        ActionHandler.set_screenshot_config(save_screenshots=save_screenshots)

        ActionHandler.init_screenshot_session(custom_report_dir=report_dir)
        logger.info(f'📸 Screenshot directory initialized for report: {report_dir}')

        test_config = TestConfiguration(
            test_id=str(uuid.uuid4()),
            test_name=i18n.t(report_lang, 'tools.run_mode.test_name', 'Run Mode'),
            enabled=True,
            report_config=self.config.report_config.model_dump(),
            browser_config=browser_config,
            test_specific_config=test_specific_config,
        )

        test_session.add_test_configuration(test_config)
        test_session.start_session()

        # Initialize index.json at start
        initial_result_count = {'total': len(cases), 'passed': 0, 'failed': 0, 'warning': 0}
        save_index_json(
            test_session=test_session,
            report_dir=report_dir,
            result_count=initial_result_count,
            llm_config=self.config.llm_config.model_dump(),
            browser_config=browser_config,
            report_lang=report_lang,
            mode='run'
        )

        case_executor = None
        case_results = None
        result_count = {'total': 0, 'passed': 0, 'failed': 0, 'warning': 0}
        html_report_path = None
        aggregated_data = None
        run_error: Optional[Exception] = None

        try:
            # Parse and validate cases from YAML dicts
            try:
                # Case model has extra='allow', so it keeps _config
                # Sanitization of name happens here in Case model
                parsed_cases = Case.from_yaml_list(cases)
                logger.info(f'📋 Parsed and validated {len(parsed_cases)} test cases')
                result_count['total'] = len(parsed_cases)

                # Keep original display names; safe_name is stored separately on the model
                # Ensure indices match (Case.from_yaml_list should maintain order)
                if len(parsed_cases) != len(cases):
                    raise ValueError(f'Parsed cases count ({len(parsed_cases)}) does not match input count ({len(cases)})')

                for i, parsed_case in enumerate(parsed_cases):
                    cases[i]['safe_name'] = parsed_case.safe_name
            except ValidationError as e:
                # Format friendly error message
                error_details = []
                for error in e.errors():
                    loc = error['loc']
                    msg = error['msg']
                    if msg.startswith('Value error, '):
                        msg = msg.replace('Value error, ', '')

                    case_idx = loc[0] if len(loc) > 0 and isinstance(loc[0], int) else None
                    case_name = 'Unknown Case'
                    if case_idx is not None and case_idx < len(cases):
                        case_name = cases[case_idx].get('name', f'Case {case_idx + 1}')

                    if len(loc) >= 3 and loc[1] == 'steps':
                        step_info = f'Step {loc[2] + 1}'
                        field = str(loc[3]) if len(loc) > 3 else ''
                        error_details.append(f"  - [{case_name}] {step_info}{f' {field}' if field else ''}: {msg}")
                    elif len(loc) >= 2:
                        error_details.append(f"  - [{case_name}] field '{loc[1]}': {msg}")
                    else:
                        error_details.append(f'  - [{case_name}]: {msg}')

                friendly_msg = 'Case format is invalid:\n' + '\n'.join(error_details)
                logger.error(f"{icon['cross']} {friendly_msg}")
                raise ValueError(friendly_msg) from e

            # Execute all cases with shared session pool (mixed concurrency)
            # Workers dynamically handle config changes via session pool
            case_executor = CaseRunner(
                test_config=test_config,
                llm_config=self.config.llm_config.model_dump(),
                report_dir=report_dir,
                account_pool=AccountPool(
                    accounts=self.config.accounts,
                    fallback_cookies=self.config.browser_config.cookies,
                ) if self.config.accounts else None,
            )

            case_results = await case_executor.execute_cases(
                cases=cases,  # All cases, no grouping by config
                workers=self.config.workers
            )

            if case_results is None:
                logger.warning('case_executor.execute_cases returned None, treating as empty list')
                case_results = []

            # Build test result first
            end_time = datetime.now()
            test_result = TestResult(
                test_id=test_config.test_id,
                test_name=test_config.test_name,
                status=TestStatus.PASSED,  # Will be updated based on sub_tests
                category=TestCategory.FUNCTION,
                start_time=test_session.start_time,
                end_time=end_time,
                sub_tests=case_results,
                error_message=None,
            )

            # Calculate result statistics and determine overall status
            result_count = ResultAggregator.compute_counts_from_tests([test_result])
            total_cases = result_count.get('total', 0)
            passed_cases = result_count.get('passed', 0)
            failed_cases = result_count.get('failed', 0)
            warning_cases = result_count.get('warning', 0)

            # Update status based on results
            if failed_cases > 0:
                test_result.status = TestStatus.FAILED
                test_result.error_message = f'{failed_cases} out of {total_cases} cases failed'
            elif warning_cases > 0:
                test_result.status = TestStatus.WARNING

            test_session.update_test_result(test_config.test_id, test_result)
            test_session.complete_session()

            # Update index.json after completion
            save_index_json(
                test_session=test_session,
                report_dir=report_dir,
                result_count=result_count,
                test_results=[test_result],  # Wrap in list for save_index_json compatibility
                llm_config=self.config.llm_config.model_dump(),
                browser_config=browser_config,
                report_lang=report_lang,
                mode='run'
            )

            logger.info(f"{icon['check']} Cases executed: {passed_cases}/{total_cases} passed")

        except BaseException as e:  # Capture KeyboardInterrupt/CancelledError as well
            run_error = e
        finally:
            # Aggregate and generate report even if execution was interrupted
            try:
                if aggregated_data is None:
                    aggregated_data, _ = self.result_aggregator.aggregate_report_json('run', report_dir)

                if html_report_path is None:
                    html_report_path = self.result_aggregator.generate_html_report_fully_inlined(
                        test_session, report_dir=report_dir, aggregated_data=aggregated_data
                    )
                    test_session.html_report_path = html_report_path
                    logger.info(f"{icon['check']} HTML report generated: {html_report_path}")

                # Cleanup tmp only when run succeeded and we actually aggregated results
                # Note: We exclude 'index' key because it's metadata, not actual test results
                has_results = bool(aggregated_data and any(k != 'index' for k in aggregated_data.get('run', {})))
                if run_error is None and has_results:
                    self.result_aggregator.cleanup_tmp_dir(report_dir)
            except Exception as agg_err:
                logger.warning(f'Failed to aggregate/generate report in {report_dir}: {agg_err}', exc_info=True)

            # Render data flow interactive gantt from captured JSONL events.
            if report_dir and self.config.report_config.save_dataflow:
                try:
                    generate_data_flow_report(report_dir)
                except Exception as dataflow_err:
                    logger.warning(f'Failed to generate data flow report: {dataflow_err}')

            # Cleanup Display
            try:
                await Display.display.stop()
                Display.display.render_summary()
            except Exception as display_err:
                logger.warning(f'Failed to stop display: {display_err}', exc_info=True)

        if run_error:
            raise run_error

        return (
            test_session.aggregated_results,
            test_session.report_path,
            test_session.html_report_path,
            result_count,
        )

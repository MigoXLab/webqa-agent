"""Case Runner - Execute test cases defined in YAML with ai/aiAssert steps.

Internal implementation for Run mode executor.

This module handles:
1. Serial/Parallel execution of test cases from YAML configuration
2. Step-by-step execution (ai actions and aiAssert validations)
3. Result collection and screenshot capture
4. Integration with existing UITester and browser session
"""

import asyncio
import json
import logging
import os
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

from webqa_agent.actions.action_handler import screenshot_prefix_var
from webqa_agent.browser import BrowserSession, BrowserSessionPool
from webqa_agent.llm.llm_api import (
    get_llm_duration_stats, reset_llm_duration_stats,
    get_llm_io_log, reset_llm_io_log,
)
from webqa_agent.data import (CaseStep, StepContext, SubTestResult,
                              SubTestStep, TestConfiguration, TestStatus)
from webqa_agent.utils import Display, i18n
from webqa_agent.utils.data_flow_reporter import record_data_flow_event
from webqa_agent.utils.get_log import test_id_var
from webqa_agent.utils.log_icon import icon
from webqa_agent.utils.reporting_utils import (save_monitor_data_json,
                                               save_test_result_json)


class CaseRunner:
    """Runner for YAML-defined test cases with action/verify steps.

    Internal implementation for Run mode executor.

    This class handles:
    - Executing multiple test cases serially
    - Managing browser sessions for each case
    - Executing action and verify steps
    - Collecting monitoring data (console/network errors)
    - Saving test results to JSON files
    """

    def __init__(self, llm_config: Dict[str, Any], test_config: TestConfiguration, report_dir: Optional[str] = None):
        """Initialize case runner.

        Args:
            llm_config: LLM configuration for AI operations
            test_config: Test configuration including browser, report, and test-specific configs
            report_dir: Optional report directory. If not provided, will use timestamp from env or current time.
        """
        self.llm_config = llm_config
        self.test_config = test_config
        self.browser_config = test_config.browser_config
        self.report_config = test_config.report_config
        self.test_specific_config = test_config.test_specific_config
        self.report_dir = report_dir

        # Pre-compute invariant i18n values for display
        report_lang = self.report_config.get('language', 'zh-CN') if self.report_config else 'zh-CN'
        self._display_prefix = i18n.t(report_lang, 'tools.run_mode.display_text', 'Run Mode')

    async def execute_cases(
        self,
        cases: List[Dict[str, Any]],
        workers: int = 1,
    ) -> List[SubTestResult]:
        """Execute all cases using worker pool pattern (unified
        serial/parallel).

        Execution flow:
        1. Cases with non-empty snapshot run serially first and auto-save browser state
        2. Remaining cases run concurrently after pre-setup-cases complete

        Args:
            cases: List of case configurations from YAML
            workers: Number of parallel workers (1 = serial, >1 = parallel)

        Returns:
            List of SubTestResult for each case
        """
        total_cases = len(cases)
        mode_str = f'parallel ({workers} workers)' if workers > 1 else 'serial'
        logging.info(f"{icon['rocket']} Starting {mode_str} execution: {total_cases} cases")

        # Phase 1: Separate cases by snapshot
        fixture_cases = [
            (idx, case) for idx, case in enumerate(cases, 1)
            if case.get('snapshot')  # Non-empty snapshot = fixture case
        ]
        normal_cases = [
            (idx, case) for idx, case in enumerate(cases, 1)
            if not case.get('snapshot')  # No snapshot = normal case
        ]

        if fixture_cases:
            logging.info(f"{icon['lock']} Found {len(fixture_cases)} fixture cases (will run serially first)")
        if normal_cases:
            logging.info(f"{icon['rocket']} Found {len(normal_cases)} normal cases (will run concurrently after)")

        # Create session pool (auto-initialized)
        session_pool = BrowserSessionPool(pool_size=workers, browser_config=self.browser_config)

        # Shared state
        results: List[SubTestResult] = []
        results_lock = asyncio.Lock()
        completed_count = 0

        # Phase 2: Execute fixture cases serially
        for idx, case in fixture_cases:
            case_name = case.get('name', f'Case {idx}')
            case_id = case.get('case_id', f'case_{idx}')
            browser_cfg = case.get('_config', {}).get('browser_config', self.browser_config)
            # Set test_id context for logging (matching Gen mode pattern: "Run | case_id")
            log_context = f'Run | {case_id}'
            token = test_id_var.set(log_context)
            session = None
            case_result = None
            raw_monitoring_data = None

            try:
                logging.info(f"{icon['lock']} Starting fixture case: '{case_name}' ({completed_count + 1}/{total_cases})")
                session = await session_pool.acquire(browser_config=browser_cfg, timeout=120.0)

                # Per-case timeout: env > case _config > default 20 minutes
                default_timeout = int(os.getenv('WEBQA_CASE_TIMEOUT', '2400'))
                case_timeout = case.get('_config', {}).get('case_timeout', default_timeout)

                with Display.display(case_name) as tracker:  # pylint: disable=not-callable
                    case_result, raw_monitoring_data = await asyncio.wait_for(
                        self.execute_single_case(
                            session=session, case=case, case_index=idx,
                            completed_case_count=completed_count,
                        ),
                        timeout=case_timeout
                    )
                    # Set result on tracker so it's included when task moves to completed
                    tracker.result = case_result.status.value

                async with results_lock:
                    results.append(case_result)
                    completed_count += 1

                status_icon = icon['check'] if case_result.status == TestStatus.PASSED else icon['cross']
                logging.info(f"{status_icon} Fixture case '{case_name}' - {case_result.status} ({completed_count}/{total_cases})")

                # Auto-save snapshot after execution (using PersistentContextManager directly)
                snapshot_id = case.get('snapshot')
                if snapshot_id:
                    try:
                        from webqa_agent.browser.context_manager import \
                            PersistentContextManager
                        await PersistentContextManager.save_storage_state(
                            session.context,
                            snapshot_id,
                            base_dir=self._get_snapshot_dir()
                        )
                        logging.info(f"{icon['check']} Saved persistent snapshot to '{snapshot_id}' for '{case_name}'")
                    except Exception as e:
                        logging.warning(f"Failed to save snapshot for '{case_name}': {e}")

            except asyncio.TimeoutError:
                logging.error(f"Fixture case '{case_name}' timed out after {case_timeout}s")
                async with results_lock:
                    completed_count += 1
                    results.append(SubTestResult(
                        sub_test_id=case_id,
                        name=case_name,
                        status=TestStatus.FAILED,
                        metrics={'total_steps': 0, 'passed_steps': 0, 'failed_steps': 0},
                        steps=[],
                        messages={},
                        start_time=datetime.now().isoformat(),
                        end_time=datetime.now().isoformat(),
                        final_summary=f'Case timed out after {case_timeout} seconds',
                        report=[],
                    ))
                if session:
                    await session_pool.release(session, failed=True)
                    session = None

            except Exception as e:
                logging.error(f"Exception in fixture case '{case_name}': {e}", exc_info=True)
                async with results_lock:
                    completed_count += 1
                    results.append(SubTestResult(
                        sub_test_id=case_id,
                        name=case_name,
                        status=TestStatus.FAILED,
                        metrics={'total_steps': 0, 'passed_steps': 0, 'failed_steps': 0},
                        steps=[],
                        messages={},
                        start_time=datetime.now().isoformat(),
                        end_time=datetime.now().isoformat(),
                        final_summary=f'Exception: {str(e)}',
                        report=[],
                    ))

            finally:
                # Reset test_id context
                test_id_var.reset(token)
                if case_result is not None:
                    case_config = case.get('_config', {})
                    self._save_case_result(case_result, case_name, idx, raw_monitoring_data=raw_monitoring_data, case_config=case_config)
                    self._clear_case_screenshots(case_result)
                if session:
                    failed = case_result is None or case_result.status == TestStatus.FAILED
                    await session_pool.release(session, failed=failed)

        # Phase 3: Execute normal cases concurrently
        if not normal_cases:
            logging.info(f"{icon['check']} All fixture cases completed. No normal cases to execute.")
            await session_pool.close_all()
            return results
        logging.info(f"{icon['rocket']} Starting concurrent execution of {len(normal_cases)} normal cases")

        # Fill queue with normal cases
        case_queue: asyncio.Queue = asyncio.Queue()  # Queue for normal cases
        for idx, case in normal_cases:
            await case_queue.put((idx, case))
        # Add sentinels early so idle workers can exit immediately
        for _ in range(workers):
            await case_queue.put(None)

        async def worker(worker_id: int):
            """Worker that pulls cases from queue until sentinel."""
            nonlocal completed_count

            session = None
            current_config_key = None

            while True:
                item = await case_queue.get()
                if item is None:  # Sentinel - exit
                    case_queue.task_done()
                    break

                idx, case = item
                case_name = case.get('name', f'Case {idx}')
                case_id = case.get('case_id', f'case_{idx}')

                # Extract browser config for this case
                browser_cfg = case.get('_config', {}).get('browser_config', self.browser_config)
                new_config_key = session_pool._make_config_key(browser_cfg)

                # Set test_id context for logging (matching Gen mode pattern: "Run | case_id")
                log_context = f'Run | {case_id}'
                token = test_id_var.set(log_context)

                # Set screenshot prefix to avoid filename collisions in parallel execution
                prefix_token = screenshot_prefix_var.set(case_id)

                case_result = None
                raw_monitoring_data = None

                try:
                    logging.info(f"Worker {worker_id}: Starting case '{case_name}' ({idx}/{total_cases})")
                    if session is None or new_config_key != current_config_key:
                        if session:
                            await session_pool.release(session, keep_alive=False)
                        session = await session_pool.acquire(browser_config=browser_cfg, timeout=120.0)
                        current_config_key = new_config_key

                    # Per-case timeout: env > case _config > default 20 minutes
                    default_timeout = int(os.getenv('WEBQA_CASE_TIMEOUT', '2400'))
                    case_timeout = case.get('_config', {}).get('case_timeout', default_timeout)

                    with Display.display(case_name) as tracker:  # pylint: disable=not-callable
                        case_result, raw_monitoring_data = await asyncio.wait_for(
                            self.execute_single_case(
                                session=session, case=case, case_index=idx,
                                completed_case_count=completed_count,
                            ),
                            timeout=case_timeout
                        )
                        # Set result on tracker so it's included when task moves to completed
                        tracker.result = case_result.status.value

                    async with results_lock:
                        results.append(case_result)
                        completed_count += 1

                    status_icon = icon['check'] if case_result.status == TestStatus.PASSED else icon['cross']
                    logging.info(f"{status_icon} Worker {worker_id}: '{case_name}' - {case_result.status} ({completed_count}/{total_cases})")

                except asyncio.TimeoutError:
                    logging.error(f"Worker {worker_id}: Case '{case_name}' timed out after {case_timeout}s")
                    async with results_lock:
                        completed_count += 1
                        results.append(SubTestResult(
                            sub_test_id=case_id,
                            name=case_name,
                            status=TestStatus.FAILED,
                            metrics={'total_steps': 0, 'passed_steps': 0, 'failed_steps': 0},
                            steps=[],
                            messages={},
                            start_time=datetime.now().isoformat(),
                            end_time=datetime.now().isoformat(),
                            final_summary=f'Case timed out after {case_timeout} seconds',
                            report=[],
                        ))
                    case_result = None
                    raw_monitoring_data = None
                    if session:
                        await session_pool.release(session, failed=True, keep_alive=False)
                        session = None
                        current_config_key = None

                except Exception as e:
                    logging.error(f"Worker {worker_id}: Exception in '{case_name}': {e}", exc_info=True)
                    async with results_lock:
                        completed_count += 1
                        results.append(SubTestResult(
                            sub_test_id=case_id,
                            name=case_name,
                            status=TestStatus.FAILED,
                            metrics={'total_steps': 0, 'passed_steps': 0, 'failed_steps': 0},
                            steps=[],
                            messages={},
                            start_time=datetime.now().isoformat(),
                            end_time=datetime.now().isoformat(),
                            final_summary=f'Exception: {str(e)}',
                            report=[],
                        ))
                    case_result = None
                    raw_monitoring_data = None
                    if session:
                        await session_pool.release(session, failed=True, keep_alive=False)
                        session = None
                        current_config_key = None

                finally:
                    # Reset context variables
                    test_id_var.reset(token)
                    screenshot_prefix_var.reset(prefix_token)

                    if case_result is not None:
                        case_config = case.get('_config', {})
                        await asyncio.to_thread(
                            self._save_case_result, case_result, case_name, idx,
                            raw_monitoring_data=raw_monitoring_data, case_config=case_config,
                        )
                        self._clear_case_screenshots(case_result)

                    case_queue.task_done()
            if session:
                await session_pool.release(session, keep_alive=False)

        try:
            # Start workers and wait for completion
            worker_tasks = [asyncio.create_task(worker(i)) for i in range(workers)]
            await case_queue.join()
            await asyncio.gather(*worker_tasks, return_exceptions=True)

        finally:
            await session_pool.close_all()

        # Sort by original index (O(n) using lookup dict)
        case_order = {c.get('case_id'): i for i, c in enumerate(cases, 1)}
        results.sort(key=lambda r: case_order.get(r.sub_test_id, 999))
        logging.info(f"{icon['check']} Execution completed: {len(results)}/{total_cases} cases")
        return results

    async def execute_single_case(
        self, session: BrowserSession, case: Dict[str, Any],
        case_index: int = 1, completed_case_count: int = 0,
    ) -> Tuple[SubTestResult, Dict[str, Any]]:
        """Execute a single test case.

        Args:
            session: Browser session
            case: Case configuration {"name": "...", "steps": [...], "_config": {...}}
            case_index: Index of the case (for logging)
            completed_case_count: Number of cases already completed (for data flow reporting)

        Returns:
            SubTestResult containing execution results
        """
        case_name = case.get('name', f'Unnamed Case {case_index}')
        case_id = case.get('case_id', f'case_{case_index}')
        start_time = datetime.now()

        # Clean session state for case isolation (clear cookies/storage from previous case)
        # This runs before navigate_to which will inject new cookies if configured
        await session.clean_state()

        # Get case-specific config if available (for multi-YAML support)
        case_config = case.get('_config', {})
        url = case_config.get('url') or self.test_specific_config.get('url')

        cookies = case_config.get('cookies') or self.test_specific_config.get('cookies')

        # Record case start for data flow reporting
        record_data_flow_event(
            stage='run',
            event_type='case_execution_start',
            payload={
                'case_id': case_id,
                'case_name': case_name,
                'case': case,
                'completed_case_count': completed_case_count,
            },
            report_dir=self.report_dir,
        )
        ignore_rules = case_config.get('ignore_rules') or self.test_specific_config.get('ignore_rules', {})

        use_snapshot = case.get('use_snapshot')

        # Always navigate first; snapshot state is applied after
        tester = await self._initialize_tester(
            session, case_name,
            url=url,
            cookies=cookies if not use_snapshot else None,
            ignore_rules=ignore_rules
        )

        if use_snapshot:
            await self._load_fixture_state(session, case, case_config)

        # Execute steps
        executed_steps, case_status, error_messages, prev_step_context, case_llm_metrics = await self._execute_steps(
            tester, case.get('steps', []), case_id=case_id, case_name=case_name
        )

        # Get monitoring data and cleanup
        monitoring_data = await self._end_session(tester)
        await self._cleanup_tester(tester, case_name)

        # Build final result
        end_time = datetime.now()
        case_result, raw_monitoring_data = self._build_case_result(
            case_name=case_name,
            case_id=case_id,
            case_status=case_status,
            executed_steps=executed_steps,
            error_messages=error_messages,
            monitoring_data=monitoring_data,
            start_time=start_time,
            end_time=end_time,
            ignore_rules=ignore_rules
        )

        # Record case result for data flow reporting (consistent with Gen mode structure)
        duration_seconds = (end_time - start_time).total_seconds()
        passed_steps = sum(1 for s in executed_steps if s.status == TestStatus.PASSED)
        failed_steps = sum(1 for s in executed_steps if s.status == TestStatus.FAILED)
        warning_steps = sum(1 for s in executed_steps if s.status == TestStatus.WARNING)
        failed_step_details = [
            {
                'step_id': s.id,
                'description': s.description,
                'status': s.status.value,
                'errors': s.errors or '',
            }
            for s in executed_steps if s.status == TestStatus.FAILED
        ]
        record_data_flow_event(
            stage='run',
            event_type='case_execution_result',
            payload={
                'case_id': case_id,
                'case_name': case_name,
                'case_result': {
                    'case_name': case_name,
                    'case_id': case_id,
                    'status': case_result.status.value,
                    'final_summary': case_result.final_summary or '',
                    'metrics': {
                        'total_steps': len(executed_steps),
                        'passed_steps': passed_steps,
                        'failed_steps': failed_steps,
                        'warning_steps': warning_steps,
                    },
                    'failed_step_details': failed_step_details,
                    'error_messages': error_messages,
                    'duration_seconds': duration_seconds,
                    'llm_metrics': case_llm_metrics,
                },
            },
            report_dir=self.report_dir,
        )

        return case_result, raw_monitoring_data

    # ========================================================================
    # Private Methods - Tester Lifecycle
    # ========================================================================

    def _get_snapshot_dir(self) -> str:
        """Get snapshot base directory within report directory.

        Returns:
            str: Snapshot base directory path ({report_dir}/snapshots/)
        """
        return os.path.join(self.report_dir, 'snapshots')

    async def _load_fixture_state(
        self,
        session: BrowserSession,
        case: Dict[str, Any],
        case_config: Dict[str, Any]
    ) -> None:
        """Load fixture state (cookies + localStorage + sessionStorage) after
        page navigation.

        Args:
            session: Browser session
            case: Case configuration with use_snapshot field
            case_config: Case-specific configuration
        """
        snapshot_name = case.get('use_snapshot')
        if not snapshot_name:
            return

        try:
            from webqa_agent.browser.context_manager import \
                PersistentContextManager
            storage_path = await PersistentContextManager.get_storage_state_path(snapshot_name, self._get_snapshot_dir())
            if not storage_path:
                logging.warning(f"Snapshot '{snapshot_name}' not found, case will run without pre-loaded state")
                return
            # load storage_state JSON, including cookies and origins
            with open(storage_path, 'r', encoding='utf-8') as f:
                storage_state = json.load(f)

            page = session.page
            current_url = page.url

            # load cookies
            if 'cookies' in storage_state and storage_state['cookies']:
                await session.context.add_cookies(storage_state['cookies'])
                logging.info(f"Loaded {len(storage_state['cookies'])} cookies from snapshot '{snapshot_name}'")

            # load localStorage and sessionStorage
            if 'origins' in storage_state:
                for origin_data in storage_state['origins']:
                    origin = origin_data.get('origin')
                    if not origin or not current_url.startswith(origin):
                        continue

                    # Inject localStorage
                    if 'localStorage' in origin_data:
                        for item in origin_data['localStorage']:
                            await page.evaluate(
                                f"window.localStorage.setItem({json.dumps(item['name'])}, {json.dumps(item['value'])})"
                            )
                        logging.debug(f"Injected {len(origin_data['localStorage'])} localStorage items")

                    # Inject sessionStorage
                    if 'sessionStorage' in origin_data:
                        for item in origin_data['sessionStorage']:
                            await page.evaluate(
                                f"window.sessionStorage.setItem({json.dumps(item['name'])}, {json.dumps(item['value'])})"
                            )
                        logging.debug(f"Injected {len(origin_data['sessionStorage'])} sessionStorage items")

            # Reload page to apply storage
            await page.reload(wait_until='domcontentloaded')
            try:
                await page.wait_for_load_state('networkidle', timeout=3000)
            except Exception:
                logging.debug(f"networkidle timed out after snapshot reload for '{snapshot_name}', proceeding")
            await asyncio.sleep(1)
            logging.info(f"Reloaded page to apply snapshot '{snapshot_name}' state")

        except Exception as e:
            logging.warning(f"Failed to load snapshot '{snapshot_name}': {e}")

    async def _initialize_tester(
        self,
        session: BrowserSession,
        case_name: str,
        url: Optional[str] = None,
        cookies: Optional[List] = None,
        ignore_rules: Optional[Dict] = None
    ):
        """Initialize and start UI tester for case execution.

        Args:
            session: Browser session to use
            case_name: Name of the case (for logging)
            url: Target URL (optional, falls back to test_specific_config)
            cookies: Cookies (optional, falls back to test_specific_config)
            ignore_rules: Ignore rules (optional, falls back to test_specific_config)

        Returns:
            Initialized UITester instance
        """
        from webqa_agent.tools.core.ui_driver import UITester

        _ignore_rules = ignore_rules or self.test_specific_config.get('ignore_rules', {})
        report_lang = self.report_config.get('language', 'zh-CN') if self.report_config else 'zh-CN'
        tester = UITester(
            llm_config=self.llm_config,
            browser_session=session,
            ignore_rules=_ignore_rules,
            execution_mode='run',  # RUN mode: trust user-specified operations in YAML
            language=report_lang,
        )
        await tester.initialize()
        tester.set_current_test_name(case_name)

        _url = url or self.test_specific_config.get('url')
        _cookies = cookies or self.test_specific_config.get('cookies')

        # Only navigate if URL is provided (None means skip navigation for snapshot cases)
        if _url:
            await tester.start_session(url=_url, cookies=_cookies)
        else:
            # No navigation needed (snapshot will load page state)
            logging.debug('Skipping navigation for snapshot case')
        return tester

    async def _end_session(self, tester) -> Dict[str, Any]:
        """Safely end tester session and get monitoring data.

        Args:
            tester: UITester instance

        Returns:
            Monitoring data dict (console/network errors)
        """
        if not tester:
            return {}

        try:
            return await tester.end_session()
        except Exception as e:
            logging.warning(f'Failed to get monitoring data: {e}')
            return {}

    async def _cleanup_tester(self, tester, case_name: str) -> None:
        """Safely cleanup tester resources.

        Args:
            tester: UITester instance
            case_name: Name of the case (for logging)
        """
        if not tester:
            return

        try:
            await tester.cleanup()
            logging.debug(f'UITester cleanup completed for case: {case_name}')
        except Exception as e:
            logging.warning(f'Failed to cleanup UITester: {e}')

    @staticmethod
    def _resolve_screenshots(step_data: Dict[str, Any]) -> Any:
        """Resolve screenshots from step data, preferring file paths over
        base64.

        Args:
            step_data: Step execution result dictionary

        Returns:
            Screenshots list (paths preferred over base64)
        """
        return step_data.get('screenshots_paths') or step_data.get('screenshots')

    # ========================================================================
    # Private Methods - Step Execution
    # ========================================================================

    async def _execute_steps(
        self,
        tester,
        steps: List[Dict[str, Any]],
        case_id: str = '',
        case_name: str = '',
    ) -> Tuple[List[SubTestStep], TestStatus, List[str], Optional[StepContext], Dict[str, Any]]:
        """Execute all steps in a case.

        Args:
            tester: UITester instance
            steps: List of step configurations
            case_id: Case identifier (for data flow reporting)
            case_name: Case name (for data flow reporting)

        Returns:
            Tuple of (executed_steps, case_status, error_messages, prev_step_context, accumulated_token_usage)
        """
        executed_steps = []
        case_status = TestStatus.PASSED
        error_messages = []
        prev_step_context: Optional[StepContext] = None
        accumulated_token_usage: Dict[str, int] = {
            'prompt_tokens': 0, 'completion_tokens': 0, 'total_tokens': 0,
        }
        accumulated_llm_duration: float = 0.0

        for step_idx, step in enumerate(steps, 1):
            # Fast-fail: check if the browser page has crashed before executing the next step
            try:
                page = tester.browser_session.page
                if page.is_closed():
                    raise RuntimeError('Page is closed')
            except Exception:
                logging.error('Browser page crashed, aborting remaining steps.')
                case_status = TestStatus.FAILED
                error_messages.append(f'Step {step_idx}: Browser page crashed (Target crashed)')
                break

            parsed_step = CaseStep.model_validate(step)
            step_type = parsed_step.step_type
            instruction = (
                parsed_step.action.description if step_type == 'action' and parsed_step.action
                else parsed_step.verify.assertion if step_type == 'verify' and parsed_step.verify
                else ''
            )

            # Record step request for data flow reporting
            record_data_flow_event(
                stage='run',
                event_type='step_request',
                payload={
                    'case_id': case_id,
                    'case_name': case_name,
                    'planned_step_index': step_idx,
                    'step_type': step_type,
                    'instruction': instruction,
                },
                report_dir=self.report_dir,
            )

            reset_llm_duration_stats()
            reset_llm_io_log()
            step_start = datetime.now()

            if step_type == 'action':
                logging.info(f'Executing step {step_idx}: {parsed_step.action}')
                step_result, prev_step_context = await self._execute_action_step(
                    tester, parsed_step.action, step_idx
                )
            elif step_type == 'verify':
                logging.info(f'Executing step {step_idx}: {parsed_step.verify}')
                step_result, prev_step_context = await self._execute_verify_step(
                    tester, parsed_step.verify, step_idx, prev_step_context
                )
            else:
                raise ValueError(f'Unsupported step type: {step_type}')

            step_duration = (datetime.now() - step_start).total_seconds()

            # Collect LLM token usage for this step
            llm_stats = get_llm_duration_stats()
            llm_token_usage = dict(llm_stats.get('token_usage', {})) if llm_stats else {}
            llm_duration = float(llm_stats.get('duration_seconds', 0.0)) if llm_stats else 0.0

            # Accumulate token usage across all steps for case-level summary
            for token_key in ('prompt_tokens', 'completion_tokens', 'total_tokens'):
                accumulated_token_usage[token_key] += int(llm_token_usage.get(token_key, 0))
            accumulated_llm_duration += llm_duration

            # Compute time breakdown (consistent with Gen mode structure)
            system_total = max(step_duration - llm_duration, 0.0)
            llm_ratio = round(llm_duration / step_duration, 4) if step_duration > 0 else 0.0
            system_ratio = round(system_total / step_duration, 4) if step_duration > 0 else 0.0

            # Collect LLM I/O log for this step
            llm_io = get_llm_io_log()

            # Record step response for data flow reporting
            record_data_flow_event(
                stage='run',
                event_type='step_response',
                payload={
                    'case_id': case_id,
                    'case_name': case_name,
                    'planned_step_index': step_idx,
                    'step_type': step_type,
                    'instruction': instruction,
                    'status': step_result.status.value,
                    'duration_seconds': step_duration,
                    'llm_metrics': {
                        'duration_seconds': llm_duration,
                        'token_usage': llm_token_usage,
                    },
                    'time_breakdown': {
                        'e2e_duration_seconds': round(step_duration, 2),
                        'llm_duration_seconds': round(llm_duration, 2),
                        'system_total_seconds': round(system_total, 2),
                        'ratio': {
                            'llm_ratio': llm_ratio,
                            'system_ratio': system_ratio,
                        },
                    },
                    'llm_calls': llm_io,
                    'output': {
                        'errors': step_result.errors or '',
                        'actions': step_result.actions or [],
                    },
                },
                report_dir=self.report_dir,
            )

            executed_steps.append(step_result)

            # Update case status
            if step_result.status == TestStatus.FAILED:
                case_status = TestStatus.FAILED
                error_messages.append(f'Step {step_idx} failed: {step_result.errors}')
                logging.warning(f'Step {step_idx} failed, interrupting case execution.')
                break
            elif step_result.status == TestStatus.WARNING and case_status == TestStatus.PASSED:
                case_status = TestStatus.WARNING

        case_llm_metrics = {
            'duration_seconds': accumulated_llm_duration,
            'token_usage': accumulated_token_usage,
        }
        return executed_steps, case_status, error_messages, prev_step_context, case_llm_metrics

    async def _execute_action_step(
        self,
        tester,
        action,
        step_idx: int
    ) -> Tuple[SubTestStep, StepContext]:
        """Execute an action step.

        Args:
            tester: UITester instance
            action: StepAction configuration
            step_idx: Step index (for logging and result)

        Returns:
            Tuple of (step_result, prev_step_context)
        """
        file_path = action.args.file_path if action.args else None

        # Clear event collector so we only capture events from this step
        await tester.browser_session.event_collector.clear()

        execution_steps_dict, execution_result = await tester.action(
            test_step=action.description,
            file_path=file_path,
            viewport_only=True,
            full_page=False
        )

        step_result = SubTestStep(
            id=step_idx,
            description=f'action: {action.description}',
            screenshots=self._resolve_screenshots(execution_steps_dict),
            modelIO=str(execution_steps_dict.get('modelIO', {})),
            actions=execution_steps_dict.get('actions', []),
            status=execution_steps_dict.get('status', TestStatus.PASSED),
            errors=execution_steps_dict.get('error', ''),
        )

        # Save context for next step (only necessary fields)
        context_result = {
            'before_screenshot': execution_result.get('before_screenshot'),
            'after_screenshot': execution_result.get('after_screenshot'),
            'after_action_url': execution_result.get('after_action_url'),
            'after_action_title': execution_result.get('after_action_title'),
            'after_action_page_structure': execution_result.get('after_action_page_structure'),
        }

        # Collect browser events for subsequent verify steps.
        # Run mode only keeps download events; console/request noise is excluded.
        collector = tester.browser_session.event_collector
        browser_events = await collector.collect(timeout=5.0)
        if browser_events:
            download_only = {k: v for k, v in browser_events.items() if k == 'download'}
            if download_only:
                context_result['browser_events'] = download_only
                logging.debug(f'Browser events captured for step context: {list(download_only.keys())}')

        prev_step_context = StepContext(
            description=action.description,
            result=context_result
        )

        return step_result, prev_step_context

    async def _execute_verify_step(
        self,
        tester,
        verify,
        step_idx: int,
        prev_step_context: Optional[StepContext]
    ) -> Tuple[SubTestStep, StepContext]:
        """Execute a verify step.

        Args:
            tester: UITester instance
            verify: StepVerify configuration
            step_idx: Step index (for logging and result)
            prev_step_context: Context from previous step (optional)

        Returns:
            Tuple of (step_result, new_step_context)
        """
        # Build context if needed
        use_context = verify.args.should_use_context if verify.args else False
        context_info = None

        if use_context and prev_step_context:
            context_info = {
                'last_action': {
                    'description': prev_step_context.description,
                    'result': prev_step_context.result,
                }
            }

        verification_step, verification_result = await tester.verify(
            assertion=verify.assertion,
            execution_context=context_info,
            viewport_only=True,
            full_page=False
        )

        step_result = SubTestStep(
            id=step_idx,
            description=f'verify: {verify.assertion}',
            screenshots=self._resolve_screenshots(verification_step),
            modelIO=str(verification_step.get('modelIO', {})),
            actions=verification_step.get('actions', []),
            status=verification_step.get('status', TestStatus.PASSED),
            errors=verification_step.get('error', ''),
        )

        # Clean up previous context screenshots (already used)
        if prev_step_context and prev_step_context.result:
            prev_step_context.result.pop('before_screenshot', None)
            prev_step_context.result.pop('after_screenshot', None)

        # Verify steps only need lightweight context
        new_context = StepContext(
            description=verify.assertion,
            result={'status': step_result.status.value}
        )

        return step_result, new_context

    # ========================================================================
    # Private Methods - Result Processing
    # ========================================================================

    def _check_monitoring_errors(
        self,
        case_name: str,
        case_status: TestStatus,
        monitoring_data: Dict[str, Any],
        error_messages: List[str],
        ignore_rules: Optional[Dict[str, Any]] = None
    ) -> Tuple[TestStatus, List[str], Dict[str, Any], Dict[str, int]]:
        """Check console and network errors from monitoring data.

        Logic:
        - Case status is primarily based on step execution
        - Console/network errors downgrade PASSED to WARNING
        - FAILED from steps is not overridden

        Args:
            case_name: Name of the case (for logging)
            case_status: Current case status
            monitoring_data: Monitoring data from tester
            error_messages: List of error messages to append to
            ignore_rules: Optional case-specific ignore rules

        Returns:
            Tuple of (updated_case_status, updated_error_messages, messages_data, error_counts)
        """
        # Convert monitoring data to template-expected format
        console_errors = monitoring_data.get('console', [])
        network_data = monitoring_data.get('network', {
            'responses': [],
            'failed_requests': []
        })
        messages_data = {
            'console_error_message': console_errors,
            'network_message': network_data
        }

        # Get ignore rules configuration (case-specific or default)
        ignore_rules = ignore_rules or self.test_specific_config.get('ignore_rules', {})
        has_console_ignore_rules = bool(ignore_rules.get('console', []))
        has_network_ignore_rules = bool(ignore_rules.get('network', []))

        failed_requests = network_data.get('failed_requests', [])
        error_responses = [r for r in network_data.get('responses', []) if r.get('status', 0) >= 400]
        # Only HTTP error responses (4xx/5xx) count toward warning;
        # failed_requests are network-level failures (DNS, blocked, timeout)
        # typically caused by third-party resources and not real API issues.
        network_error_count = len(error_responses)
        failed_request_count = len(failed_requests)
        error_counts = {
            'console_error_count': len(console_errors),
            'network_error_count': network_error_count,
            'failed_request_count': failed_request_count,
        }

        # Do not override step failures; still record counts for reporting
        if case_status == TestStatus.FAILED:
            return case_status, error_messages, messages_data, error_counts

        # ========== 1. Check Console Errors ==========
        # Note: EventCollector has already filtered out ignored errors
        # So console_errors only contains unignored errors
        if console_errors:
            if case_status == TestStatus.PASSED:
                case_status = TestStatus.WARNING
            if not has_console_ignore_rules:
                error_messages.append(f'Console errors detected: {len(console_errors)} error(s)')
                logging.warning(f'{case_name} detected {len(console_errors)} console errors - marking case as WARNING')
            else:
                error_messages.append(f'Unignored console errors detected: {len(console_errors)} error(s)')
                logging.warning(f'{case_name} detected {len(console_errors)} unignored console errors - marking case as WARNING')

        # ========== 2. Check Network Errors (HTTP 4xx/5xx only) ==========
        # Note: EventCollector has already filtered out ignored requests
        # Only error_responses (4xx/5xx) trigger warning; failed_requests are informational only
        if network_error_count > 0:
            if case_status == TestStatus.PASSED:
                case_status = TestStatus.WARNING
            if not has_network_ignore_rules:
                error_messages.append(
                    f'Network errors detected: {len(error_responses)} error responses (4xx/5xx)'
                )
                logging.warning(f'{case_name} detected {len(error_responses)} error responses (4xx/5xx) - marking case as WARNING')
            else:
                error_messages.append(
                    f'Unignored network errors detected: {len(error_responses)} error responses (4xx/5xx)'
                )
                logging.warning(f'{case_name} detected {len(error_responses)} unignored error responses (4xx/5xx) - marking case as WARNING')

        if failed_request_count > 0:
            logging.info(f'{case_name} has {failed_request_count} network-level failed requests (informational, not counted as errors)')

        return case_status, error_messages, messages_data, error_counts

    def _build_case_result(
        self,
        case_name: str,
        case_id: str,
        case_status: TestStatus,
        executed_steps: List[SubTestStep],
        error_messages: List[str],
        monitoring_data: Dict[str, Any],
        start_time: datetime,
        end_time: datetime,
        ignore_rules: Optional[Dict[str, Any]] = None
    ) -> Tuple[SubTestResult, Dict[str, Any]]:
        """Build final case result with monitoring check.

        Args:
            case_name: Name of the case
            case_id: ID of the case (e.g., case_1, case_2)
            case_status: Current case status
            executed_steps: List of executed steps
            error_messages: List of error messages
            monitoring_data: Monitoring data from tester
            start_time: Case start time
            end_time: Case end time
            ignore_rules: Optional ignore rules for this specific case

        Returns:
            Tuple of (SubTestResult, raw_monitoring_data)
        """
        # Build case summary
        total_steps = len(executed_steps)
        passed_steps = sum(1 for s in executed_steps if s.status == TestStatus.PASSED)
        failed_steps = sum(1 for s in executed_steps if s.status == TestStatus.FAILED)
        total_actions = sum(len(getattr(s, 'actions', []) or []) for s in executed_steps)
        network_data = monitoring_data.get('network', {
            'responses': [],
            'failed_requests': []
        })
        api_request_count = len(network_data.get('responses', [])) + len(network_data.get('failed_requests', []))

        final_summary = f'Executed {total_steps} steps: {passed_steps} passed, {failed_steps} failed'

        # Check monitoring errors (use case-specific ignore_rules if provided)
        case_status, error_messages, messages_data, error_counts = self._check_monitoring_errors(
            case_name=case_name,
            case_status=case_status,
            monitoring_data=monitoring_data,
            error_messages=error_messages,
            ignore_rules=ignore_rules
        )

        if error_messages:
            final_summary += f". Errors: {'; '.join(error_messages)}"

        result = SubTestResult(
            sub_test_id=case_id,
            name=case_name,
            status=case_status,
            metrics={
                'total_steps': total_steps,
                'passed_steps': passed_steps,
                'failed_steps': failed_steps,
                'total_actions': total_actions,
                'console_error_count': error_counts.get('console_error_count', 0),
                'network_error_count': error_counts.get('network_error_count', 0),
                'failed_request_count': error_counts.get('failed_request_count', 0),
            },
            steps=executed_steps,
            messages=messages_data,
            start_time=start_time.isoformat(),
            end_time=end_time.isoformat(),
            final_summary=final_summary,
            report=[],
        )
        if api_request_count > 0:
            result.metrics['api_request_count'] = api_request_count

        # Return result and raw monitoring data separately for explicit data flow
        return result, monitoring_data

    # ========================================================================
    # Private Methods - File Operations
    # ========================================================================

    def _save_case_result(
        self,
        case_result: SubTestResult,
        case_name: str,
        case_index: int,
        raw_monitoring_data: Optional[Dict[str, Any]] = None,
        case_config: Optional[Dict[str, Any]] = None
    ) -> None:
        """Save case result to JSON file.

        Args:
            case_result: The case result to save
            case_name: Name of the case (for filename sanitization)
            case_index: Index of the case (for ordering in report)
            raw_monitoring_data: Raw monitoring data to save separately
            case_config: Optional case-specific config (for multi-YAML support)
        """
        if self.report_dir is None:
            timestamp = os.getenv('WEBQA_REPORT_TIMESTAMP') or os.getenv('WEBQA_TIMESTAMP') or datetime.now().strftime('%Y-%m-%d_%H-%M-%S_%f')
            self.report_dir = os.path.join('.', 'reports', f'test_{timestamp}')

        try:
            # Use case-specific config if available, otherwise fall back to default
            target_url = case_config.get('url') if case_config else self.test_specific_config.get('url', '')

            # Call common saving method
            save_test_result_json(
                test_result=case_result,
                report_dir=self.report_dir,
                index=case_index,
                name=case_name,
                category='function',
                mode='run',
                llm_config=self.llm_config,
                browser_config=case_config.get('browser_config') if case_config else self.browser_config,
                target_url=target_url
            )

            # Save monitoring data separately using unified method
            if raw_monitoring_data is not None:
                save_monitor_data_json(
                    monitoring_data=raw_monitoring_data,
                    report_dir=self.report_dir,
                    index=case_index,
                    name=case_name,
                    sub_test_id=case_result.sub_test_id or f'case_{case_index}',
                    category='function',
                    mode='run'
                )
        except Exception as mk_err:
            logging.warning(f"Cannot save case result to '{self.report_dir}': {mk_err}")

    def _clear_case_screenshots(self, case_result: SubTestResult) -> None:
        """Clear large screenshot data from case result after saving to JSON.

        This significantly reduces memory usage when executing many cases,
        as screenshot data is no longer needed in memory after being saved.
        However, if the screenshots are base64 strings and we're not saving
        them as files, we MUST keep them in memory for the final report.

        Args:
            case_result: Case result to clear screenshots from
        """
        try:
            # We don't clear screenshots here anymore because the final HTML report
            # generation depends on these being present in memory (in test_session).
            # If memory becomes an issue for very large test suites, we should
            # implement a lazy-loading mechanism or read from JSON during report generation.

            # For now, we only clear very large modelIO strings to save some memory
            for step in case_result.steps:
                if step.modelIO and len(step.modelIO) > 20000:
                    step.modelIO = '[cleared after save]'

            logging.debug(f'Cleaned up large data for case: {case_result.name}')
        except Exception as e:
            logging.warning(f'Failed to clear large data: {e}')

"""Case Executor - Execute test cases defined in YAML with ai/aiAssert steps.

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
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from webqa_agent.browser import BrowserSession, BrowserSessionPool
from webqa_agent.data import (CaseStep, StepContext, SubTestResult,
                              SubTestStep, TestConfiguration, TestStatus)
from webqa_agent.utils import Display
from webqa_agent.utils.get_log import test_id_var
from webqa_agent.utils.log_icon import icon


class CaseExecutor:
    """Executor for YAML-defined test cases with action/verify steps.

    This class handles:
    - Executing multiple test cases serially
    - Managing browser sessions for each case
    - Executing action and verify steps
    - Collecting monitoring data (console/network errors)
    - Saving test results to JSON files
    """

    def __init__(self, llm_config: Dict[str, Any], test_config: TestConfiguration, report_dir: Optional[str] = None):
        """Initialize case executor.

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

    async def execute_cases(
        self,
        cases: List[Dict[str, Any]],
        workers: int = 1,
    ) -> List[SubTestResult]:
        """Execute all cases using worker pool pattern (unified
        serial/parallel).

        Args:
            cases: List of case configurations from YAML
            workers: Number of parallel workers (1 = serial, >1 = parallel)

        Returns:
            List of SubTestResult for each case
        """
        total_cases = len(cases)
        mode_str = f'parallel ({workers} workers)' if workers > 1 else 'serial'
        logging.info(f"{icon['rocket']} Starting {mode_str} execution: {total_cases} cases")

        # Create session pool (auto-initialized)
        session_pool = BrowserSessionPool(pool_size=workers, browser_config=self.browser_config)

        # Shared state
        case_queue: asyncio.Queue = asyncio.Queue()
        results: List[SubTestResult] = []
        results_lock = asyncio.Lock()
        completed_count = 0

        # Fill queue
        for idx, case in enumerate(cases, 1):
            await case_queue.put((idx, case))

        async def worker(worker_id: int):
            """Worker that pulls cases from queue until sentinel."""
            nonlocal completed_count

            while True:
                item = await case_queue.get()
                if item is None:  # Sentinel - exit
                    break

                idx, case = item
                case_name = case.get('name', f'Case {idx}')
                case_id = case.get('case_id', f'case_{idx}')

                # Extract browser config for this case
                browser_cfg = case.get('_config', {}).get('browser_config', self.browser_config)

                # Set test_id context for logging (imitating graph.py style)
                # Including both ID and Name for maximum clarity
                log_context = f'Run Case Test | {case_id} | {case_name}'
                token = test_id_var.set(log_context)

                session = None
                case_result = None

                try:
                    logging.info(f"Worker {worker_id}: Starting case '{case_name}' ({idx}/{total_cases})")
                    session = await session_pool.acquire(browser_config=browser_cfg, timeout=120.0)

                    with Display.display(case_name):  # pylint: disable=not-callable
                        case_result = await self.execute_single_case(session=session, case=case, case_index=idx)

                    async with results_lock:
                        results.append(case_result)
                        completed_count += 1

                    status_icon = icon['check'] if case_result.status == TestStatus.PASSED else icon['cross']
                    logging.info(f"{status_icon} Worker {worker_id}: '{case_name}' - {case_result.status} ({completed_count}/{total_cases})")

                except Exception as e:
                    logging.error(f"Worker {worker_id}: Exception in '{case_name}': {e}", exc_info=True)
                    async with results_lock:
                        completed_count += 1
                        results.append(SubTestResult(
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
                        self._save_case_result(case_result, case_name, idx, case_config=case_config)
                        self._clear_case_screenshots(case_result)

                    if session:
                        failed = case_result is None or case_result.status == TestStatus.FAILED
                        if case_queue.qsize() == 0:
                            await session.close()
                        else:
                            await session_pool.release(session, failed=failed)

                    case_queue.task_done()

        try:
            # Start workers and wait for completion
            worker_tasks = [asyncio.create_task(worker(i)) for i in range(workers)]
            await case_queue.join()

            # Stop workers
            for _ in range(workers):
                await case_queue.put(None)
            await asyncio.gather(*worker_tasks, return_exceptions=True)

        finally:
            await session_pool.close_all()

        # Sort by original index
        results.sort(key=lambda r: next((i for i, c in enumerate(cases, 1) if c.get('name') == r.name), 999))
        logging.info(f"{icon['check']} Execution completed: {len(results)}/{total_cases} cases")
        return results

    async def execute_single_case(self, session: BrowserSession, case: Dict[str, Any], case_index: int = 1) -> SubTestResult:
        """Execute a single test case.

        Args:
            session: Browser session
            case: Case configuration {"name": "...", "steps": [...], "_config": {...}}
            case_index: Index of the case (for logging)

        Returns:
            SubTestResult containing execution results
        """
        case_name = case.get('name', f'Unnamed Case {case_index}')
        start_time = datetime.now()

        # Get case-specific config if available (for multi-YAML support)
        case_config = case.get('_config', {})
        url = case_config.get('url') or self.test_specific_config.get('url')
        cookies = case_config.get('cookies') or self.test_specific_config.get('cookies')
        ignore_rules = case_config.get('ignore_rules') or self.test_specific_config.get('ignore_rules', {})

        # Initialize tester and execute steps
        tester = await self._initialize_tester(session, case_name, url=url, cookies=cookies, ignore_rules=ignore_rules)

        # Execute steps
        executed_steps, case_status, error_messages, prev_step_context = await self._execute_steps(
            tester, case.get('steps', [])
        )

        # Get monitoring data and cleanup
        monitoring_data = await self._end_session(tester)
        await self._cleanup_tester(tester, case_name)

        # Build final result
        end_time = datetime.now()
        return self._build_case_result(
            case_name=case_name,
            case_status=case_status,
            executed_steps=executed_steps,
            error_messages=error_messages,
            monitoring_data=monitoring_data,
            start_time=start_time,
            end_time=end_time,
            ignore_rules=ignore_rules
        )

    # ========================================================================
    # Private Methods - Tester Lifecycle
    # ========================================================================

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
        from webqa_agent.testers.function_tester import UITester

        _ignore_rules = ignore_rules or self.test_specific_config.get('ignore_rules', {})
        tester = UITester(
            llm_config=self.llm_config,
            browser_session=session,
            ignore_rules=_ignore_rules
        )
        await tester.initialize()
        tester.set_current_test_name(case_name)

        _url = url or self.test_specific_config.get('url')
        _cookies = cookies or self.test_specific_config.get('cookies')
        await tester.start_session(url=_url, cookies=_cookies)
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

    # ========================================================================
    # Private Methods - Step Execution
    # ========================================================================

    async def _execute_steps(
        self,
        tester,
        steps: List[Dict[str, Any]]
    ) -> Tuple[List[SubTestStep], TestStatus, List[str], Optional[StepContext]]:
        """Execute all steps in a case.

        Args:
            tester: UITester instance
            steps: List of step configurations

        Returns:
            Tuple of (executed_steps, case_status, error_messages, prev_step_context)
        """
        executed_steps = []
        case_status = TestStatus.PASSED
        error_messages = []
        prev_step_context: Optional[StepContext] = None

        for step_idx, step in enumerate(steps, 1):
            try:
                parsed_step = CaseStep.model_validate(step)

                if parsed_step.step_type == 'action':
                    logging.info(f'Executing step {step_idx}: {parsed_step.action}')
                    step_result, prev_step_context = await self._execute_action_step(
                        tester, parsed_step.action, step_idx
                    )
                elif parsed_step.step_type == 'verify':
                    logging.info(f'Executing step {step_idx}: {parsed_step.verify}')
                    step_result, prev_step_context = await self._execute_verify_step(
                        tester, parsed_step.verify, step_idx, prev_step_context
                    )
                else:
                    raise ValueError(f'Unsupported step type: {parsed_step.step_type}')

                executed_steps.append(step_result)

                # Update case status
                if step_result.status == TestStatus.FAILED:
                    case_status = TestStatus.FAILED
                    error_messages.append(f'Step {step_idx} failed: {step_result.errors}')
                elif step_result.status == TestStatus.WARNING and case_status == TestStatus.PASSED:
                    case_status = TestStatus.WARNING

            except Exception as e:
                raise e

        return executed_steps, case_status, error_messages, prev_step_context

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

        execution_steps_dict, execution_result = await tester.action(
            test_step=action.description,
            file_path=file_path,
            viewport_only=True,
            full_page=True
        )

        step_result = SubTestStep(
            id=step_idx,
            description=f'action: {action.description}',
            screenshots=execution_steps_dict.get('screenshots', []),
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
            screenshots=verification_step.get('screenshots', []),
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
    ) -> Tuple[TestStatus, List[str], Dict[str, Any]]:
        """Check console and network errors from monitoring data.

        Logic:
        - If case already FAILED from steps, don't override
        - If no ignore rules configured, any error causes FAILED
        - If ignore rules configured, only unignored errors cause FAILED

        Args:
            case_name: Name of the case (for logging)
            case_status: Current case status
            monitoring_data: Monitoring data from tester
            error_messages: List of error messages to append to
            ignore_rules: Optional case-specific ignore rules

        Returns:
            Tuple of (updated_case_status, updated_error_messages, messages_data)
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

        # Only check errors if case status is currently PASSED (don't override step failures)
        if case_status != TestStatus.PASSED:
            return case_status, error_messages, messages_data

        # ========== 1. Check Console Errors ==========
        # Note: ConsoleCheck has already filtered out ignored errors
        # So console_errors only contains unignored errors
        if console_errors:
            if not has_console_ignore_rules:
                # No ignore rules configured, any console error causes failure
                case_status = TestStatus.FAILED
                error_messages.append(f'Console errors detected: {len(console_errors)} error(s)')
                logging.warning(f'{case_name} detected {len(console_errors)} console errors - marking case as FAILED')
            else:
                # Ignore rules configured, but these errors were not filtered
                # They don't match any ignore rules, so they should cause failure
                case_status = TestStatus.FAILED
                error_messages.append(f'Unignored console errors detected: {len(console_errors)} error(s)')
                logging.warning(f'{case_name} detected {len(console_errors)} unignored console errors - marking case as FAILED')

        # ========== 2. Check Network Errors ==========
        # Note: NetworkCheck has already filtered out ignored requests
        # So failed_requests and error responses only contain unignored errors
        failed_requests = network_data.get('failed_requests', [])
        error_responses = [r for r in network_data.get('responses', []) if r.get('status', 0) >= 400]

        network_error_count = len(failed_requests) + len(error_responses)

        if network_error_count > 0:
            if not has_network_ignore_rules:
                # No ignore rules configured, any network error causes failure
                case_status = TestStatus.FAILED
                error_messages.append(
                    f'Network errors detected: {len(failed_requests)} failed requests, '
                    f'{len(error_responses)} error responses'
                )
                logging.warning(f'{case_name} detected {len(failed_requests)} failed requests, {len(error_responses)} error responses - marking case as FAILED')
            else:
                # Ignore rules configured, but these errors were not filtered
                # They don't match any ignore rules, so they should cause failure
                case_status = TestStatus.FAILED
                error_messages.append(
                    f'Unignored network errors detected: {len(failed_requests)} failed requests, '
                    f'{len(error_responses)} error responses'
                )
                logging.warning(f'{case_name} detected {len(failed_requests)} unignored failed requests, {len(error_responses)} unignored error responses - marking case as FAILED')

        return case_status, error_messages, messages_data

    def _build_case_result(
        self,
        case_name: str,
        case_status: TestStatus,
        executed_steps: List[SubTestStep],
        error_messages: List[str],
        monitoring_data: Dict[str, Any],
        start_time: datetime,
        end_time: datetime,
        ignore_rules: Optional[Dict[str, Any]] = None
    ) -> SubTestResult:
        """Build final case result with monitoring check.

        Args:
            case_name: Name of the case
            case_status: Current case status
            executed_steps: List of executed steps
            error_messages: List of error messages
            monitoring_data: Monitoring data from tester
            start_time: Case start time
            end_time: Case end time
            ignore_rules: Optional ignore rules for this specific case

        Returns:
            Complete SubTestResult
        """
        # Build case summary
        total_steps = len(executed_steps)
        passed_steps = sum(1 for s in executed_steps if s.status == TestStatus.PASSED)
        failed_steps = sum(1 for s in executed_steps if s.status == TestStatus.FAILED)

        final_summary = f'Executed {total_steps} steps: {passed_steps} passed, {failed_steps} failed'

        # Check monitoring errors (use case-specific ignore_rules if provided)
        case_status, error_messages, messages_data = self._check_monitoring_errors(
            case_name=case_name,
            case_status=case_status,
            monitoring_data=monitoring_data,
            error_messages=error_messages,
            ignore_rules=ignore_rules
        )

        if error_messages:
            final_summary += f". Errors: {'; '.join(error_messages)}"

        return SubTestResult(
            name=case_name,
            status=case_status,
            metrics={'total_steps': total_steps, 'passed_steps': passed_steps, 'failed_steps': failed_steps},
            steps=executed_steps,
            messages=messages_data,
            start_time=start_time.isoformat(),
            end_time=end_time.isoformat(),
            final_summary=final_summary,
            report=[],
        )

    # ========================================================================
    # Private Methods - File Operations
    # ========================================================================

    def _save_case_result(
        self,
        case_result: SubTestResult,
        case_name: str,
        case_index: int,
        case_config: Optional[Dict[str, Any]] = None
    ) -> None:
        """Save case result to JSON file.

        Args:
            case_result: The case result to save
            case_name: Name of the case (for filename sanitization)
            case_index: Index of the case (for ordering in report)
            case_config: Optional case-specific config (for multi-YAML support)
        """
        if self.report_dir is None:
            timestamp = os.getenv('WEBQA_REPORT_TIMESTAMP') or os.getenv('WEBQA_TIMESTAMP') or datetime.now().strftime('%Y-%m-%d_%H-%M-%S_%f')
            self.report_dir = os.path.join('.', 'reports', f'test_{timestamp}')

        try:
            os.makedirs(self.report_dir, exist_ok=True)
            report_dir_path = Path(self.report_dir).resolve()

            # Sanitize case name for filename with index prefix for ordering
            safe_case_name = ''.join(c if c.isalnum() or c in ('-', '_', ' ') else '_' for c in case_name)
            case_result_path = report_dir_path / f'test_data_{case_index:03d}_{safe_case_name}.json'

            # Use case-specific config if available, otherwise fall back to default
            target_url = case_config.get('url') if case_config else self.test_specific_config.get('url', '')
            ignore_rules = case_config.get('ignore_rules') if case_config else self.test_specific_config.get('ignore_rules', {})
            source_file = case_config.get('_source_file') if case_config else None

            # Add config information for template compatibility
            case_dict = case_result.model_dump()
            case_dict['case_index'] = case_index  # Save index for ordering
            case_dict['config'] = {
                'target_url': target_url,
                'browser_config': case_config.get('browser_config') if case_config else self.browser_config,
                'env': self.test_specific_config.get('env', ''),
                'llm_model': self.llm_config.get('model', ''),
                'filter_model': self.llm_config.get('filter_model', ''),
                'ignore_rules': ignore_rules,
            }

            # Add source file info if available (for multi-config mode)
            if source_file:
                case_dict['config']['source_file'] = source_file

            # Save as list format to match template expectations
            with open(case_result_path, 'w', encoding='utf-8') as f:
                json.dump([case_dict], f, indent=2, ensure_ascii=False, default=str)
            logging.debug(f'Case result saved to: {case_result_path}')
        except Exception as mk_err:
            logging.warning(f"Cannot save case result to '{self.report_dir}': {mk_err}")

    def _clear_case_screenshots(self, case_result: SubTestResult) -> None:
        """Clear large screenshot data from case result after saving to JSON.

        This significantly reduces memory usage when executing many cases,
        as screenshot data is no longer needed in memory after being saved.

        Args:
            case_result: Case result to clear screenshots from
        """
        try:
            # Clear screenshots from each step
            for step in case_result.steps:
                if step.screenshots:
                    step.screenshots = []  # Clear screenshot data

                # Also clear modelIO if it's very large (can contain duplicate data)
                if step.modelIO and len(step.modelIO) > 10000:
                    step.modelIO = '[cleared after save]'

            logging.debug(f'Cleared screenshot data for case: {case_result.name}')
        except Exception as e:
            logging.warning(f'Failed to clear screenshots: {e}')

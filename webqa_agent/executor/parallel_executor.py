import asyncio
import logging
import os
from typing import Dict, List, Optional

# Session ID constants
SECURITY_TEST_NO_SESSION_ID = "security_test_no_session"

from webqa_agent.browser.session import BrowserSessionManager
from webqa_agent.data import ParallelTestSession, TestConfiguration, TestResult, TestStatus, TestType
from webqa_agent.data.test_structures import get_category_for_test_type
from webqa_agent.executor.result_aggregator import ResultAggregator
from webqa_agent.executor.test_runners import (
    ButtonTestRunner,
    LighthouseTestRunner,
    SecurityTestRunner,
    UIAgentLangGraphRunner,
    UXTestRunner,
    WebBasicCheckRunner,
)


class ParallelTestExecutor:
    """Parallel test execution manager."""

    def __init__(self, max_concurrent_tests: int = 4):
        self.max_concurrent_tests = max_concurrent_tests
        self.session_manager = BrowserSessionManager()
        self.result_aggregator = ResultAggregator()

        # Test runners mapping
        self.test_runners = {
            TestType.UI_AGENT_LANGGRAPH: UIAgentLangGraphRunner(),
            TestType.UX_TEST: UXTestRunner(),
            TestType.PERFORMANCE: LighthouseTestRunner(),
            TestType.WEB_BASIC_CHECK: WebBasicCheckRunner(),
            TestType.BUTTON_TEST: ButtonTestRunner(),
            TestType.SECURITY_TEST: SecurityTestRunner(),
        }

        # Execution tracking
        self.running_tests: Dict[str, asyncio.Task] = {}
        self.completed_tests: Dict[str, TestResult] = {}

    async def execute_parallel_tests(self, test_session: ParallelTestSession) -> ParallelTestSession:
        """Execute tests in parallel with proper isolation.

        Args:
            test_session: Session containing test configurations

        Returns:
            Updated session with results
        """
        logging.debug(f"Starting parallel test execution for session: {test_session.session_id}")
        test_session.start_session()

        try:
            # Get enabled tests
            enabled_tests = test_session.get_enabled_tests()
            if not enabled_tests:
                logging.warning("No enabled tests found")
                return test_session

            # Execute tests in batches to respect concurrency limits
            await self._execute_tests_in_batches(test_session, enabled_tests)

            test_session.complete_session()
        except asyncio.CancelledError:
            logging.warning("Parallel test execution cancelled – generating partial report.")
            raise
        except Exception as e:
            logging.error(f"Error in parallel test execution: {e}")
            raise
        finally:
            # Consolidated cleanup, aggregation, and report generation
            await self._finalize_session(test_session)

        return test_session

    async def _execute_tests_in_batches(
        self, test_session: ParallelTestSession, enabled_tests: List[TestConfiguration]
    ):
        """Execute tests in concurrent batches."""

        # Resolve dependencies and create execution order
        execution_batches = self._resolve_test_dependencies(enabled_tests)

        for batch_idx, test_batch in enumerate(execution_batches):
            logging.debug(f"Executing batch {batch_idx + 1}/{len(execution_batches)} with {len(test_batch)} tests")

            # Create semaphore for this batch
            semaphore = asyncio.Semaphore(min(self.max_concurrent_tests, len(test_batch)))

            # Create tasks for this batch
            batch_tasks = []
            for test_config in test_batch:
                task = asyncio.create_task(self._execute_single_test(test_session, test_config, semaphore))
                batch_tasks.append(task)
                self.running_tests[test_config.test_id] = task

            # Wait for batch completion
            try:
                try:
                    results = await asyncio.gather(*batch_tasks, return_exceptions=True)
                except asyncio.CancelledError:
                    logging.warning("Batch was cancelled – collecting completed task results.")

                    results = []
                    for task in batch_tasks:
                        if task.done():
                            try:
                                results.append(task.result())
                            except Exception as e:
                                results.append(e)
                        else:
                            # Task not finished (still cancelled/pending)
                            results.append(asyncio.CancelledError())
                    cancelled_in_batch = True
                else:
                    cancelled_in_batch = False

                # Process results
                for i, result in enumerate(results):
                    test_config = test_batch[i]
                    if isinstance(result, Exception):
                        if isinstance(result, asyncio.CancelledError):
                            logging.warning(f"Test {test_config.test_name} was cancelled.")
                            cancelled_result = TestResult(
                                test_id=test_config.test_id,
                                test_type=test_config.test_type,
                                test_name=test_config.test_name,
                                status=TestStatus.CANCELLED,
                                category=get_category_for_test_type(test_config.test_type),
                                error_message="Test was cancelled",
                            )
                            test_session.update_test_result(test_config.test_id, cancelled_result)
                        else:
                            logging.error(f"Test {test_config.test_name} failed with exception: {result}")
                            failed_result = TestResult(
                                test_id=test_config.test_id,
                                test_type=test_config.test_type,
                                test_name=test_config.test_name,
                                status=TestStatus.FAILED,
                                category=get_category_for_test_type(test_config.test_type),
                                error_message=str(result),
                            )
                            test_session.update_test_result(test_config.test_id, failed_result)
                    else:
                        test_session.update_test_result(test_config.test_id, result)

            finally:
                # Clean up batch tasks
                for test_config in test_batch:
                    self.running_tests.pop(test_config.test_id, None)

            logging.debug(f"Batch {batch_idx + 1} completed")
            if cancelled_in_batch:
                # Propagate cancellation after processing.
                raise asyncio.CancelledError()

    async def _execute_single_test(
        self, test_session: ParallelTestSession, test_config: TestConfiguration, semaphore: asyncio.Semaphore
    ) -> TestResult:
        """Execute a single test with proper isolation."""

        async with semaphore:
            test_context = test_session.test_contexts[test_config.test_id]
            test_context.start_execution()

            logging.debug(f"Starting test: {test_config.test_name} ({test_config.test_type.value})")

            try:
                if test_config.test_type in [
                    TestType.UI_AGENT_LANGGRAPH,
                    TestType.UX_TEST,
                    TestType.BUTTON_TEST,
                    TestType.WEB_BASIC_CHECK,
                ]:

                    # Create isolated browser session
                    session = await self.session_manager.create_session(test_config.browser_config)
                    test_context.session_id = session.session_id

                    # Navigate to target URL
                    await session.navigate_to(
                        test_session.target_url, cookies=test_config.test_specific_config.get("cookies", None)
                    )

                elif test_config.test_type == TestType.SECURITY_TEST:
                    # Security tests don't need browser sessions, use a placeholder
                    session = None
                    test_context.session_id = SECURITY_TEST_NO_SESSION_ID

                else:
                    session = await self.session_manager.browser_session(test_config.browser_config)
                    test_context.session_id = session.session_id

                # Get appropriate test runner
                runner = self.test_runners.get(test_config.test_type)
                if not runner:
                    raise ValueError(f"No runner available for test type: {test_config.test_type}")

                # Execute test
                result = await runner.run_test(
                    session=session,
                    test_config=test_config,
                    llm_config=test_session.llm_config,
                    target_url=test_session.target_url,
                )

                # Mark execution outcome according to the returned result status.
                is_success = result.status == TestStatus.PASSED
                test_context.complete_execution(
                    success=is_success, error_message=result.error_message if not is_success else ""
                )
                result.start_time = test_context.start_time
                result.end_time = test_context.end_time
                result.duration = test_context.duration

                logging.debug(f"Test completed successfully: {test_config.test_name}")
                return result

            except Exception as e:
                error_msg = f"Test execution failed: {str(e)}"
                logging.error(f"Test failed: {test_config.test_name} - {error_msg}")

                test_context.complete_execution(success=False, error_message=error_msg)

                # Create failed result
                result = TestResult(
                    test_id=test_config.test_id,
                    test_type=test_config.test_type,
                    test_name=test_config.test_name,
                    status=TestStatus.FAILED,
                    category=get_category_for_test_type(test_config.test_type),
                    start_time=test_context.start_time,
                    end_time=test_context.end_time,
                    duration=test_context.duration,
                    error_message=error_msg,
                )
                return result

            except asyncio.CancelledError:
                # The task was cancelled (e.g., by cancel_test / KeyboardInterrupt).
                logging.warning(f"Test cancelled: {test_config.test_name}")

                test_context.complete_execution(success=False, error_message="Test was cancelled")

                cancelled_result = TestResult(
                    test_id=test_config.test_id,
                    test_type=test_config.test_type,
                    test_name=test_config.test_name,
                    status=TestStatus.CANCELLED,
                    category=get_category_for_test_type(test_config.test_type),
                    start_time=test_context.start_time,
                    end_time=test_context.end_time,
                    duration=test_context.duration,
                    error_message="Test was cancelled",
                )

                return cancelled_result

            finally:
                # Clean up browser session
                if test_context.session_id and test_context.session_id != SECURITY_TEST_NO_SESSION_ID:
                    await self.session_manager.close_session(test_context.session_id)

    def _resolve_test_dependencies(self, tests: List[TestConfiguration]) -> List[List[TestConfiguration]]:
        """Resolve test dependencies and return execution batches.

        Returns:
            List of test batches where each batch can run in parallel
        """
        # dependencies for login
        independent_tests = [test for test in tests if not test.dependencies]
        dependent_tests = [test for test in tests if test.dependencies]

        batches = []

        # First batches: independent tests (split by max_concurrent_tests)
        if independent_tests:
            # Split independent tests into batches based on max_concurrent_tests
            for i in range(0, len(independent_tests), self.max_concurrent_tests):
                batch = independent_tests[i : i + self.max_concurrent_tests]
                batches.append(batch)

        # Additional batches for dependent tests (also split by max_concurrent_tests)
        if dependent_tests:
            for i in range(0, len(dependent_tests), self.max_concurrent_tests):
                batch = dependent_tests[i : i + self.max_concurrent_tests]
                batches.append(batch)

        return batches

    async def cancel_test(self, test_id: str):
        """Cancel a running test."""
        if test_id in self.running_tests:
            task = self.running_tests[test_id]
            task.cancel()
            logging.debug(f"Test cancelled: {test_id}")

    async def cancel_all_tests(self):
        """Cancel all running tests."""
        for test_id in list(self.running_tests.keys()):
            await self.cancel_test(test_id)

        await self.session_manager.close_all_sessions()
        logging.debug("All tests cancelled")

    def get_running_tests(self) -> List[str]:
        """Get list of currently running test IDs."""
        return list(self.running_tests.keys())

    def get_test_status(self, test_id: str) -> Optional[TestStatus]:
        """Get status of a specific test."""
        if test_id in self.running_tests:
            return TestStatus.RUNNING
        elif test_id in self.completed_tests:
            return self.completed_tests[test_id].status
        return None

    async def _finalize_session(self, test_session: ParallelTestSession):
        """Close sessions, aggregate results, and generate reports for the given session.

        This helper consolidates cleanup and report generation logic to avoid duplication
        across normal completion, cancellation, and error paths.
        """
        # Ensure all browser sessions are closed
        await self.session_manager.close_all_sessions()

        # Aggregate results
        aggregated_results = await self.result_aggregator.aggregate_results(test_session)
        test_session.aggregated_results = aggregated_results

        # Generate JSON & HTML reports
        report_path = await self.result_aggregator.generate_json_report(test_session)
        test_session.report_path = report_path

        report_dir = os.path.dirname(report_path)
        html_path = self.result_aggregator.generate_html_report_fully_inlined(
            test_session, report_dir=report_dir
        )
        test_session.html_report_path = html_path

        logging.debug(f"Report generated: {report_path}")
        logging.debug(f"HTML report generated: {html_path}")

        # Mark session as completed if not already done
        if test_session.end_time is None:
            test_session.complete_session()

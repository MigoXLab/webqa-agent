"""Case Executor - Execute test cases defined in YAML with ai/aiAssert steps.

This module handles:
1. Serial execution of test cases from YAML configuration
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
from typing import Any, Dict, List, Optional

from webqa_agent.browser import BrowserSession, BrowserSessionPool
from webqa_agent.data import (SubTestReport, SubTestResult, SubTestStep,
                              TestConfiguration, TestStatus)
from webqa_agent.utils import Display
from webqa_agent.utils.log_icon import icon


class CaseExecutor:
    """Executor for YAML-defined test cases with ai/aiAssert steps."""

    def __init__(self, llm_config: Dict[str, Any], test_config: TestConfiguration):
        """Initialize case executor.

        Args:
            llm_config: LLM configuration for AI operations
            test_config: Test configuration
        """
        self.session_pool: Optional[BrowserSessionPool] = None
        self.llm_config = llm_config
        self.test_config = test_config
        self.browser_config = test_config.browser_config
        self.report_config = test_config.report_config
        self.test_specific_config = test_config.test_specific_config
        self.report_dir = None

    def _save_case_result(self, case_result: SubTestResult, case_name: str):
        """Save case result to JSON file.

        Args:
            case_result: The case result to save
            case_name: Name of the case (for filename)
        """
        if self.report_dir is None:
            timestamp = os.getenv('WEBQA_REPORT_TIMESTAMP') or os.getenv('WEBQA_TIMESTAMP')
            self.report_dir = f'./reports/test_{timestamp}'

        try:
            os.makedirs(self.report_dir, exist_ok=True)
            report_dir_path = Path(self.report_dir).resolve()

            # Sanitize case name for filename
            safe_case_name = ''.join(c if c.isalnum() or c in ('-', '_', ' ') else '_' for c in case_name)
            case_result_path = report_dir_path / f'test_data_{safe_case_name}.json'

            # Add config information for template compatibility
            case_dict = case_result.model_dump()
            case_dict['config'] = {
                'target_url': self.test_specific_config.get('url', ''),
                'browser_config': self.browser_config,
                'env': self.test_specific_config.get('env', ''),
                'llm_model': self.llm_config.get('model', ''),
                'filter_model': self.llm_config.get('filter_model', '')
            }

            # Save as list format to match template expectations
            with open(case_result_path, 'w', encoding='utf-8') as f:
                json.dump([case_dict], f, indent=2, ensure_ascii=False, default=str)
            logging.debug(f'Case result saved to: {case_result_path}')
        except Exception as mk_err:
            logging.warning(f"Cannot save case result to '{self.report_dir}': {mk_err}")


    async def execute_cases(self, cases: List[Dict[str, Any]]) -> List[SubTestResult]:
        """Execute all cases serially.

        Args:
            cases: List of case configurations from YAML
                   [{"name": "case1", "steps": [...]}, ...]

        Returns:
            List of SubTestResult for each case
        """
        results = []
        total_cases = len(cases)

        for idx, case in enumerate(cases, 1):
            case_name = case.get('name', f'Case {idx}')
            logging.info(f"{icon['running']} Executing case {idx}/{total_cases}: {case_name}")

            # Create a new session for each case
            session_pool = BrowserSessionPool(browser_config=self.browser_config)
            await session_pool.initialize()
            session = await session_pool.acquire()

            try:
                with Display.display(case_name):
                    # Execute case
                    case_result = None  # Initialize to avoid UnboundLocalError
                    try:
                        case_result = await self.execute_single_case(session=session, case=case, case_index=idx)
                        results.append(case_result)

                        status_icon = icon['check'] if case_result.status == TestStatus.PASSED else icon['cross']
                        logging.info(f'{status_icon} Case {idx}/{total_cases} completed: {case_name} - {case_result.status}')

                    except Exception as e:
                        logging.error(f"{icon['cross']} Case {idx}/{total_cases} failed: {case_name} - {str(e)}")
                        # Create failed result for the case
                        case_result = SubTestResult(
                            name=case_name,
                            status=TestStatus.FAILED,
                            metrics={},
                            steps=[],
                            messages={
                                'error': str(e),
                                'console_error_message': [],
                                'network_message': {
                                    'responses': [],
                                    'failed_requests': []
                                }
                            },
                            start_time=datetime.now().isoformat(),
                            end_time=datetime.now().isoformat(),
                            final_summary=f'Case execution failed: {str(e)}',
                            report=[SubTestReport(title='Execution Error', issues=str(e))],
                        )
                        results.append(case_result)

                    finally:
                        # Save case result to json file (only if case_result was created)
                        if case_result is not None:
                            self._save_case_result(case_result, case_name)

            finally:
                # Close session after each case
                if session:
                    await session_pool.release(session)
                await session_pool.close_all()

        return results


    async def execute_single_case(self, session: BrowserSession, case: Dict[str, Any], case_index: int = 1) -> SubTestResult:
        """Execute a single test case.

        Args:
            case: Case configuration {"name": "...", "steps": [...]}
            case_index: Index of the case (for logging)

        Returns:
            SubTestResult containing execution results
        """
        case_name = case.get('name', f'Unnamed Case {case_index}')
        steps = case.get('steps', [])

        start_time = datetime.now()
        executed_steps = []
        case_status = TestStatus.PASSED
        error_messages = []

        try:
            from webqa_agent.testers.function_tester import UITester

            # Set current test name for UI tester
            tester = UITester(
                llm_config=self.llm_config,
                browser_session=session
            )
            await tester.initialize()

            tester.set_current_test_name(case.get('name'))
            await tester.start_session(url=self.test_specific_config.get('url'), cookies=self.test_specific_config.get('cookies'))

            # Execute each step
            for step_idx, step in enumerate(steps, 1):
                step_result = None
                try:
                    if not isinstance(step, dict) or len(step) != 1:
                        logging.warning(f'Invalid step format: {step}')
                        continue

                    action_type, action_value = list(step.items())[0]

                    if action_type == 'action':
                        # Execute AI action
                        file_path = None
                        if isinstance(action_value, dict):
                            # Handle complex instruction format
                            args = action_value.get('args', {})
                            file_path = args.get('file_path')
                            action_value = action_value.get('case', '')

                        # Execute action through UI tester
                        execution_steps_dict, execution_result = await tester.action(test_step=action_value, file_path=file_path)
                        modelIO = str(execution_steps_dict.get('modelIO', {}))
                        step_result = SubTestStep(
                            id=step_idx,
                            description=f'action: {action_value}',
                            screenshots=execution_steps_dict.get('screenshots', []),
                            modelIO=modelIO,
                            actions=execution_steps_dict.get('actions', []),
                            status=execution_steps_dict.get('status', TestStatus.PASSED),
                            errors=execution_steps_dict.get('error', ''),
                        )

                    elif action_type == 'verify':
                        # Execute AI assertion
                        verification_step, verification_result = await tester.verify(action_value)
                        modelIO = str(verification_step.get('modelIO', {}))
                        step_result = SubTestStep(
                            id=step_idx,
                            description=f'verify: {action_value}',
                            screenshots=verification_step.get('screenshots', []),
                            modelIO=modelIO,
                            actions=verification_step.get('actions', []),
                            status=verification_step.get('status', TestStatus.PASSED),
                            errors=verification_step.get('error', ''),
                        )
                    else:
                        raise ValueError(f'Unsupported step type: {action_type}')

                    # Add successful step to results
                    executed_steps.append(step_result)

                    # Update case status based on step result
                    if step_result.status == TestStatus.FAILED:
                        case_status = TestStatus.FAILED
                        error_messages.append(f'Step {step_idx} failed: {step_result.errors}')
                    elif step_result.status == TestStatus.WARNING and case_status == TestStatus.PASSED:
                        case_status = TestStatus.WARNING

                except Exception as e:
                    logging.error(f"{icon['cross']} Step {step_idx} execution error: {str(e)}")
                    # Create failed step
                    failed_step = SubTestStep(
                        id=step_idx,
                        description=f"{action_type if 'action_type' in locals() else 'unknown'}: {action_value if 'action_value' in locals() else str(step)}",
                        screenshots=[],
                        modelIO='',
                        actions=[],
                        status=TestStatus.FAILED,
                        errors=f'Step execution failed: {str(e)}',
                    )
                    executed_steps.append(failed_step)
                    case_status = TestStatus.FAILED
                    error_messages.append(f'Step {step_idx} exception: {str(e)}')

            # End session after all steps and get monitoring data
            monitoring_data = await tester.end_session()

        except Exception as e:
            logging.error(f"{icon['cross']} Case {case_index} execution error: {str(e)}")
            case_status = TestStatus.FAILED
            error_messages.append(f'Case execution failed: {str(e)}')
            monitoring_data = {}

        # Always calculate end time and summary after try-except
        end_time = datetime.now()

        # Build case summary
        total_steps = len(executed_steps)
        passed_steps = sum(1 for s in executed_steps if s.status == TestStatus.PASSED)
        failed_steps = sum(1 for s in executed_steps if s.status == TestStatus.FAILED)

        final_summary = f'Executed {total_steps} steps: {passed_steps} passed, {failed_steps} failed'
        if error_messages:
            final_summary += f". Errors: {'; '.join(error_messages)}"

        # Convert monitoring data to template-expected format
        messages_data = {
            'console_error_message': monitoring_data.get('console', []),
            'network_message': monitoring_data.get('network', {
                'responses': [],
                'failed_requests': []
            })
        }

        return SubTestResult(
            name=case_name,
            status=case_status,
            metrics={'total_steps': total_steps, 'passed_steps': passed_steps, 'failed_steps': failed_steps},
            steps=executed_steps,
            messages=messages_data,  # Dict structure
            start_time=start_time.isoformat(),
            end_time=end_time.isoformat(),
            final_summary=final_summary,
        )

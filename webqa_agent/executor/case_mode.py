"""Case Mode - Execute test cases defined in YAML configuration.

This mode is activated when the YAML configuration contains a 'cases' field.
It executes test cases serially with ai/aiAssert steps.
"""

import logging
import os
import uuid
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

from pydantic import ValidationError

from webqa_agent.browser.config import DEFAULT_CONFIG
from webqa_agent.data import (ParallelTestSession, TestConfiguration,
                              TestResult, TestStatus, TestType)
from webqa_agent.data.case_structures import Case
from webqa_agent.data.test_structures import get_category_for_test_type
from webqa_agent.executor.case_executor import CaseExecutor
from webqa_agent.utils import Display
from webqa_agent.utils.get_log import GetLog
from webqa_agent.utils.log_icon import icon


class CaseMode:
    """Case mode - executes YAML-defined test cases serially."""

    def __init__(self):
        """Initialize case mode."""
        pass

    async def run(
        self,
        cases: List[Dict[str, Any]],  # Raw YAML dicts
        target_url: str,
        llm_config: Dict[str, Any],
        cookies: Optional[List[Dict]] = None,
        browser_config: Optional[Dict[str, Any]] = None,
        ignore_rules: Optional[Dict[str, List[Dict]]] = None,
        log_cfg: Optional[Dict[str, Any]] = None,
        report_cfg: Optional[Dict[str, Any]] = None,
    ) -> Tuple[Dict[str, Any], str, str, Dict[str, Any]]:
        """Run test cases in case mode.

        Args:
            cases: List of case configurations from YAML
            target_url: Target URL to test
            llm_config: LLM configuration
            browser_config: Browser configuration
            cookies: Optional cookies for browser session
            ignore_rules: Optional ignore rules for network and console errors
            log_cfg: Log configuration
            report_cfg: Report configuration

        Returns:
            Tuple of (aggregated_results, json_report_path, html_report_path, result_count)
        """
        # Initialize logging and display
        if log_cfg is None:
            log_cfg = {'level': 'info'}
        if report_cfg is None:
            report_cfg = {'language': 'en-US'}

        GetLog.get_log(log_level=log_cfg['level'])
        Display.init(language=report_cfg['language'])
        Display.display.start()

        logging.info(f"{icon['rocket']} Starting case mode execution for URL: {target_url}")
        # Use default config if none provided
        if not browser_config:
            browser_config = DEFAULT_CONFIG.copy()

        # Create test session (reuse ParallelTestSession structure)
        session_id = str(uuid.uuid4())
        test_session = ParallelTestSession(session_id=session_id, target_url=target_url, llm_config=llm_config)

        # Use a fresh per-task timestamp for reports
        report_ts = datetime.now().strftime('%Y-%m-%d_%H-%M-%S_%f')
        os.environ['WEBQA_REPORT_TIMESTAMP'] = report_ts

        # Create a single TestConfiguration for the case execution
        # This wraps all cases under one test result
        test_config = TestConfiguration(
            test_id=str(uuid.uuid4()),
            test_type=TestType.UI_AGENT_LANGGRAPH,  # Use existing type for compatibility
            test_name='YAML Case Execution',
            enabled=True,
            browser_config=browser_config,
            report_config=report_cfg,
            test_specific_config={
                'cookies': cookies,
                'url': target_url,
                'ignore_rules': ignore_rules or {},
            },
        )

        test_session.add_test_configuration(test_config)
        test_session.start_session()

        case_executor = None
        case_results = None
        test_result = None
        result_count = {'total': 0, 'passed': 0, 'failed': 0, 'warning': 0}
        html_report_path = None

        try:
            # Parse cases from YAML dicts to Case objects
            try:
                parsed_cases = Case.from_yaml_list(cases)
                logging.info(f'📋 Parsed {len(parsed_cases)} test cases')
                # Set total count early for report summary
                result_count['total'] = len(parsed_cases)
            except ValidationError as e:
                # Format friendly error message
                error_details = []
                for error in e.errors():
                    # error['loc'] looks like (0, 'steps', 2, 'verify') or (0, 'name')
                    loc = error['loc']
                    msg = error['msg']
                    
                    # Clean up common pydantic prefixes
                    if msg.startswith("Value error, "):
                        msg = msg.replace("Value error, ", "")
                    
                    case_idx = loc[0] if len(loc) > 0 and isinstance(loc[0], int) else None
                    case_name = "Unknown Case"
                    if case_idx is not None and case_idx < len(cases):
                        case_name = cases[case_idx].get('name', f'Case {case_idx + 1}')
                    
                    if len(loc) >= 3 and loc[1] == 'steps':
                        step_idx = loc[2]
                        step_info = f"Step {step_idx + 1}"
                        
                        # Try to get field name if available
                        field = str(loc[3]) if len(loc) > 3 else ""
                        if field:
                            error_details.append(f"  - [{case_name}] {step_info} '{field}': {msg}")
                        else:
                            error_details.append(f"  - [{case_name}] {step_info}: {msg}")
                    elif len(loc) >= 2:
                        field = str(loc[1])
                        error_details.append(f"  - [{case_name}] field '{field}': {msg}")
                    else:
                        error_details.append(f"  - [{case_name}]: {msg}")

                friendly_msg = "Case format is invalid:\n" + "\n".join(error_details)
                logging.error(f"{icon['cross']} {friendly_msg}")
                raise ValueError(friendly_msg) from e

            # Initialize case executor
            case_executor = CaseExecutor(
                test_config=test_config,
                llm_config=llm_config,
            )

            # Execute all cases
            case_results = await case_executor.execute_cases(cases=cases)

            # Safety check: ensure case_results is not None
            if case_results is None:
                logging.warning('case_executor.execute_cases returned None, treating as empty list')
                case_results = []

            # Calculate result statistics
            total_cases = len(case_results)
            passed_cases = sum(1 for c in case_results if c.status == TestStatus.PASSED)
            failed_cases = sum(1 for c in case_results if c.status == TestStatus.FAILED)
            warning_cases = sum(1 for c in case_results if c.status == TestStatus.WARNING)

            result_count = {
                'total': total_cases,
                'passed': passed_cases,
                'failed': failed_cases,
                'warning': warning_cases,
            }

            # Determine overall status
            if failed_cases > 0:
                overall_status = TestStatus.FAILED
                error_message = f'{failed_cases} out of {total_cases} cases failed'
            elif warning_cases > 0:
                overall_status = TestStatus.WARNING
                error_message = None
            else:
                overall_status = TestStatus.PASSED
                error_message = None

            # Build test result
            end_time = datetime.now()
            test_result = TestResult(
                test_id=test_config.test_id,
                test_type=test_config.test_type,
                test_name=test_config.test_name,
                status=overall_status,
                category=get_category_for_test_type(test_config.test_type),
                start_time=test_session.start_time,
                end_time=end_time,
                sub_tests=case_results,
                error_message=error_message,
            )

            test_result.duration = (end_time - test_session.start_time).total_seconds()

            # Update session with result
            test_session.update_test_result(test_config.test_id, test_result)
            test_session.complete_session()

            logging.info(f"{icon['check']} Cases executed: {passed_cases}/{total_cases} passed")

        except Exception as e:
            raise e
        finally:
            # Generate HTML report if possible (even if some cases failed or crashed)
            if case_executor and case_executor.report_dir:
                try:
                    html_report_path = self._generate_html_with_jinja2(
                        test_session, report_cfg, case_executor.report_dir, result_count
                    )
                    if html_report_path:
                        test_session.html_report_path = html_report_path
                except Exception as report_err:
                    logging.warning(f'Failed to generate final report: {report_err}')

            # Cleanup Display (with error protection)
            try:
                await Display.display.stop()
                Display.display.render_summary()
            except Exception as display_err:
                logging.warning(f'Failed to stop display: {display_err}')

        return (
            test_session.aggregated_results,
            test_session.report_path,
            test_session.html_report_path,
            result_count,
        )


    def _generate_html_with_jinja2(
        self, test_session: ParallelTestSession, report_cfg: Dict[str, Any], report_dir: str, result_count: Dict[str, Any]
    ) -> str:
        """Generate HTML test report with Jinja2 template, merge all test case
        data.

        Args:
            test_session: ParallelTestSession object
            report_cfg: report configuration
            report_dir: report directory
            result_count: result count

        Returns:
            str: report path
        """
        # read all test data files
        test_data = []
        test_data_files = []
        try:
            import glob
            import json

            # Find all test_data_*.json files in report_dir and sort by filename (which includes index)
            test_data_files = sorted(glob.glob(os.path.join(report_dir, 'test_data_*.json')))

            if not test_data_files:
                logging.warning(f'No test data files found in {report_dir}')
                return None

            # read and merge all test data
            for data_file in test_data_files:
                try:
                    with open(data_file, 'r', encoding='utf-8') as f:
                        file_data = json.load(f)
                        if isinstance(file_data, list):
                            test_data.extend(file_data)
                except Exception as e:
                    logging.warning(f'Failed to read test data file: {data_file}, error: {str(e)}')
        except Exception as e:
            logging.error(f'Failed to merge test data: {str(e)}')
            return None

        # Check if we have test data
        if not test_data:
            logging.error('No test data found after merging')
            return None

        # Sort test_data by case_index to ensure correct order
        test_data.sort(key=lambda x: x.get('case_index', 999))

        logging.debug(f'Loaded {len(test_data)} test cases from {len(test_data_files)} files')

        # Extract case summary information
        case_summaries = []
        for i, case in enumerate(test_data):
            case_summaries.append({
                'index': i + 1,
                'name': case.get('name', f'Case {i+1}'),
                'status': case.get('status', 'unknown')
            })

        # # prepare template data - if OSS is enabled, remove base64 data to reduce HTML file size
        # if cls.enable_oss_screenshots:
        #     for case in test_data:
        #         for step in case.get('steps', []):
        #             for screenshot in step.get('screenshots', []):
        #                 # 如果有 OSS URL，移除 base64 数据
        #                 if screenshot.get('oss_url'):
        #                     screenshot.pop('base64', None)

        passed_count = result_count.get('passed', 0)
        warning_count = result_count.get('warning', 0)
        failed_count = result_count.get('failed', 0)
        
        # Recalculate summary from actual data found on disk for accuracy (especially on crashes)
        if test_data:
            passed_count = sum(1 for c in test_data if c.get('status') == 'passed')
            warning_count = sum(1 for c in test_data if c.get('status') == 'warning')
            failed_count = sum(1 for c in test_data if c.get('status') == 'failed')

        total_count = result_count.get('total', len(test_data))
        exception_count = total_count - passed_count - warning_count - failed_count
        total_count = total_count # Keep as is for template usage

        # render template with Jinja2
        try:
            from jinja2 import BaseLoader, Environment, select_autoescape

            # create a custom filter to parse JSON string
            def from_json(value):
                if not value:
                    return {}
                try:
                    return json.loads(value)
                except:
                    return {'error': 'Invalid JSON'}

            # process image data, support base64, OSS URL and path
            def process_image(img_data):
                if not img_data:
                    return ''

                # if new format (dict format)
                if isinstance(img_data, dict):
                    # use OSS URL (if exists)
                    if img_data.get('oss_url'):
                        return img_data.get('oss_url')
                    # otherwise use data field (maybe base64 or path)
                    elif img_data.get('data'):
                        data = img_data.get('data', '')
                        # if base64 format, return directly
                        if isinstance(data, str) and data.startswith('data:image'):
                            return data
                        # otherwise treat as path
                        return data.replace('\\', '/')
                    # finally try base64 field
                    elif img_data.get('base64'):
                        return img_data.get('base64')
                    else:
                        return ''

                # compatible with old format (string)
                if isinstance(img_data, str):
                    if img_data.startswith('data:image') or img_data.startswith('http'):
                        return img_data
                    return img_data.replace('\\', '/')

                return ''

            # set Jinja2 environment
            env = Environment(
                loader=BaseLoader(),
                autoescape=select_autoescape(['html', 'xml'])
            )

            # Custom safe tojson filter that handles Undefined and missing attributes
            def safe_tojson(value, indent=None):
                """Safe JSON serialization that handles Undefined objects and
                None values."""
                import json

                from jinja2 import Undefined

                # Handle Undefined or None
                if value is None or isinstance(value, Undefined):
                    return 'null'

                try:
                    if indent:
                        return json.dumps(value, indent=indent, ensure_ascii=False, default=str)
                    else:
                        return json.dumps(value, ensure_ascii=False, default=str)
                except (TypeError, ValueError) as e:
                    logging.warning(f'Failed to serialize to JSON: {e}, value type: {type(value)}')
                    return 'null'

            # Custom filter to render modelIO - simple version without markdown
            def render_modelio(value):
                """Render modelIO as formatted JSON or plain text."""
                if not value:
                    return ''

                # Try to parse as JSON first
                try:
                    if isinstance(value, str):
                        parsed = json.loads(value)
                        # Format as pretty JSON and wrap in code block
                        formatted = json.dumps(parsed, indent=2, ensure_ascii=False)
                        # HTML escape for safety
                        import html
                        formatted = html.escape(formatted)
                        return f'<pre><code class="language-json">{formatted}</code></pre>'
                except (json.JSONDecodeError, TypeError):
                    pass

                # If not JSON, display as plain text in pre tag
                import html
                if isinstance(value, str):
                    escaped = html.escape(value)
                    return f'<pre>{escaped}</pre>'
                else:
                    escaped = html.escape(str(value))
                    return f'<pre>{escaped}</pre>'

            # 添加自定义过滤器
            env.filters['from_json'] = from_json
            env.filters['process_image'] = process_image
            env.filters['tojson'] = safe_tojson  # Override built-in tojson with safe version
            env.filters['render_modelio'] = render_modelio  # Render modelIO as formatted JSON or plain text

            def decode_unicode(s):
                """Decode Unicode escape sequence, while preserving existing
                Chinese characters."""
                if not isinstance(s, str):
                    return s
                try:
                    # check if contains Unicode escape sequence (like \u4e2d \u6587)
                    import re
                    if re.search(r'\\u[0-9a-fA-F]{4}', s):
                        # only decode when contains Unicode escape sequence
                        # use raw_unicode_escape encoding and then decode
                        decoded = s.encode('utf-8').decode('unicode_escape')
                        # handle possible surrogate pairs
                        try:
                            decoded = decoded.encode('utf-16', 'surrogatepass').decode('utf-16', 'replace')
                        except:
                            pass
                        return decoded
                    else:
                        # string is already normal UTF-8, return directly
                        return s
                except Exception as e:
                    # decode failed, return original string
                    return s

            env.filters['decode_unicode'] = decode_unicode

            # Get template path - use static/template.html
            from pathlib import Path
            executor_dir = Path(__file__).resolve().parent
            static_dir = executor_dir.parent / 'static'
            template_path = static_dir / 'template.html'

            if not template_path.exists():
                logging.error(f'Template not found at {template_path}')
                return None

            logging.debug(f'Loading template from: {template_path}')
            template_string = template_path.read_text(encoding='utf-8')

            # Load i18n resources
            language = report_cfg.get('language', 'en-US')
            i18n_file = static_dir / 'i18n' / f'{language}.json'
            i18n_data = {}
            
            if i18n_file.exists():
                try:
                    with open(i18n_file, 'r', encoding='utf-8') as f:
                        i18n_data = json.load(f)
                    logging.debug(f'Loaded i18n file: {i18n_file}')
                except Exception as e:
                    logging.warning(f'Failed to load i18n file {i18n_file}: {e}')
            else:
                logging.warning(f'i18n file not found: {i18n_file}, using default language')

            # get template
            template = env.from_string(template_string)

            # render template
            rendered_html = template.render(
                test_cases=test_data,
                case_summaries=case_summaries,
                passed_count=passed_count,
                warning_count=warning_count,
                failed_count=failed_count,
                exception_count=exception_count,
                total_count=total_count,
                language=language,
                i18n=i18n_data
            )

            # save rendered HTML to file
            report_path = os.path.join(report_dir, 'report.html')
            with open(report_path, 'w', encoding='utf-8') as f:
                f.write(rendered_html)

            # Convert to absolute path
            absolute_report_path = os.path.abspath(report_path)
            logging.info(f"{icon['check']} HTML report generated: {absolute_report_path}")
            return absolute_report_path

        except Exception as e:
            logging.error(f"{icon['cross']} Failed to generate HTML report: {str(e)}")
            import traceback
            logging.debug(traceback.format_exc())
            return None

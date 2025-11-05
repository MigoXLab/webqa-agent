import json
import logging
import os
from pathlib import Path
from typing import Any, Dict, List, Optional

from webqa_agent.data import ParallelTestSession, TestStatus
from webqa_agent.llm.llm_api import LLMAPI
from webqa_agent.utils import i18n

class ResultAggregator:
    """Aggregates and analyzes parallel test results"""
    
    def __init__(self, report_config: dict = None):
        """Initialize ResultAggregator with language support.
        
        Args:
            report_config: Configuration dictionary containing language settings
        """
        self.language = report_config.get("language", "zh-CN") if report_config else "zh-CN"
        self.localized_strings = {
            'zh-CN': i18n.get_lang_data('zh-CN').get('aggregator', {}),
            'en-US': i18n.get_lang_data('en-US').get('aggregator', {}),
        }
    
    def _get_text(self, key: str) -> str:
        """Get localized text for the given key."""
        return self.localized_strings.get(self.language, {}).get(key, key)
    
    async def aggregate_results(self, test_session: ParallelTestSession) -> Dict[str, Any]:
        """Aggregate all test results into a comprehensive summary.

        Args:
            test_session: Session containing all test results

        Returns:
            Aggregated results dictionary
        """
        logging.debug(f"Aggregating results for session: {test_session.session_id}")
        issues = []
        error_message = await self._get_error_message(test_session)
        # Generate issue list (LLM powered when possible)
        llm_issues = await self._generate_llm_issues(test_session)
        
        issues.extend(error_message)
        issues.extend(llm_issues)
        logging.info(f"Aggregated {len(test_session.test_results)} test results, found {len(issues)} issues")
        for test_id, result in test_session.test_results.items():
            sub_tests_count = len(result.sub_tests or [])
            logging.debug(f"Test {test_id} has {sub_tests_count} sub_tests")
            if result.sub_tests:
                for i, sub_test in enumerate(result.sub_tests):
                    logging.debug(f"Sub-test {i}: status={sub_test.status}")
        
        total_sub_tests = sum(len(r.sub_tests or []) for r in test_session.test_results.values())
        passed_sub_tests = sum(
            1
            for r in test_session.test_results.values()
            for sub in (r.sub_tests or [])
            if sub.status == TestStatus.PASSED
        )
        warning_sub_tests = sum(
            1
            for r in test_session.test_results.values()
            for sub in (r.sub_tests or [])
            if sub.status == TestStatus.WARNING
        )
        failed_sub_tests = sum(
            1
            for r in test_session.test_results.values()
            for sub in (r.sub_tests or [])
            if sub.status == TestStatus.FAILED
        )
        critical_sub_tests = total_sub_tests - passed_sub_tests  # 未通过即视为关键问题
        
        logging.debug(f"Debug: total_sub_tests={total_sub_tests}, passed_sub_tests={passed_sub_tests}, warning_sub_tests={warning_sub_tests}, failed_sub_tests={failed_sub_tests}, critical_sub_tests={critical_sub_tests}")

        # Build content for executive summary tab
        executive_content = {
            "executiveSummary": "",
            "statistics": [
                {"label": self._get_text('assessment_categories'), "value": str(total_sub_tests), "colorClass": "var(--warning-color)"},
                {"label": self._get_text('passed_count'), "value": str(passed_sub_tests), "colorClass": "var(--success-color)"},
                {"label": self._get_text('warning_count'), "value": str(warning_sub_tests), "colorClass": "var(--warning-color)"},
                {"label": self._get_text('failed_count'), "value": str(failed_sub_tests), "colorClass": "var(--failure-color)"},
            ]
        }

        aggregated_results_list = [
            {"id": "subtab-summary-advice", "title": self._get_text('summary_and_advice'), "content": executive_content},
            {
                "id": "subtab-issue-tracker",
                "title": self._get_text('issue_list'),
                "content": {
                    "title": self._get_text('issue_tracker_list'),
                    "note": self._get_text('issue_list_note'),
                    "issues": issues,
                },
            },
        ]

        # Store additional raw analysis for LLM etc.
        raw_analysis = {
            "session_summary": test_session.get_summary_stats(),
        }

        def dict_to_text(d, indent=0):
            lines = []
            for k, v in d.items():
                if isinstance(v, dict):
                    lines.append(" " * indent + f"{k}:")
                    lines.append(dict_to_text(v, indent + 2))
                else:
                    lines.append(" " * indent + f"{k}: {v}")
            return "\n".join(lines)

        executive_content["executiveSummary"] = f"{dict_to_text(raw_analysis['session_summary'])}"

        # Also expose simple counters at the top-level for easy consumption
        return {
            "title": self._get_text('assessment_overview'),
            "tabs": aggregated_results_list,
            "count":{
                "total": total_sub_tests,
                "passed": passed_sub_tests,
                "warning": warning_sub_tests,
                "failed": failed_sub_tests,
            }
        }

    async def _generate_llm_issues(self, test_session: ParallelTestSession) -> List[Dict[str, Any]]:
        """Use LLM to summarise issues for each sub-test.

        Fallback to heuristic if LLM unavailable.
        """
        llm_config = test_session.llm_config or {}
        use_llm = bool(llm_config)
        critical_issues: List[Dict[str, Any]] = []

        # Prepare LLM client if configured
        llm: Optional[LLMAPI] = None
        if use_llm:
            try:
                llm = LLMAPI(llm_config)
                await llm.initialize()
            except Exception as e:
                logging.error(f"Failed to initialise LLM, falling back to heuristic issue extraction: {e}")
                use_llm = False

        # Iterate over all tests and their sub-tests
        for test_result in test_session.test_results.values():
            for sub in test_result.sub_tests or []:
                try:
                    # Determine severity strictly based on sub-test status
                    if sub.status == TestStatus.PASSED:
                        continue  # No issue for passed sub-tests
                    if sub.status == TestStatus.WARNING:
                        severity_level = "low"
                    elif sub.status == TestStatus.FAILED:
                        severity_level = "high"
                    else:
                        severity_level = "medium"

                    issue_entry = {
                        "issue_name": self._get_text('test_failed_prefix') + test_result.test_name, 
                        "issue_type": test_result.test_type.value,
                        "sub_test_name": sub.name,
                        "severity": severity_level,
                    }
                    if use_llm and llm:
                        prompt_content = {
                            "name": sub.name,
                            "status": sub.status,
                            "report": sub.report,
                            "metrics": sub.metrics,
                            "final_summary": sub.final_summary,
                        }
                        prompt = (
                            f"{self._get_text('llm_prompt_main')}\n\n"
                            f"{self._get_text('llm_prompt_test_info')}{json.dumps(prompt_content, ensure_ascii=False, default=str)}"
                        )
                        logging.debug(f"LLM Issue Prompt: {prompt}")
                        llm_response_raw = await llm.get_llm_response("", prompt)
                        llm_response = llm._clean_response(llm_response_raw)
                        logging.debug(f"LLM Issue Response: {llm_response}")
                        try:
                            parsed = json.loads(llm_response)
                            issue_count = parsed.get("issue_count", parsed.get("count", 1))
                            if issue_count == 0:
                                continue
                            issue_text = parsed.get("issues", "").strip()
                            if not issue_text:
                                continue
                            llm_severity = parsed.get("severity", severity_level)
                            issue_entry["severity"] = llm_severity
                            issue_entry["issues"] = issue_text
                            issue_entry["issue_count"] = issue_count
                        except Exception as parse_err:
                            logging.error(f"Failed to parse LLM JSON: {parse_err}; raw: {llm_response}")
                            continue  # skip if cannot parse
                    else:
                        # Heuristic fallback – use final_summary to detect issue presence
                        summary_text = (sub.final_summary or "").strip()
                        if not summary_text:
                            continue
                        lowered = summary_text.lower()
                        if any(k in lowered for k in ["error", "fail", "严重", "错误", "崩溃", "无法"]):
                            issue_entry["severity"] = "high"
                        elif any(k in lowered for k in ["warning", "警告", "建议", "优化", "改进"]):
                            issue_entry["severity"] = "low"
                        else:
                            issue_entry["severity"] = "medium"
                        issue_entry["issues"] = summary_text
                        issue_entry["issue_count"] = 1
                    # add populated entry
                    critical_issues.append(issue_entry)
                except Exception as e:
                    logging.error(f"Error while generating issue summary for sub-test {sub.name}: {e}")
                    continue  # skip problematic sub-test
        # Close LLM client if needed
        if use_llm and llm:
            try:
                await llm.close()
            except Exception as e:
                logging.warning(f"Failed to close LLM client: {e}")
        return critical_issues

    async def _get_error_message(self, test_session: ParallelTestSession) -> str:
        """Get error message from test session."""
        error_message = []
        for test_result in test_session.test_results.values():
            if test_result.status != TestStatus.PASSED:
                # Only append if error_message is not empty
                if test_result.error_message:
                    error_message.append({
                        "issue_name": self._get_text('execution_error_prefix') + test_result.test_name,
                        "issue_type": test_result.test_type.value,
                        "severity": "high",
                        "issues": test_result.error_message
                    })
        return error_message

    async def generate_json_report(self, test_session: ParallelTestSession, report_dir: str | None = None) -> str:
        """Generate comprehensive JSON report."""
        try:
            # Determine report directory
            if report_dir is None:
                timestamp = os.getenv("WEBQA_REPORT_TIMESTAMP") or os.getenv("WEBQA_TIMESTAMP")
                report_dir = f"./reports/test_{timestamp}"
            os.makedirs(report_dir, exist_ok=True)

            json_path = os.path.join(report_dir, "test_results.json")
            with open(json_path, "w", encoding="utf-8") as f:
                json.dump(test_session.to_dict(), f, indent=2, ensure_ascii=False, default=str)

            absolute_path = os.path.abspath(json_path)
            if os.getenv("DOCKER_ENV"):
                host_path = absolute_path.replace("/app/reports", "./reports")
                logging.debug(f"JSON report generated: {host_path}")
                return host_path
            else:
                logging.debug(f"JSON report generated: {absolute_path}")
                return absolute_path

        except Exception as e:
            logging.error(f"Failed to generate JSON report: {e}")
            return ""

    def _get_static_dir(self) -> Path:
        """Resolve the static assets directory in a robust way.

        This uses the source file location of this module instead of the working
        directory to avoid issues on hosted platforms.
        """
        # __file__ → .../webqa_agent/executor/result_aggregator.py
        # static dir → .../webqa_agent/static
        executor_dir = Path(__file__).resolve().parent
        static_dir = (executor_dir.parent / "static").resolve()
        return static_dir

    def _read_css_content(self) -> str:
        """Read and return CSS content."""
        try:
            css_path = self._get_static_dir() / "assets" / "style.css"
            if css_path.exists():
                return css_path.read_text(encoding="utf-8")
        except Exception as e:
            logging.warning(f"Failed to read CSS file: {e}")
        return ""

    def _read_js_content(self) -> str:
        """Read and return JavaScript content based on language."""
        try:
            # Choose JS file based on language
            if self.language == "en-US":
                js_filename = "index_en-US.js"
            else:
                js_filename = "index.js"  # Default to Chinese version
                
            js_path = self._get_static_dir() / "assets" / js_filename
            if js_path.exists():
                return js_path.read_text(encoding="utf-8")
            else:
                # Fallback to default file if language-specific file doesn't exist
                fallback_path = self._get_static_dir() / "assets" / "index.js"
                if fallback_path.exists():
                    logging.warning(f"Language-specific JS file {js_filename} not found, using fallback")
                    return fallback_path.read_text(encoding="utf-8")
        except Exception as e:
            logging.warning(f"Failed to read JS file: {e}")
        return ""

    def generate_html_report_fully_inlined(self, test_session, report_dir: str | None = None) -> str:
        """Generate a fully inlined HTML report for the test session."""
        import re
        import json
        import re

        try:
            template_file = self._get_static_dir() / "index.html"

            template_found = template_file.exists()
            if template_found:
                html_template = template_file.read_text(encoding="utf-8")
            else:
                logging.warning(
                    f"Report template not found at {template_file}. Falling back to minimal inline template."
                )

            datajs_content = (
                "window.testResultData = " + json.dumps(test_session.to_dict(), ensure_ascii=False, default=str) + ";"
            )

            if template_found:
                css_content = self._read_css_content()
                js_content = self._read_js_content()

                html_out = html_template
                html_out = re.sub(
                    r'<link\s+rel="stylesheet"\s+href="/assets/style.css"\s*>',
                    lambda m: f"<style>\n{css_content}\n</style>",
                    html_out,
                )
                html_out = re.sub(
                    r'<script\s+src="/data.js"\s*>\s*</script>',
                    lambda m: f"<script>\n{datajs_content}\n</script>",
                    html_out,
                )
                html_out = re.sub(
                    r'<script\s+type="module"\s+crossorigin\s+src="/assets/index.js"\s*>\s*</script>',
                    lambda m: f'<script type="module">\n{js_content}\n</script>',
                    html_out,
                )

            if report_dir is None:
                timestamp = os.getenv("WEBQA_REPORT_TIMESTAMP") or os.getenv("WEBQA_TIMESTAMP")
                report_dir = f"./reports/test_{timestamp}"
            # Ensure report dir exists; if creation fails, fallback to tmp
            try:
                os.makedirs(report_dir, exist_ok=True)
                report_dir_path = Path(report_dir).resolve()
            except Exception as mk_err:
                logging.warning(f"Cannot create report dir '{report_dir}': {mk_err}. Falling back to /tmp/webqa-reports.")
                report_dir_path = Path("/tmp/webqa-reports").resolve()
                report_dir_path.mkdir(parents=True, exist_ok=True)

            html_path = report_dir_path / "test_report.html"
            html_path.write_text(html_out, encoding="utf-8")

            absolute_path = str(html_path)
            if os.getenv("DOCKER_ENV"):
                mapped = absolute_path.replace("/app/reports", "./reports")
                logging.debug(f"HTML report generated: {mapped}")
                return mapped
            else:
                logging.debug(f"HTML report generated: {absolute_path}")
                return absolute_path
        except Exception as e:
            logging.error(f"Failed to generate fully inlined HTML report: {e}")
            return ""
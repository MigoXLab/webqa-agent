import json
import logging
import os
import shutil
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from webqa_agent.data import TestResult
from webqa_agent.llm.llm_api import LLMAPI
from webqa_agent.llm.prompt import LLMPrompt
from webqa_agent.utils import i18n


class ResultAggregator:
    """Aggregates and analyzes parallel test results."""

    def __init__(self, report_config: dict = None):
        """Initialize ResultAggregator with language support.

        Args:
            report_config: Configuration dictionary containing language settings
        """
        self.language = report_config.get('language', 'zh-CN') if report_config else 'zh-CN'
        self.localized_strings = {
            'zh-CN': i18n.get_lang_data('zh-CN').get('aggregator', {}),
            'en-US': i18n.get_lang_data('en-US').get('aggregator', {}),
        }
        self.report_dir = report_config.get('report_dir', None)
        self.tmp_subdir = 'tmp'

    def _get_text(self, key: str) -> str:
        """Get localized text for the given key."""
        return self.localized_strings.get(self.language, {}).get(key, key)

    @staticmethod
    def compute_counts_from_tests(test_results: List[TestResult]) -> Dict[str, int]:
        """Single source of truth for counting sub-test statuses."""
        total = passed = failed = warning = 0
        for result in test_results or []:
            sub_tests = result.sub_tests if getattr(result, 'sub_tests', None) else [result]
            for sub in sub_tests:
                total += 1
                status = getattr(sub, 'status', None)
                if hasattr(status, 'value'):
                    status = status.value
                status_str = str(status).lower()
                if status_str == 'passed':
                    passed += 1
                elif status_str == 'warning':
                    warning += 1
                elif status_str == 'failed':
                    failed += 1
        return {'total': total, 'passed': passed, 'failed': failed, 'warning': warning}

    async def generate_llm_summary(
        self,
        test_results: List[TestResult],
        llm_config: Dict[str, Any],
        report_lang: Optional[str] = None
    ) -> str:
        """Generate a summary using LLM based on test results."""
        if not test_results or not llm_config:
            return ''

        if report_lang is None:
            report_lang = self.language

        # Extract report information from all sub_tests
        reports_info = []
        for result in test_results:
            sub_tests = result.sub_tests if hasattr(result, 'sub_tests') else result.get('sub_tests', [])
            if sub_tests:
                for sub in sub_tests:
                    report = sub.report if hasattr(sub, 'report') else sub.get('report', [])
                    name = sub.name if hasattr(sub, 'name') else sub.get('name', 'Unknown')
                    if report:
                        report_text = ''
                        for r in report:
                            title = r.title if hasattr(r, 'title') else r.get('title', '')
                            issues = r.issues if hasattr(r, 'issues') else r.get('issues', '')
                            report_text += f'Title: {title}\nIssues: {issues}\n'
                        if report_text:
                            reports_info.append(f'Case: {name}\n{report_text}')

        if not reports_info:
            return ''

        # Combine all reports into a single input string
        combined_reports = '\n---\n'.join(reports_info)

        # Prepare LLM call
        try:
            llm = LLMAPI(llm_config)
            system_prompt = LLMPrompt.summary_prompt_zh if report_lang == 'zh-CN' else LLMPrompt.summary_prompt_en

            summary = await llm.get_llm_response(system_prompt, combined_reports)
            return summary
        except Exception as e:
            logging.warning(f'Failed to generate LLM summary: {e}')
            return ''

    def aggregate_report_json(self, mode: str, report_dir: str, tmp_subdir: Optional[str] = None) -> Tuple[Dict[str, Any], str]:
        """Read all JSON files in report directory (including tmp subdir) and
        aggregate them into a single dict and write to test_results.json.

        Returns:
            Tuple[Dict[str, Any], str]: (aggregated_data, json_path)
        """

        aggregated = {mode: {}}
        final_path = ''
        if not report_dir or not os.path.exists(report_dir):
            return aggregated, final_path

        import re

        def natural_sort_key(s):
            return [int(text) if text.isdigit() else text.lower() for text in re.split(r'([0-9]+)', s)]

        report_path = Path(report_dir)
        tmp_dir = report_path / (tmp_subdir or self.tmp_subdir)

        # Collect JSON files from tmp first, then root (avoid duplicates)
        json_files = []
        seen_names = set()

        def _add_files_from_dir(directory: Path):
            if not directory.exists():
                return
            files = list(directory.glob('*.json'))
            files.sort(key=lambda p: natural_sort_key(p.name))
            for f in files:
                if f.name in seen_names:
                    continue
                seen_names.add(f.name)
                json_files.append(f)

        _add_files_from_dir(tmp_dir)
        _add_files_from_dir(report_path)

        for file_path in json_files:
            filename = os.path.basename(file_path)
            # Skip test_results.json to avoid self-inclusion
            if filename == 'test_results.json':
                continue
            if filename == 'cases.json':
                continue
            if filename == 'index.json':
                key = 'index'
            elif filename.endswith('_data.json'):
                key = filename[:-10]  # remove _data.json
            elif filename.endswith('_monitor.json'):
                key = filename[:-5]   # remove .json
            else:
                key = os.path.splitext(filename)[0]

            try:
                with open(file_path, 'r', encoding='utf-8') as f:
                    aggregated[mode][key] = json.load(f)
            except Exception as e:
                logging.warning(f'Failed to read {file_path}: {e}')

        # Backfill aggregated_results list if index exists but has empty result list
        try:
            index_data = aggregated[mode].get('index')
            if index_data and isinstance(index_data, dict):
                agg_res = index_data.get('aggregated_results', {}) or {}
                results_key = 'gen_result' if mode == 'gen' else 'run_result'
                needs_backfill = not agg_res.get(results_key)

                if needs_backfill:
                    backfilled = []
                    for key, value in aggregated[mode].items():
                        # Skip non-case entries and monitor artifacts to avoid duplicates
                        if key in ('index', 'cases', 'test_results'):
                            continue
                        if isinstance(key, str) and key.endswith('_monitor'):
                            continue
                        if not isinstance(value, dict):
                            continue
                        display_name = value.get('display_name') or value.get('name') or key
                        safe_name = value.get('safe_name') or value.get('name') or key
                        backfilled.append({
                            'name': safe_name,
                            'display_name': display_name,
                            'safe_name': safe_name,
                            'status': str(value.get('status') or '').lower(),
                            'sub_test_id': value.get('sub_test_id') or key
                        })

                    if backfilled:
                        agg_res[results_key] = backfilled
                        # Recompute counters by status for UI accuracy
                        count = {
                            'total': len(backfilled),
                            'passed': sum(1 for item in backfilled if item.get('status') == 'passed'),
                            'warning': sum(1 for item in backfilled if item.get('status') == 'warning'),
                            'failed': sum(1 for item in backfilled if item.get('status') == 'failed'),
                        }
                        agg_res['count'] = count
                        index_data['aggregated_results'] = agg_res
                        index_data['count'] = count
                        aggregated[mode]['index'] = index_data
        except Exception as backfill_err:
                logging.warning(f'Failed to backfill aggregated results: {backfill_err}')

        # Normalize any file-system paths to POSIX style so HTML works cross-platform
        try:
            aggregated = self._normalize_paths_for_web(aggregated)
        except Exception as norm_err:
            logging.warning(f'Failed to normalize paths for web: {norm_err}')

        # Write the aggregated results to test_results.json
        output_path = os.path.join(report_dir, 'test_results.json')
        try:
            with open(output_path, 'w', encoding='utf-8') as f:
                json.dump(aggregated, f, indent=2, ensure_ascii=False, default=str)

            # Docker path adaptation
            absolute_path = os.path.abspath(output_path)
            if os.getenv('DOCKER_ENV'):
                final_path = absolute_path.replace('/app/reports', './reports')
            else:
                final_path = absolute_path

            logging.info(f'Aggregated report saved to {final_path}')
        except Exception as e:
            logging.warning(f'Failed to save aggregated report to {output_path}: {e}')
            final_path = os.path.abspath(output_path)

        return aggregated, final_path

    def _get_static_dir(self) -> Path:
        """Resolve the static assets directory in a robust way.

        This uses the source file location of this module instead of the
        working directory to avoid issues on hosted platforms.
        """
        # __file__ → .../webqa_agent/executor/result_aggregator.py
        # static dir → .../webqa_agent/static
        executor_dir = Path(__file__).resolve().parent
        static_dir = (executor_dir.parent / 'static').resolve()
        return static_dir

    def _read_css_content(self) -> str:
        """Read and return CSS content."""
        try:
            css_path = self._get_static_dir() / 'assets' / 'index.css'
            if css_path.exists():
                return css_path.read_text(encoding='utf-8')
        except Exception as e:
            logging.warning(f'Failed to read CSS file: {e}')
        return ''

    def _read_js_content(self) -> str:
        """Read and return JavaScript content based on language."""
        try:
            # Choose JS file based on language
            if self.language == 'en-US':
                js_filename = 'index_en-US.js'
            else:
                js_filename = 'index.js'  # Default to Chinese version

            js_path = self._get_static_dir() / 'assets' / js_filename
            if js_path.exists():
                return js_path.read_text(encoding='utf-8')
            else:
                # Fallback to default file if language-specific file doesn't exist
                fallback_path = self._get_static_dir() / 'assets' / 'index.js'
                if fallback_path.exists():
                    logging.warning(f'Language-specific JS file {js_filename} not found, using fallback')
                    return fallback_path.read_text(encoding='utf-8')
        except Exception as e:
            logging.warning(f'Failed to read JS file: {e}')
        return ''

    @staticmethod
    def _serialize_data_for_inline(data: Any) -> str:
        """Safely serialize data for inline <script> usage.

        Escapes sequences that would prematurely terminate the script tag (e.g.
        </script>) and control characters that are invalid in JS string
        literals.
        """
        try:
            raw = json.dumps(data, ensure_ascii=False, default=str)
        except Exception as e:
            logging.warning(f'Failed to serialize report data to JSON: {e}')
            raw = '{}'

        # Protect against closing the script tag or breaking JS parsing
        safe = (
            raw
            .replace('</', '<\\/')           # Prevent </script> from ending the tag
            .replace('\u2028', '\\u2028')    # Line separator
            .replace('\u2029', '\\u2029')    # Paragraph separator
            .replace('<!--', '<\\!--')       # Prevent HTML comment start
        )
        return safe

    @staticmethod
    def _normalize_paths_for_web(data: Any) -> Any:
        """Convert screenshot paths to web-friendly separators.

        Windows paths use backslashes, which break relative asset loading in
        the generated HTML. This recursively walks the data structure and
        rewrites strings that look like screenshot paths to POSIX style.
        """

        def _normalize(value: Any) -> Any:
            if isinstance(value, dict):
                normalized = {k: _normalize(v) for k, v in value.items()}
                if normalized.get('type') == 'path' and isinstance(normalized.get('data'), str):
                    normalized['data'] = normalized['data'].replace('\\', '/')
                return normalized
            if isinstance(value, list):
                return [_normalize(item) for item in value]
            if isinstance(value, str) and 'screenshots' in value:
                return value.replace('\\', '/')
            return value

        return _normalize(data)

    def generate_html_report_fully_inlined(self, test_session, report_dir: str | None = None, aggregated_data: Dict[str, Any] = None) -> str:
        """Generate a fully inlined HTML report for the test session."""
        import json
        import re

        try:
            template_file = self._get_static_dir() / 'index.html'

            template_found = template_file.exists()
            if template_found:
                html_template = template_file.read_text(encoding='utf-8')
            else:
                logging.warning(
                    f'Report template not found at {template_file}. Falling back to minimal inline template.'
                )

            # Resolve report directory early for file-based fallback
            if report_dir is None:
                # Priority: 1. test_session.report_path 2. self.report_dir 3. fallback env-based
                report_dir = test_session.report_path or self.report_dir

            # Prefer provided aggregated_data; otherwise read from test_results.json; finally fallback to session
            data = aggregated_data
            if data is None:
                try:
                    resolved_dir = Path(report_dir) if report_dir else None
                    if resolved_dir:
                        test_results_path = resolved_dir / 'test_results.json'
                        if test_results_path.exists():
                            with open(test_results_path, 'r', encoding='utf-8') as f:
                                data = json.load(f)
                except Exception as read_err:
                    logging.warning(f'Failed to load test_results.json for HTML generation: {read_err}')

            if data is None:
                data = test_session.to_dict()

            # Ensure any Windows-style paths are safe for browser consumption
            data = self._normalize_paths_for_web(data)

            safe_data_json = self._serialize_data_for_inline(data)
            datajs_content = f'window.testResultData = {safe_data_json};'

            if template_found:
                css_content = self._read_css_content()
                js_content = self._read_js_content()

                html_out = html_template
                # Use flexible regex to match tags regardless of attribute order or extra whitespace
                html_out = re.sub(
                    r'<link[^>]*href=["\']?/assets/index\.css["\']?[^>]*>',
                    lambda m: f'<style>\n{css_content}\n</style>',
                    html_out,
                )
                html_out = re.sub(
                    r'<script[^>]*src=["\']?/data\.js["\']?[^>]*>\s*</script>',
                    lambda m: f'<script>\n{datajs_content}\n</script>',
                    html_out,
                )
                html_out = re.sub(
                    r'<script[^>]*src=["\']?/assets/index\.js["\']?[^>]*>\s*</script>',
                    lambda m: f'<script type="module">\n{js_content}\n</script>',
                    html_out,
                )

            if not report_dir:
                timestamp = os.getenv('WEBQA_REPORT_TIMESTAMP') or os.getenv('WEBQA_TIMESTAMP') or datetime.now().strftime('%Y-%m-%d_%H-%M-%S')
                report_dir = os.path.join('reports', f'test_{timestamp}')

            # Ensure report dir exists; if creation fails, fallback to temp dir
            try:
                os.makedirs(report_dir, exist_ok=True)
                report_dir_path = Path(report_dir).resolve()
            except Exception as mk_err:
                import tempfile
                temp_dir = os.path.join(tempfile.gettempdir(), 'webqa-reports')
                logging.warning(f"Cannot create report dir '{report_dir}': {mk_err}. Falling back to {temp_dir}.")
                report_dir_path = Path(temp_dir)
                report_dir_path.mkdir(parents=True, exist_ok=True)

            html_path = report_dir_path / 'test_report.html'
            html_path.write_text(html_out, encoding='utf-8')

            absolute_path = str(html_path)
            if os.getenv('DOCKER_ENV'):
                mapped = absolute_path.replace('/app/reports', './reports')
                logging.debug(f'HTML report generated: {mapped}')
                return mapped
            else:
                logging.debug(f'HTML report generated: {absolute_path}')
                return absolute_path
        except Exception as e:
            logging.error(f'Failed to generate fully inlined HTML report: {e}')
            return ''

    def cleanup_tmp_dir(self, report_dir: str, tmp_subdir: Optional[str] = None) -> None:
        """Remove temporary sub-test artifacts after aggregation."""
        try:
            tmp_path = Path(report_dir) / (tmp_subdir or self.tmp_subdir)
            if tmp_path.exists():
                shutil.rmtree(tmp_path)
                logging.debug(f'Cleaned tmp artifacts at: {tmp_path}')
        except Exception as e:
            logging.warning(f'Failed to clean tmp dir: {e}')

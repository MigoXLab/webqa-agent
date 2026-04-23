#!/usr/bin/env python3
"""WebQA Agent execution script.

Features:
1. Load configuration and run webqa-agent tests
2. On completion, call the Backend API to report results

Usage:
  python -m backend.gen_webqa -c config.yaml --execution-id xxx
"""

import argparse
import asyncio
import importlib.util
import json
import os
import sys
import threading
import time
from typing import Dict, Optional
from pathlib import Path

import yaml

# Shared storage and callback config
SHARED_STORAGE_PATH = os.getenv('SHARED_STORAGE_PATH', '')
BACKEND_CALLBACK_URL = os.getenv('BACKEND_CALLBACK_URL', '')

try:
    from webqa_agent.config_models.gen_config import GenConfig
    from webqa_agent.executor.gen_executor import GenExecutor
    from webqa_agent.utils import check_playwright_browsers_async, load_yaml
    WEBQA_AGENT_AVAILABLE = True
except ImportError as e:
    print(f'Warning: Failed to import webqa-agent modules: {e}')
    WEBQA_AGENT_AVAILABLE = False


def load_yaml_file(yaml_path: str) -> Dict:
    """Load YAML file."""
    with open(yaml_path, 'r', encoding='utf-8') as f:
        return yaml.safe_load(f)


def _load_cc_mini_runner():
    """Load ``run_cc_mini`` from sibling ``webqa-cc-mini`` tree."""
    from webqa_agent.utils.cc_mini_utils import load_cc_mini_runner
    return load_cc_mini_runner(module_name='webqa_cc_mini_runner_for_backend')


def _resolve_cc_mini_provider(llm_cfg: Dict) -> str:
    """Resolve provider name for cc-mini from Gen llm_config."""
    provider = str(llm_cfg.get('api', 'openai')).lower()
    if provider in ('openai', 'anthropic'):
        return provider
    if provider == 'gemini':
        # cc-mini currently uses OpenAI-compatible endpoint for Gemini style APIs.
        return 'openai'
    model_name = str(llm_cfg.get('model', '')).lower()
    if model_name.startswith('claude'):
        return 'anthropic'
    return 'openai'


def _extract_cc_mini_task(config_data: Dict) -> str:
    """Extract task text for cc-mini execution from gen config."""
    task = str(config_data.get('business_objectives') or '').strip()
    if task:
        return task
    test_cfg = config_data.get('test_config') or {}
    task = str(test_cfg.get('business_objectives') or '').strip()
    return task


def _bundled_cc_mini_skills_dir() -> Path:
    """Shipped skills next to ``webqa-cc-mini`` (plan, ui-audit, …)."""
    return Path(__file__).resolve().parent.parent / 'webqa-cc-mini' / 'skills'


def _resolve_cc_mini_skills_dir(config_data: Dict) -> Optional[str]:
    """``test_config.cc_mini_skills_dir`` or bundled ``webqa-cc-mini/skills``."""
    test_cfg = config_data.get('test_config') or {}
    explicit = str(test_cfg.get('cc_mini_skills_dir') or '').strip()
    if explicit:
        return explicit
    bundled = _bundled_cc_mini_skills_dir()
    if bundled.is_dir():
        return str(bundled)
    return None


def _build_cc_mini_file_catalog(config_data: Dict) -> Optional[str]:
    """Build an LLM-readable upload catalog from the gen config.

    Returns None when no files are available so the runner skips the whole
    file-upload section. The path resolution mirrors the standard
    ``GenExecutor`` path (see ``webqa_agent.executor.gen_executor``) so both
    runners see the same set of files when the frontend selects any.
    """
    test_files_dir = str(config_data.get('test_files_dir') or '').strip()
    if not test_files_dir:
        return None

    test_files = config_data.get('test_files')
    if test_files is not None and not isinstance(test_files, list):
        print(f'[Gen] Ignoring malformed test_files ({type(test_files).__name__}); expected list')
        test_files = None

    try:
        from webqa_agent.utils.test_file_library import TestFileLibrary
    except ImportError as exc:
        print(f'[Gen] TestFileLibrary unavailable, skipping file catalog: {exc}')
        return None

    try:
        library = TestFileLibrary(test_files_dir, file_whitelist=test_files)
    except Exception as exc:
        print(f'[Gen] Failed to scan test_files_dir ({test_files_dir}): {exc}')
        return None

    if not library.files:
        print(f'[Gen] test_files_dir={test_files_dir} has no eligible files; no catalog injected')
        return None

    catalog = library.get_catalog_for_llm()
    print(f'[Gen] cc-mini catalog prepared: {len(library.files)} file(s) from {test_files_dir}')
    return catalog or None


def _build_cc_mini_result_count(run_result) -> Dict[str, int]:
    """Map cc-mini RunResult to backend-compatible result_count."""
    try:
        from webqa_agent.executor.cc_mini_report_adapter import run_result_to_aggregated_data
        aggregated_data = run_result_to_aggregated_data(
            run_result,
            url='',
            task='',
            language='zh-CN',
        )
        count = (
            (aggregated_data.get('gen') or {})
            .get('index', {})
            .get('count', {})
        )
        total = int(count.get('total', 1) or 1)
        passed = int(count.get('passed', 0) or 0)
        failed = int(count.get('failed', 0) or 0)
        warning = int(count.get('warning', 0) or 0)
        return {
            'total': total,
            'passed': passed,
            'failed': failed,
            'warning': warning,
        }
    except Exception:
        # Conservative fallback: aborted means failed, otherwise passed.
        aborted = bool(getattr(run_result, 'aborted', False))
        return {
            'total': 1,
            'passed': 0 if aborted else 1,
            'failed': 1 if aborted else 0,
            'warning': 0,
        }


def _render_cc_mini_report(
    run_result,
    *,
    report_dir: str,
    url: str,
    task: str,
    language: str = 'zh-CN',
) -> Optional[str]:
    """Render HTML report for cc-mini run, delegates to shared utility."""
    from webqa_agent.utils.cc_mini_utils import render_cc_mini_report
    return render_cc_mini_report(
        run_result,
        report_dir=report_dir,
        url=url,
        task=task,
        language=language,
    )


async def execute_cc_mini_webqa(
    config_data: Dict,
    report_dir_override: str | None = None,
    *,
    source_file: str | None = None,
):
    """Execute cc-mini runner based on gen config payload."""
    llm_cfg = config_data.get('llm_config') or {}
    target_url = str(config_data.get('target_url') or '').strip()
    if not target_url:
        raise ValueError('cc-mini requires gen_config.target_url')

    task = _extract_cc_mini_task(config_data)
    if not task:
        raise ValueError('cc-mini requires business_objectives')

    model = str(llm_cfg.get('model') or '').strip()
    api_key = str(llm_cfg.get('api_key') or '').strip()
    if not model:
        raise ValueError('cc-mini requires llm_config.model')
    if not api_key:
        raise ValueError('cc-mini requires llm_config.api_key')

    provider = _resolve_cc_mini_provider(llm_cfg)
    base_url = llm_cfg.get('base_url')
    if provider == 'anthropic' and base_url == 'https://api.openai.com/v1':
        base_url = None

    report_cfg = config_data.get('report_config') or {}
    save_screenshots = bool(report_cfg.get('save_screenshots', False))
    screenshot_dir = (
        str(Path(report_dir_override) / 'screenshots')
        if save_screenshots and report_dir_override
        else None
    )

    run_cc_mini = _load_cc_mini_runner()
    extension_kwargs: Dict[str, object] = {}
    try:
        from webqa_agent.utils.cc_mini_utils import build_cookie_extensions_from_config
        extensions = build_cookie_extensions_from_config(
            config_data,
            source_file=source_file,
        )
    except ValueError as exc:
        raise ValueError(f'cc-mini cookie configuration error: {exc}') from exc
    if extensions is not None and hasattr(extensions, 'as_kwargs'):
        extension_kwargs = extensions.as_kwargs()

    file_catalog = _build_cc_mini_file_catalog(config_data)
    execution_id = str(config_data.get('execution_id') or os.getenv('EXECUTION_ID') or '').strip()
    progress_pusher: Optional[ProgressPusher] = None
    stdout_mode = os.getenv('WEBQA_STDOUT', '').lower() == 'true'
    if BACKEND_CALLBACK_URL and execution_id and not stdout_mode:
        progress_pusher = ProgressPusher(BACKEND_CALLBACK_URL, execution_id, interval=1.0)
        progress_pusher.start()

    try:
        result = await asyncio.to_thread(
            run_cc_mini,
            target_url,
            task,
            provider=provider,
            model=model,
            api_key=api_key,
            base_url=base_url,
            effort=(llm_cfg.get('reasoning') or {}).get('effort') if isinstance(llm_cfg.get('reasoning'), dict) else None,
            temperature=llm_cfg.get('temperature'),
            top_p=llm_cfg.get('top_p'),
            max_tokens=llm_cfg.get('max_tokens'),
            timeout=llm_cfg.get('timeout'),
            skills_dir=_resolve_cc_mini_skills_dir(config_data),
            file_catalog=file_catalog,
            save_screenshots=save_screenshots,
            screenshot_dir=screenshot_dir,
            browser_headless=True,
            # In stdout mode, external pusher may already run in main().
            # Keep display progress enabled so logs/task rows are still produced.
            enable_display_progress=bool(progress_pusher) or stdout_mode,
            progress_language=str(report_cfg.get('language') or 'zh-CN'),
            progress_no_terminal_ui=True,
            progress_log_level='info',
            **extension_kwargs,
        )
    finally:
        if progress_pusher:
            progress_pusher.stop()

    html_report_path = None
    if report_dir_override:
        language = str(report_cfg.get('language') or 'zh-CN')
        html_report_path = _render_cc_mini_report(
            result,
            report_dir=report_dir_override,
            url=target_url,
            task=task,
            language=language,
        )

    result_count = _build_cc_mini_result_count(result)
    return [{'runner': 'cc-mini'}], report_dir_override, html_report_path, result_count


async def execute_gen_webqa(config_path: str, report_dir_override: str = None):
    """Execute WebQA Agent in Gen mode.

    Args:
        config_path: Path to YAML configuration file
        report_dir_override: Report directory override

    Returns:
        (results, report_path, html_report_path, result_count)
    """
    if not WEBQA_AGENT_AVAILABLE:
        raise Exception('webqa-agent module not available')

    try:
        # Load config
        config_data = load_yaml(config_path)

        # Override report dir if provided
        if report_dir_override:
            if 'report_config' not in config_data:
                config_data['report_config'] = {}
            config_data['report_config']['report_dir'] = report_dir_override

        runner_source = str(config_data.get('runner_source') or 'standard').lower()
        if runner_source in ('cc-mini', 'cc_mini'):
            print(f'[Gen] Runner source: {runner_source}')
            return await execute_cc_mini_webqa(
                config_data,
                report_dir_override=report_dir_override,
                source_file=config_path,
            )

        # Initialize GenConfig
        gen_config = GenConfig(**config_data)

        # Check Playwright
        if not await check_playwright_browsers_async():
            raise RuntimeError('Playwright browsers not installed')

        print(f'[Gen] Starting GenExecutor for URL: {gen_config.target_url}')

        # Execute
        executor = GenExecutor(gen_config)
        results, report_path, html_report_path, result_count = await executor.execute()

        return results, report_path, html_report_path, result_count

    except Exception as e:
        print(f'[Error] Execution failed: {e}')
        import traceback
        traceback.print_exc()
        return None, None, None, None


def callback_backend(execution_id: str, status: str, result_count: Dict = None,
                     report_path: str = None, log_path: str = None, error_message: str = None):
    """Callback to Backend API."""
    if not BACKEND_CALLBACK_URL:
        print('[Callback] BACKEND_CALLBACK_URL not configured, skipping callback')
        return

    url = f'{BACKEND_CALLBACK_URL}/api/internal/executions/{execution_id}/complete'
    payload = {
        'status': status,
        'result_count': result_count,
        'report_path': report_path,
        'log_path': log_path,
        'error_message': error_message,
    }

    print(f'[Callback] Calling Backend: {url}')
    print(f'[Callback] Payload: {json.dumps(payload, indent=2, ensure_ascii=False)}')

    try:
        import requests
        response = requests.post(url, json=payload, timeout=60)
        response.raise_for_status()
        result = response.json()
        print(f'[Callback] Success: {result}')
        if result.get('oss_report_url'):
            print(f"[Callback] OSS Report URL: {result['oss_report_url']}")
    except Exception as e:
        print(f'[Callback] Failed: {e}')
        # Write marker file for recovery
        if report_path and os.path.exists(report_path):
            marker_file = os.path.join(report_path, '.callback_failed')
            try:
                with open(marker_file, 'w') as f:
                    f.write(json.dumps({
                        'execution_id': execution_id,
                        'status': status,
                        'result_count': result_count,
                        'error': str(e),
                    }))
                print(f'[Callback] Wrote failure marker: {marker_file}')
            except Exception as write_err:
                print(f'[Callback] Failed to write marker: {write_err}')


class ProgressPusher:
    """Background thread to push progress to Backend API."""

    def __init__(self, callback_url: str, execution_id: str, interval: float = 1.0):
        self.callback_url = callback_url
        self.execution_id = execution_id
        self.interval = interval
        self._stop_event = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._display = None

    def start(self):
        from webqa_agent.utils.task_display_util import Display
        self._display = Display
        self._thread = threading.Thread(target=self._push_loop, daemon=True)
        self._thread.start()

    def stop(self):
        self._stop_event.set()
        if self._thread:
            self._thread.join(timeout=5)
        self._push_progress()

    def _push_loop(self):
        while not self._stop_event.is_set():
            self._push_progress()
            time.sleep(self.interval)

    def _push_progress(self):
        if not self._display or not self._display.display:
            return

        try:
            progress = self._display.display.get_progress()
            url = f'{self.callback_url}/api/internal/executions/{self.execution_id}/progress'

            import requests
            requests.post(url, json=progress, timeout=2)
        except Exception:
            pass


def main():
    parser = argparse.ArgumentParser(description='WebQA Agent Gen Mode Execution Script')
    parser.add_argument('-c', '--config', required=True, help='YAML config file path')
    parser.add_argument('--execution-id', required=True, help='Execution ID')
    parser.add_argument('--report-dir', help='Report directory override')
    parser.add_argument('--stdout', action='store_true',
                        help='Disable file logging, push logs to Backend API instead')

    args = parser.parse_args()
    execution_id = args.execution_id
    os.environ['EXECUTION_ID'] = execution_id

    config_path = os.path.abspath(args.config)
    if not os.path.exists(config_path):
        print(f'Error: Config file not found: {config_path}')
        sys.exit(1)

    report_dir = args.report_dir
    if not report_dir and SHARED_STORAGE_PATH:
        report_dir = f'{SHARED_STORAGE_PATH}/reports/exec_{execution_id}'

    progress_pusher: Optional[ProgressPusher] = None
    if args.stdout:
        os.environ['WEBQA_STDOUT'] = 'true'
        from webqa_agent.utils.task_display_util import Display
        Display.init(language='zh-CN', no_terminal_ui=True)
        print('[Gen] stdout mode enabled, logs pushed to Backend API')

        if BACKEND_CALLBACK_URL:
            progress_pusher = ProgressPusher(BACKEND_CALLBACK_URL, execution_id, interval=1.0)

    try:
        if progress_pusher:
            progress_pusher.start()

        print('\n[Gen] Starting WebQA Agent (Gen Mode)...')
        print(f'[Gen] Config: {config_path}')
        print(f'[Gen] Report Dir: {report_dir}')

        results, report_path, html_report_path, result_count = asyncio.run(
            execute_gen_webqa(config_path, report_dir_override=report_dir)
        )

        if results is None:
            raise Exception('Gen execution failed')

        if progress_pusher:
            progress_pusher.stop()

        final_report_path = report_path or report_dir
        print(f'\n[Gen] Completed. Report: {final_report_path}')
        if result_count:
            print(f'[Gen] Result Count: {result_count}')

        if BACKEND_CALLBACK_URL:
            callback_backend(
                execution_id=execution_id,
                status='completed',
                result_count=result_count,
                report_path=final_report_path,
                log_path=None,
                error_message=None,
            )

    except KeyboardInterrupt:
        print('\n[Gen] Interrupted by user')
        if progress_pusher:
            progress_pusher.stop()
        if BACKEND_CALLBACK_URL:
            callback_backend(execution_id, 'failed', None, None, None, 'User interrupted')
        sys.exit(130)

    except Exception as e:
        print(f'\n[Gen] Error: {e}')
        import traceback
        traceback.print_exc()
        if progress_pusher:
            progress_pusher.stop()
        if BACKEND_CALLBACK_URL:
            callback_backend(execution_id, 'failed', None, None, None, str(e))
        sys.exit(1)


if __name__ == '__main__':
    main()

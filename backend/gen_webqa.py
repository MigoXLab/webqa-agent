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
import json
import os
import sys
import threading
import time
from pathlib import Path
from typing import Any, Dict, Optional

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


def _extract_cc_mini_tasks(config_data: Dict) -> list:
    """Extract task(s) for cc-mini from gen config.

    Returns a list of strings.
    """
    objectives = config_data.get('business_objectives')
    if isinstance(objectives, list):
        return [t.strip() for t in objectives if isinstance(t, str) and t.strip()]
    task = str(objectives or '').strip()
    if task:
        return [task]
    test_cfg = config_data.get('test_config') or {}
    task = str(test_cfg.get('business_objectives') or '').strip()
    return [task] if task else []


def _bundled_cc_mini_skills_dir() -> Path:
    """Shipped skills next to ``webqa-cc-mini`` (plan, ui-audit, …)."""
    return Path(__file__).resolve().parent.parent / 'webqa_agent' / 'executor' / 'flash' / 'skills'


def _resolve_cc_mini_skills_dir(config_data: Dict) -> Optional[str]:
    """``test_config.cc_mini_skills_dir`` or bundled ``webqa-cc-
    flash/skills``."""
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


async def execute_cc_mini_webqa(
    config_data: Dict,
    report_dir_override: str | None = None,
    *,
    source_file: str | None = None,
):
    """Execute cc-mini runner based on gen config payload.

    A single, unified path for both single-task (``business_objectives`` as
    a string) and multi-task (``business_objectives`` as a list). Both go
    through ``FlashExecutor`` with shared progress hooks; single-task
    is just the N=1 case of the same code path. ``render_flash_report``
    itself is a thin wrapper around ``render_flash_multi_report`` so the
    HTML output is identical to the legacy single-task path.
    """
    llm_cfg = config_data.get('llm_config') or {}
    target_url = str(config_data.get('target_url') or '').strip()
    if not target_url:
        raise ValueError('cc-mini requires gen_config.target_url')

    tasks = _extract_cc_mini_tasks(config_data)
    if not tasks:
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
    save_dataflow = bool(report_cfg.get('save_dataflow', True))
    language = str(report_cfg.get('language') or 'zh-CN')

    # Setup data flow recording (FlashExecutor's per-task sinks rely on
    # this global flag — see data_flow_reporter.record_data_flow_event_object).
    from webqa_agent.utils.data_flow_reporter import set_dataflow_enabled
    set_dataflow_enabled(bool(save_dataflow and report_dir_override))

    # Build cookie extensions (passed through FlashExecutor's shared_kwargs
    # → cli.execute_cc_mini_mode → run_cc_mini).
    extensions = None
    try:
        from webqa_agent.utils.flash_utils import \
            build_cookie_extensions_from_config
        extensions = build_cookie_extensions_from_config(
            config_data,
            source_file=source_file,
        )
    except ValueError as exc:
        raise ValueError(f'cc-mini cookie configuration error: {exc}') from exc

    file_catalog = _build_cc_mini_file_catalog(config_data)
    skills_dir = _resolve_cc_mini_skills_dir(config_data)
    effort = (
        (llm_cfg.get('reasoning') or {}).get('effort')
        if isinstance(llm_cfg.get('reasoning'), dict) else None
    )
    max_concurrent = int(config_data.get('max_concurrent_tests') or len(tasks))

    from webqa_agent.cli import execute_cc_mini_mode
    from webqa_agent.executor import FlashExecutor

    filter_model_raw = llm_cfg.get('filter_model')
    filter_model = (
        str(filter_model_raw).strip()
        if isinstance(filter_model_raw, str) and filter_model_raw.strip()
        else None
    )
    if filter_model is None and model:
        filter_model = model

    case_timeout = int(os.environ.get('WEBQA_CASE_TIMEOUT', '2400'))

    shared_kwargs: Dict[str, Any] = dict(
        url=target_url,
        provider=provider,
        model=model,
        api_key=api_key,
        base_url=base_url,
        effort=effort,
        temperature=llm_cfg.get('temperature'),
        top_p=llm_cfg.get('top_p'),
        max_tokens=llm_cfg.get('max_tokens'),
        timeout=llm_cfg.get('timeout'),
        max_time_seconds=case_timeout,
        skills_dir=skills_dir,
        file_catalog=file_catalog,
        save_screenshots=save_screenshots,
        browser_headless=True,
        browser_viewport=(1280, 720),
        log_level='info',
        extensions=extensions,
        filter_model=filter_model,
    )

    log_sink, tracker_factory = _make_cc_mini_progress_hooks()

    executor = FlashExecutor(
        shared_kwargs=shared_kwargs,
        max_concurrent=max_concurrent,
        report_dir=report_dir_override or '.',
        url=target_url,
        language=language,
        save_screenshots=save_screenshots,
        save_dataflow=save_dataflow and bool(report_dir_override),
        invoke_runner=execute_cc_mini_mode,
        log_sink=log_sink,
        tracker_factory=tracker_factory,
    )

    batch_result = await executor.execute(tasks)

    statuses = batch_result.statuses
    result_count = {
        'total': len(statuses),
        'passed': sum(1 for s in statuses if s == 'passed'),
        'failed': sum(1 for s in statuses if s == 'failed'),
        'warning': sum(1 for s in statuses if s == 'warning'),
    }
    return (
        [{'runner': 'cc-mini'}],
        report_dir_override,
        batch_result.report_path,
        result_count,
    )


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

        runner_source = str(config_data.get('runner_source') or '').lower()
        if runner_source in ('mini', 'cc-mini', 'cc_mini'):
            use_flash = True
        else:
            engine = str(config_data.get('engine', 'flash')).strip().lower()
            use_flash = (engine == 'flash')

        if use_flash:
            print('[Gen] Running on Flash engine')
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


def _make_cc_mini_progress_hooks():
    """Return ``(log_sink, tracker_factory)`` wired into ``Display.display``.

    Both hooks use only the **public** Display API:

    * ``Display.display.lock`` — exposed as a ``@property``
    * ``Display.display.captured_output`` — public attribute holding the
      log buffer that ``ProgressPusher`` reads via ``get_progress()``
    * ``Display.display(name)`` — callable that returns a ``_Tracker``
      context manager for per-case running/completed bookkeeping

    The outer ``ProgressPusher`` in ``main()`` polls ``get_progress()`` once
    per second and POSTs the snapshot to the backend; writing through the
    public surface lets it pick up logs AND per-case state without us
    duplicating any internal data structures.

    Returns ``(None, None)`` when Display has not been initialised (e.g. a
    direct CLI run without ``--stdout``).
    """
    try:
        from webqa_agent.utils.task_display_util import Display
        display_obj = Display.display
        if display_obj is None:
            return None, None
        lock = display_obj.lock
        buf = display_obj.captured_output

        def log_sink(line: str) -> None:
            stripped = line.rstrip('\n')
            if not stripped:
                return
            with lock:
                buf.write(stripped + '\n')

        # ``Display.display`` itself satisfies ``Callable[[str], _Tracker]``,
        # so the executor can use it as a tracker factory directly.
        tracker_factory = display_obj

        return log_sink, tracker_factory
    except Exception:
        return None, None


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

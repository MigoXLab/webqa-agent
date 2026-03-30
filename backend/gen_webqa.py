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
from typing import Dict, Optional

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

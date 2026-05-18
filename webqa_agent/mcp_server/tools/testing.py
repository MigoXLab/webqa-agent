"""Testing tools — run, status, report, cancel."""
from __future__ import annotations

from typing import Any, Optional

from webqa_agent.mcp_server.client import WebQAClient


def _parse_cookies(cookies: Optional[list[dict[str, Any]]]) -> Optional[list[dict[str, Any]]]:
    """Validate cookies list format."""
    if not cookies:
        return None
    if not isinstance(cookies, list):
        raise ValueError('cookies must be an array of cookie objects')
    return cookies


async def run_test(
    client: WebQAClient,
    url: str,
    task: str,
    language: str = 'zh-CN',
    model: Optional[str] = None,
    cookies: Optional[list[dict[str, Any]]] = None,
    business_id: Optional[str] = None,
    environment_id: Optional[str] = None,
    test_files: Optional[list[str]] = None,
    workers: int = 1,
    save_screenshots: bool = True,
) -> dict[str, Any]:
    """Create a cc-mini test execution."""
    gen_config: dict[str, Any] = {
        'url': url,
        'task': task,
        'report_language': language,
        'save_screenshots': save_screenshots,
    }

    cookie_list = _parse_cookies(cookies)
    if cookie_list:
        gen_config['cookies'] = cookie_list

    if test_files:
        gen_config['test_files'] = test_files

    params: dict[str, Any] = {
        'trigger_type': 'mcp_quick',
        'gen_config': gen_config,
        'workers': workers,
    }
    if model:
        params['model'] = model
    if business_id:
        params['business_id'] = business_id
    if environment_id:
        params['environment_id'] = environment_id

    return await client.create_execution(params)


async def get_test_status(client: WebQAClient, execution_id: str) -> dict[str, Any]:
    """Get current status and progress."""
    progress = await client.get_execution_progress(execution_id)
    status_val = progress.get('status', 'unknown')

    result: dict[str, Any] = {'status': status_val}

    tasks_list = []
    for t in progress.get('completed', []):
        entry: dict[str, Any] = {
            'name': t.get('name', 'unnamed'),
            'result': t.get('result', 'unknown'),
        }
        if t.get('duration'):
            entry['duration_seconds'] = round(t['duration'], 1)
        tasks_list.append(entry)

    for t in progress.get('running', []):
        entry = {
            'name': t.get('name', 'unnamed'),
            'result': 'running',
        }
        if t.get('elapsed'):
            entry['elapsed_seconds'] = round(t['elapsed'], 1)
        tasks_list.append(entry)

    if tasks_list:
        result['tasks'] = tasks_list

    logs = progress.get('logs', [])
    if logs:
        result['recent_logs'] = logs[-3:]

    return result


async def get_test_report(client: WebQAClient, execution_id: str) -> dict[str, Any]:
    """Get test report for a completed execution."""
    execution = await client.get_execution_status(execution_id)

    status_val = execution.get('status', 'unknown')
    result_count = execution.get('result_count') or {}

    result: dict[str, Any] = {
        'execution_id': execution_id,
        'status': status_val,
    }

    if result_count:
        result['passed'] = result_count.get('passed', 0)
        result['failed'] = result_count.get('failed', 0)
        result['warning'] = result_count.get('warning', 0)
        result['total'] = result_count.get('total', 0)

    started = execution.get('started_at', '')
    completed_at = execution.get('completed_at', '')
    if started and completed_at:
        from datetime import datetime
        try:
            t0 = datetime.fromisoformat(started)
            t1 = datetime.fromisoformat(completed_at)
            result['duration_seconds'] = int((t1 - t0).total_seconds())
        except (ValueError, TypeError):
            pass

    report_url = execution.get('report_url') or execution.get('oss_report_url')
    if report_url:
        result['report_url'] = report_url

    if execution.get('error_message'):
        result['error'] = execution['error_message']

    return result


async def cancel_test(client: WebQAClient, execution_id: str) -> dict[str, str]:
    """Cancel a running test execution."""
    await client.cancel_execution(execution_id)
    return {'execution_id': execution_id, 'status': 'cancelled'}

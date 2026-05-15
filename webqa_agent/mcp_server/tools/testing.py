"""Testing tools — run, status, report, cancel."""
from __future__ import annotations

import json
from typing import Any, Optional

from webqa_agent.mcp_server.client import WebQAClient


def _parse_cookies(cookies_json: Optional[str]) -> Optional[list[dict[str, Any]]]:
    """Parse cookies JSON string into list of cookie dicts."""
    if not cookies_json:
        return None
    try:
        parsed = json.loads(cookies_json)
        if not isinstance(parsed, list):
            raise ValueError('cookies must be a JSON array')
        return parsed
    except json.JSONDecodeError as e:
        raise ValueError(f'Invalid cookies JSON: {e}') from e


async def run_test(
    client: WebQAClient,
    url: str,
    task: str,
    language: str = 'zh-CN',
    model: Optional[str] = None,
    cookies: Optional[str] = None,
    workers: int = 1,
    save_screenshots: bool = True,
) -> dict[str, Any]:
    """Create a cc-mini test execution.

    Returns execution data dict.
    """
    gen_config: dict[str, Any] = {
        'url': url,
        'task': task,
        'report_language': language,
        'save_screenshots': save_screenshots,
    }

    cookie_list = _parse_cookies(cookies)
    if cookie_list:
        gen_config['cookies'] = cookie_list

    params: dict[str, Any] = {
        'trigger_type': 'mcp_quick',
        'gen_config': gen_config,
        'workers': workers,
    }
    if model:
        params['model'] = model

    return await client.create_execution(params)


async def get_test_status(client: WebQAClient, execution_id: str) -> str:
    """Get current status and progress of a test execution."""
    progress = await client.get_execution_progress(execution_id)
    status_val = progress.get('status', 'unknown')

    lines = [f'Status: {status_val}']

    completed = progress.get('completed', [])
    running = progress.get('running', [])

    if completed:
        for t in completed:
            result_val = t.get('result', '')
            tag = 'PASS' if result_val == 'passed' else 'FAIL' if result_val == 'failed' else 'WARN'
            duration = f' ({t["duration"]:.0f}s)' if t.get('duration') else ''
            lines.append(f'  [{tag}] {t.get("name", "unnamed")}{duration}')

    if running:
        for t in running:
            elapsed = f' ({t["elapsed"]:.0f}s)' if t.get('elapsed') else ''
            lines.append(f'  [RUNNING] {t.get("name", "unnamed")}{elapsed}')

    logs = progress.get('logs', [])
    if logs:
        for log_line in logs[-3:]:
            lines.append(f'  > {log_line}')

    return '\n'.join(lines)


async def get_test_report(client: WebQAClient, execution_id: str) -> str:
    """Get test report for a completed execution."""
    execution = await client.get_execution_status(execution_id)

    status_val = execution.get('status', 'unknown')
    result_count = execution.get('result_count') or {}
    error_msg = execution.get('error_message', '')

    parts = [f'Status: {status_val}']

    if result_count:
        passed = result_count.get('passed', 0)
        total = sum(result_count.values())
        parts[0] += f' ({passed}/{total} passed)'

    started = execution.get('started_at', '')
    completed_at = execution.get('completed_at', '')
    if started and completed_at:
        from datetime import datetime
        try:
            t0 = datetime.fromisoformat(started)
            t1 = datetime.fromisoformat(completed_at)
            secs = int((t1 - t0).total_seconds())
            m, s = divmod(secs, 60)
            parts.append(f'Duration: {m}m {s}s')
        except (ValueError, TypeError):
            pass

    report_url = execution.get('report_url') or execution.get('oss_report_url')
    if report_url:
        parts.append(f'Report: {report_url}')

    if error_msg:
        parts.append(f'Error: {error_msg}')

    return '\n'.join(parts)


async def cancel_test(client: WebQAClient, execution_id: str) -> str:
    """Cancel a running test execution."""
    await client.cancel_execution(execution_id)
    return f'Cancelled: {execution_id}'

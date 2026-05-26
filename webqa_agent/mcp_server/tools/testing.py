"""Testing tools — run, status, report, cancel."""
from __future__ import annotations

from pathlib import Path
from typing import Any, Optional

from webqa_agent.mcp_server.client import WebQAClient

_IMAGE_EXTENSIONS = frozenset({
    '.jpg', '.jpeg', '.png', '.gif', '.webp', '.bmp', '.svg', '.avif',
})

_UPLOAD_KEYWORDS = (
    'upload', 'file upload', 'attachment', 'attach',
    '上传', '附件', '文件上传', '图片上传', '上传文件', '上传图片',
)

_IMAGE_TASK_KEYWORDS = (
    'image', 'photo', 'picture', 'jpg', 'jpeg', 'png', '图片', '照片', '图像',
)


def _parse_cookies(cookies: Optional[list[dict[str, Any]]]) -> Optional[list[dict[str, Any]]]:
    """Validate cookies list format."""
    if not cookies:
        return None
    if not isinstance(cookies, list):
        raise ValueError('cookies must be an array of cookie objects')
    return cookies


def _task_mentions_upload(task: str) -> bool:
    text = task.lower()
    return any(keyword in text for keyword in _UPLOAD_KEYWORDS)


def _task_requests_image_upload(task: str) -> bool:
    text = task.lower()
    return any(keyword in text for keyword in _IMAGE_TASK_KEYWORDS)


def _is_business_file_name(name: str) -> bool:
    if not name or name in {'.', '..'} or '/' in name or '\\' in name:
        return False
    path = Path(name)
    if path.is_absolute() or path.anchor:
        return False
    return '..' not in path.parts


def _validate_business_file_names(test_files: Optional[list[str]]) -> list[str]:
    if not test_files:
        return []
    if not isinstance(test_files, list):
        raise ValueError('test_files must be an array of business file names')

    validated: list[str] = []
    for name in test_files:
        if not isinstance(name, str) or not name.strip():
            raise ValueError('test_files must contain non-empty business file names')
        clean_name = name.strip()
        if not _is_business_file_name(clean_name):
            raise ValueError(
                'test_files accepts business file names only. '
                'Upload local files with upload_business_file first, then pass '
                'the returned file name.'
            )
        validated.append(clean_name)
    return validated


def _image_files_from_pool(available_names: set[str]) -> list[str]:
    return sorted(
        name for name in available_names
        if Path(name).suffix.lower() in _IMAGE_EXTENSIONS
    )


async def _validate_upload_files(
    client: WebQAClient,
    *,
    business_id: Optional[str],
    task: str,
    test_files: Optional[list[str]],
) -> list[str]:
    validated_files = _validate_business_file_names(test_files)
    upload_requested = _task_mentions_upload(task)

    if validated_files and not business_id:
        raise ValueError('test_files requires business_id')
    if upload_requested and not business_id:
        raise ValueError(
            'This task asks to upload files, but no business_id was provided. '
            'Use a business file pool by passing business_id.'
        )

    if not business_id or not (validated_files or upload_requested):
        return validated_files

    business_files = await client.list_files(business_id)
    available_names = {
        item['name']
        for item in business_files
        if isinstance(item, dict) and item.get('name')
    }

    if validated_files:
        missing = [name for name in validated_files if name not in available_names]
        if missing:
            raise ValueError(
                'test_files not found in business file pool: '
                f'{", ".join(missing)}. Call list_business_files to inspect '
                'available files or upload_business_file to add local files.'
            )
        return validated_files

    if not available_names:
        raise ValueError(
            'No files are available in the business file pool for this upload '
            'test. Upload a local file with upload_business_file first or add '
            'files to the business before calling run_test.'
        )

    if _task_requests_image_upload(task):
        matching_names = _image_files_from_pool(available_names)
        if not matching_names:
            raise ValueError(
                'No image files are available in the business file pool for '
                'this upload test. Upload a suitable local file with '
                'upload_business_file first.'
            )
        return matching_names

    return validated_files


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
    """Create a Mini test execution."""
    validated_test_files = await _validate_upload_files(
        client,
        business_id=business_id,
        task=task,
        test_files=test_files,
    )
    gen_config: dict[str, Any] = {
        'url': url,
        'task': task,
        'report_language': language,
        'save_screenshots': save_screenshots,
    }

    cookie_list = _parse_cookies(cookies)
    if cookie_list:
        gen_config['cookies'] = cookie_list

    if validated_test_files:
        gen_config['test_files'] = validated_test_files

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

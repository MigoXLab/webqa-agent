import json
import logging
import os
import re
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from webqa_agent.data import ParallelTestSession, TestResult


def sanitize_case_name(name: str, keep_chars: str = '-_') -> str:
    """Sanitize case name by replacing special characters with underscores.

    This ensures consistency between case names in data and filenames.

    Args:
        name: Original case name (may contain special characters)
        keep_chars: Characters to preserve (default: '-_')

    Returns:
        Sanitized name safe for use in filenames
    """
    if not name:
        return name

    # Replace non-alphanumeric (except specified chars) with _
    sanitized = ''.join(
        c if c.isalnum() or c in keep_chars else '_'
        for c in name
    )

    # Replace multiple underscores with a single one to keep names compact
    sanitized = re.sub(r'_+', '_', sanitized)

    # Avoid returning empty string when all characters were sanitized
    if not sanitized:
        sanitized = '_'

    return sanitized


def _resolve_output_dir(report_dir: str, storage_subdir: Optional[str] = 'tmp') -> str:
    """Resolve the directory for storing sub-test artifacts.

    By default, sub-tests are stored under `report_dir/tmp` to keep the root
    report folder clean and allow safe cleanup after aggregation.
    """
    base_dir = Path(report_dir)
    target_dir = base_dir / storage_subdir if storage_subdir else base_dir
    target_dir.mkdir(parents=True, exist_ok=True)
    return str(target_dir)


def save_index_json(
    test_session: ParallelTestSession,
    report_dir: str,
    result_count: Dict[str, Any],
    test_results: Optional[List[TestResult]] = None,
    llm_config: Optional[Dict[str, Any]] = None,
    browser_config: Optional[Dict[str, Any]] = None,
    report_lang: str = 'zh-CN',
    mode: str = 'gen'
) -> None:
    """Save index.json for the test session.

    Shared between CaseMode and ParallelMode.
    """
    def _get_attr(obj, key, default=None):
        if hasattr(obj, key):
            return getattr(obj, key, default)
        if isinstance(obj, dict):
            return obj.get(key, default)
        return default

    def _get_metric_value(metrics_obj, key, default=0):
        if isinstance(metrics_obj, dict):
            return metrics_obj.get(key, default)
        return getattr(metrics_obj, key, default)

    # Counters and collections
    function_step_total = 0
    function_action_total = 0
    ux_page_total = 0
    security_scene_total = 0
    performance_total = 0
    api_request_total = 0
    console_error_total = 0
    network_error_total = 0
    results_list: List[Dict[str, Any]] = []

    # Collect result summaries and counters
    if test_results:
        for result in test_results:
            subs = result.sub_tests if result.sub_tests else [result]
            parent_cat = result.category.value if hasattr(result.category, 'value') else str(result.category)
            for sub in subs:
                sub_cat = _get_attr(sub, 'category', parent_cat) or parent_cat
                metrics = _get_attr(sub, 'metrics', {}) or {}

                # Count functional steps/pages by category
                step_count = _get_metric_value(metrics, 'total_steps', 0)
                action_count = _get_metric_value(metrics, 'total_actions', 0)
                if step_count == 0 or action_count == 0:
                    steps_list = _get_attr(sub, 'steps', [])
                    if isinstance(steps_list, list):
                        if step_count == 0:
                            step_count = len(steps_list)
                        if action_count == 0:
                            for st in steps_list:
                                actions = _get_attr(st, 'actions', [])
                                if isinstance(actions, list):
                                    action_count += len(actions)

                if sub_cat == 'function':
                    function_step_total += step_count
                    function_action_total += action_count
                elif sub_cat == 'ux':
                    ux_page_total += 1
                elif sub_cat == 'security':
                    security_scene_total += 1
                elif sub_cat == 'performance':
                    performance_total += 1

                # API count only for downstream display; keep zero if absent
                api_count = _get_metric_value(metrics, 'api_request_count', 0)
                api_request_total += api_count
                if isinstance(metrics, dict):
                    metrics.setdefault('api_request_count', api_count)

                # Console/API error counts for summary display
                console_error_total += _get_metric_value(metrics, 'console_error_count', 0)
                network_error_total += _get_metric_value(metrics, 'network_error_count', 0)

                raw_name = _get_attr(sub, 'name')
                display_name = raw_name
                safe_name = sanitize_case_name(raw_name) if isinstance(raw_name, str) else raw_name
                sub_dict = {
                    # Keep name as storage-safe value for front-end path rules
                    'name': safe_name,
                    'display_name': display_name,
                    'safe_name': safe_name,
                    'status': _get_attr(sub, 'status'),
                    'sub_test_id': _get_attr(sub, 'sub_test_id')
                }
                status = sub_dict['status']
                if hasattr(status, 'value'):
                    status = status.value
                sub_dict['status'] = str(status)
                results_list.append(sub_dict)

    # Summary items
    cat_map = {
        'function': '功能测试' if report_lang == 'zh-CN' else 'Function Test',
        'ux': '用户体验' if report_lang == 'zh-CN' else 'User Experience',
        'security': '安全扫描' if report_lang == 'zh-CN' else 'Security Scan',
        'performance': '性能评估' if report_lang == 'zh-CN' else 'Performance',
    }

    test_items: List[Dict[str, str]] = []
    if function_step_total > 0 or function_action_total > 0:
        func_steps_display = function_step_total if function_step_total > 0 else result_count.get('total', 0)
        base_item = (
            f'已检查{func_steps_display}个功能项'
            if report_lang == 'zh-CN' else
            f'Checked {func_steps_display} function items'
        )
        if function_action_total > 0:
            action_suffix = (
                f'，执行{function_action_total}个操作'
                if report_lang == 'zh-CN' else
                f', executed {function_action_total} actions'
            )
            base_item += action_suffix
        test_items.append({
            'name': cat_map['function'],
            'item': base_item
        })
    if ux_page_total > 0:
        test_items.append({
            'name': cat_map['ux'],
            'item': f'已检查{ux_page_total}个页面' if report_lang == 'zh-CN' else f'Checked {ux_page_total} pages'
        })
    if security_scene_total > 0:
        test_items.append({
            'name': cat_map['security'],
            'item': f'已检查{security_scene_total}个安全场景' if report_lang == 'zh-CN' else f'Checked {security_scene_total} security scenarios'
        })
    if performance_total > 0:
        test_items.append({
            'name': cat_map['performance'],
            'item': f'已检查{performance_total}项性能指标' if report_lang == 'zh-CN' else f'Checked {performance_total} performance items'
        })

    # API summary: only show in run mode or when count > 0
    if mode != 'gen' or api_request_total > 0:
        test_items.append({
            'name': '接口请求' if report_lang == 'zh-CN' else 'API Requests',
            'item': f'已检查{api_request_total}个接口请求' if report_lang == 'zh-CN' else f'Checked {api_request_total} API requests'
        })

    # Console/API error summary (only when any error exists)
    if console_error_total > 0 or network_error_total > 0:
        if report_lang == 'zh-CN':
            error_item = f'Console报错{console_error_total}个，接口报错{network_error_total}个'
        else:
            error_item = f'Console errors: {console_error_total}, API errors: {network_error_total}'
        test_items.append({
            'name': '控制台/接口报错' if report_lang == 'zh-CN' else 'Console/API Errors',
            'item': error_item
        })

    total_items = result_count.get('total', 0)
    has_function_item = any(item.get('name') == cat_map['function'] for item in test_items)
    if not has_function_item and total_items > 0 and mode == 'gen':
        test_items.append({
            'name': cat_map['function'],
            'item': f'已检查{total_items}个功能项' if report_lang == 'zh-CN' else f'Checked {total_items} function items'
        })
    if not test_items and total_items > 0:
        test_items.append({
            'name': '功能测试' if report_lang == 'zh-CN' else 'Function Test',
            'item': f'已检查{total_items}个功能项' if report_lang == 'zh-CN' else f'Checked {total_items} function items'
        })

    summary = test_session.llm_summary if mode == 'gen' else ''

    aggregated_results = {
        'title': 'Overview',
        'mode': mode,
        'count': result_count,
        'test_items': test_items,
        'summary': summary
    }
    results_key = 'gen_result' if mode == 'gen' else 'run_result'
    aggregated_results[results_key] = results_list

    test_session.aggregated_results = aggregated_results

    index_data = {
        'session_info': test_session.get_summary_stats(),
        'aggregated_results': aggregated_results,
        'config': {
            'target_url': test_session.target_url,
            'browser_config': browser_config,
            'llm_config': llm_config
        }
    }

    index_path = os.path.join(report_dir, 'index.json')
    try:
        os.makedirs(report_dir, exist_ok=True)
        with open(index_path, 'w', encoding='utf-8') as f:
            json.dump(index_data, f, indent=2, ensure_ascii=False, default=str)
        logging.info(f'Generated index.json: {index_path}')
    except Exception as e:
        logging.warning(f'Failed to generate index.json: {e}')


def get_result_filename(index: int, name: str, category: str, mode: str = 'gen', is_monitor: bool = False, sub_test_id: str = '') -> str:
    """Generate result filename based on sub_test_id and sanitized name.

    Rule: {sub_test_id}_{sanitized_name}_data.json

    Args:
        index: Test index (used if sub_test_id not provided)
        name: Test case name (will be sanitized)
        category: Test category (function/ux/security/performance)
        mode: Test mode ('run' or 'gen')
        is_monitor: Whether this is a monitor data file
        sub_test_id: Optional explicit sub_test_id

    Returns:
        Sanitized filename
    """
    suffix = '_monitor' if is_monitor else '_data'

    # 获取 sub_test_id
    if not sub_test_id:
        if mode == 'run':
            sub_test_id = f'case_{index}'
        else:
            sub_test_id = f'{category}_{index}'

    # Use shared sanitization logic
    safe_name = sanitize_case_name(name)

    return f'{sub_test_id}_{safe_name}{suffix}.json'


def save_test_result_json(
    test_result: Any,  # Can be TestResult or SubTestResult
    report_dir: str,
    index: int,
    name: str,
    category: str = 'function',
    mode: str = 'gen',
    sub_test_id: str = '',
    llm_config: Optional[Dict[str, Any]] = None,
    browser_config: Optional[Dict[str, Any]] = None,
    target_url: str = '',
    storage_subdir: Optional[str] = 'tmp'
) -> str:
    """Save a single test or subtest result to a JSON file."""
    try:
        output_dir = _resolve_output_dir(report_dir, storage_subdir)

        # 获取 sub_test_id，如果参数没传则从对象中尝试获取
        if not sub_test_id:
            if hasattr(test_result, 'sub_test_id'):
                sub_test_id = test_result.sub_test_id
            elif isinstance(test_result, dict):
                sub_test_id = test_result.get('sub_test_id', '')
        if not sub_test_id:
            sub_test_id = f'{category}_{index}'

        safe_name = sanitize_case_name(name) if isinstance(name, str) else name
        filename = get_result_filename(index, safe_name, category, mode, sub_test_id=sub_test_id)
        file_path = os.path.join(output_dir, filename)

        # Convert to dict
        if hasattr(test_result, 'model_dump'):
            result_dict = test_result.model_dump()
        elif hasattr(test_result, 'dict'):
            result_dict = test_result.dict()
        else:
            result_dict = test_result

        # Preserve original display name and keep a sanitized copy for reference.
        # name is kept storage-safe to match front-end lookup (name + sub_test_id).
        result_dict['name'] = safe_name
        result_dict['display_name'] = name
        result_dict['safe_name'] = safe_name

        # Ensure index is included for ordering
        result_dict['case_index'] = index
        # Ensure category is present for downstream aggregation
        result_dict.setdefault('category', category)

        metrics = result_dict.get('metrics') or {}
        if not isinstance(metrics, dict):
            metrics = {}
    # Interface/API request count
        # Only compute/store api_request_count for run mode
        if mode != 'gen':
            api_request_count = metrics.get('api_request_count')
            if api_request_count is None:
                monitoring = result_dict.get('monitoring_data', {})
                if isinstance(monitoring, dict):
                    network_data = monitoring.get('network', {})
                    if isinstance(network_data, dict):
                        api_request_count = len(network_data.get('responses', []) or []) + len(network_data.get('failed_requests', []) or [])
            api_request_count = api_request_count or 0
            metrics['api_request_count'] = api_request_count
        result_dict['metrics'] = metrics
        # Ensure sub_test_id is persisted
        result_dict.setdefault('sub_test_id', sub_test_id)

        # Add config info if not present
        if 'config' not in result_dict:
            result_dict['config'] = {
                'target_url': target_url,
                'browser_config': browser_config,
                'llm_model': llm_config.get('model', '') if llm_config else '',
                'filter_model': llm_config.get('filter_model', '') if llm_config else '',
            }

        with open(file_path, 'w', encoding='utf-8') as f:
            json.dump(result_dict, f, indent=2, ensure_ascii=False, default=str)

        logging.debug(f'Result saved to: {file_path}')
        return file_path
    except Exception as e:
        logging.warning(f'Failed to save result JSON for {name}: {e}')
        return ''


def save_monitor_data_json(
    monitoring_data: Dict[str, Any],
    report_dir: str,
    index: int,
    name: str,
    sub_test_id: str,
    category: str = 'function',
    mode: str = 'gen',
    storage_subdir: Optional[str] = 'tmp'
) -> str:
    """统一保存监控数据 JSON 的方法。"""
    try:
        output_dir = _resolve_output_dir(report_dir, storage_subdir)
        safe_name = sanitize_case_name(name) if isinstance(name, str) else name
        filename = get_result_filename(index, safe_name, category, mode, is_monitor=True, sub_test_id=sub_test_id)
        corresponding_file = get_result_filename(index, safe_name, category, mode, is_monitor=False, sub_test_id=sub_test_id)

        monitor_path = os.path.join(output_dir, filename)
        monitor_dict = {
            'sub_test_id': sub_test_id,
            # name kept storage-safe; also provide display_name for UI
            'name': safe_name,
            'display_name': name,
            'safe_name': safe_name,
            'corresponding_file': corresponding_file,
            'monitoring_data': monitoring_data,
            'timestamp': datetime.now().isoformat()
        }
        with open(monitor_path, 'w', encoding='utf-8') as f:
            json.dump(monitor_dict, f, indent=2, ensure_ascii=False, default=str)
        logging.debug(f'Monitoring data saved to: {monitor_path}')
        return monitor_path
    except Exception as e:
        logging.warning(f'Failed to save monitor JSON for {name}: {e}')
        return ''

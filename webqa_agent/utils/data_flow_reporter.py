"""Utilities for capturing and rendering gen-mode data flow reports."""

from __future__ import annotations

import hashlib
import json
import queue
import re
import threading
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

_WRITE_LOCK = threading.Lock()
_DATAFLOW_ENABLED: bool = True  # Module-level switch; set via set_dataflow_enabled()
_MAX_STRING_LENGTH = 12000
_MAX_LIST_ITEMS = 200
_SENSITIVE_KEYS = {
    'authorization',
    'cookie',
    'set-cookie',
    'api_key',
    'apikey',
    'api-key',
    'x-api-key',
    'password',
    'passwd',
    'secret',
    'credential',
    'credentials',
    'access_token',
    'refresh_token',
    'id_token',
    'session',
    'session_id',
    'sessionid',
}
_TOKEN_METRIC_KEYS = {
    'input_tokens',
    'output_tokens',
    'prompt_tokens',
    'completion_tokens',
    'total_tokens',
    'cache_read_input_tokens',
    'cache_creation_input_tokens',
}

# Background writer: events are queued and flushed by a daemon thread
# so that callers (often on the asyncio event loop) never block on file I/O.
_EVENT_QUEUE: queue.Queue[tuple[Path, str] | None] = queue.Queue()


def _bg_writer() -> None:
    """Daemon thread that drains _EVENT_QUEUE and writes events to disk."""
    while True:
        item = _EVENT_QUEUE.get()
        if item is None:
            _EVENT_QUEUE.task_done()
            break  # Shutdown sentinel
        event_path, line = item
        try:
            event_path.parent.mkdir(parents=True, exist_ok=True)
            with _WRITE_LOCK:
                with event_path.open('a', encoding='utf-8') as f:
                    f.write(line)
        except Exception:
            pass  # Best-effort; never crash the writer
        finally:
            _EVENT_QUEUE.task_done()


_WRITER_THREAD = threading.Thread(target=_bg_writer, daemon=True, name='dataflow-writer')
_WRITER_THREAD.start()


def set_dataflow_enabled(enabled: bool) -> None:
    """Toggle data-flow event recording globally."""
    global _DATAFLOW_ENABLED  # noqa: PLW0603
    _DATAFLOW_ENABLED = enabled


def _resolve_report_dir(report_dir: str | None = None) -> Path | None:
    """Resolve the active report directory for data flow artifacts."""
    if report_dir:
        return Path(report_dir)
    return None


def _round_float_by_key(key: str, value: float) -> float:
    """Round float values based on key semantics for readable output."""
    k = key.lower()
    if k.endswith('_ratio') or k == 'ratio':
        return round(value, 4)
    if 'seconds' in k or 'duration' in k or k.endswith('_ms'):
        return round(value, 2)
    return value


def _is_sensitive_key(key: str) -> bool:
    normalized = key.strip().lower().replace('-', '_')
    if normalized in _TOKEN_METRIC_KEYS:
        return False
    if normalized in {k.replace('-', '_') for k in _SENSITIVE_KEYS}:
        return True
    return normalized.endswith('_token') and normalized not in _TOKEN_METRIC_KEYS


def _looks_like_base64(value: str) -> bool:
    if len(value) < 512:
        return False
    sample = value[:512].replace('\n', '').replace('\r', '')
    return bool(re.fullmatch(r'[A-Za-z0-9+/=_-]+', sample))


def _omitted_blob(value: str, label: str = 'binary data') -> str:
    digest = hashlib.sha256(value.encode('utf-8', errors='ignore')).hexdigest()[:16]
    return f'<{label} omitted; length={len(value)}; sha256={digest}>'


def _redact_sensitive_text(value: str) -> str:
    patterns = [
        r'(?i)(authorization\s*[:=]\s*)(bearer\s+)?[^\s,;]+',
        r'(?i)((?:api[_-]?key|password|passwd|access_token|refresh_token|id_token|secret)\s*[:=]\s*)[^\s,;]+',
        r'(?i)(cookie\s*[:=]\s*)[^\n]+',
        r'(?i)(set-cookie\s*[:=]\s*)[^\n]+',
    ]
    redacted = value
    for pattern in patterns:
        redacted = re.sub(pattern, lambda m: f'{m.group(1)}<redacted>', redacted)
    return redacted


def _truncate_long_string(value: str) -> str:
    if len(value) <= _MAX_STRING_LENGTH:
        return value
    digest = hashlib.sha256(value.encode('utf-8', errors='ignore')).hexdigest()[:16]
    return (
        value[:_MAX_STRING_LENGTH]
        + f'\n<truncated; original_length={len(value)}; sha256={digest}>'
    )


def _sanitize_value(value: Any, _key: str = '', _depth: int = 0) -> Any:
    """Sanitize values for JSON/Markdown output without losing structure."""
    if _is_sensitive_key(_key):
        return '<redacted>'
    if _depth > 40:
        return '<max depth exceeded>'

    if isinstance(value, dict):
        return {
            str(k): _sanitize_value(v, _key=str(k), _depth=_depth + 1)
            for k, v in value.items()
        }

    if isinstance(value, list):
        items = [_sanitize_value(item, _key=_key, _depth=_depth + 1)
                 for item in value[:_MAX_LIST_ITEMS]]
        if len(value) > _MAX_LIST_ITEMS:
            items.append(f'<truncated list; omitted={len(value) - _MAX_LIST_ITEMS}>')
        return items

    if isinstance(value, tuple):
        items = [_sanitize_value(item, _key=_key, _depth=_depth + 1)
                 for item in value[:_MAX_LIST_ITEMS]]
        if len(value) > _MAX_LIST_ITEMS:
            items.append(f'<truncated tuple; omitted={len(value) - _MAX_LIST_ITEMS}>')
        return items

    if isinstance(value, str):
        if value.startswith('data:image'):
            return _omitted_blob(value, 'image data')
        if _key.lower() in {'data', 'image', 'image_base64'} and _looks_like_base64(value):
            return _omitted_blob(value)
        return _truncate_long_string(_redact_sensitive_text(value))

    if isinstance(value, bool) or value is None:
        return value

    if isinstance(value, int):
        return value

    if isinstance(value, float):
        return _round_float_by_key(_key, value) if _key else value

    return str(value)


def serialize_langchain_message(message: Any) -> dict[str, Any]:
    """Convert LangChain message objects to JSON-safe dictionaries."""
    return {
        'message_type': getattr(message, 'type', type(message).__name__),
        'content': _sanitize_value(getattr(message, 'content', '')),
        'tool_calls': _sanitize_value(getattr(message, 'tool_calls', None)),
        'tool_call_id': getattr(message, 'tool_call_id', None),
        'name': getattr(message, 'name', None),
    }


def serialize_intermediate_steps(intermediate_steps: Any) -> list[dict[str, Any]]:
    """Convert LangChain intermediate steps to JSON-safe dictionaries."""
    serialized_steps: list[dict[str, Any]] = []
    for step in intermediate_steps or []:
        if not isinstance(step, (list, tuple)) or len(step) < 2:
            serialized_steps.append({'raw': _sanitize_value(step)})
            continue

        action, observation = step[0], step[1]
        serialized_steps.append({
            'tool': getattr(action, 'tool', None),
            'tool_input': _sanitize_value(getattr(action, 'tool_input', None)),
            'log': getattr(action, 'log', None),
            'tool_call_id': getattr(action, 'tool_call_id', None),
            'message_log': _sanitize_value(getattr(action, 'message_log', None)),
            'observation': _sanitize_value(observation),
        })
    return serialized_steps


def record_data_flow_event(
    stage: str,
    event_type: str,
    payload: dict[str, Any],
    report_dir: str | None = None,
) -> str | None:
    """Append one sanitized data-flow event to the JSONL log.

    File I/O is offloaded to a background daemon thread so that callers
    on the asyncio event loop are never blocked.
    """
    if not _DATAFLOW_ENABLED:
        return None
    target_dir = _resolve_report_dir(report_dir)
    if target_dir is None:
        return None

    try:
        event_path = target_dir / 'data_flow_events.jsonl'
        event = {
            'timestamp': datetime.now().isoformat(timespec='milliseconds'),
            'stage': stage,
            'event_type': event_type,
            'payload': _sanitize_value(payload),
        }
        line = json.dumps(event, ensure_ascii=False) + '\n'
        _EVENT_QUEUE.put_nowait((event_path, line))
        return str(event_path)
    except Exception:
        return None


def record_data_flow_event_object(
    event: dict[str, Any],
    report_dir: str | None = None,
) -> str | None:
    """Append a pre-shaped data-flow event to the JSONL log.

    Unlike ``record_data_flow_event()``, this preserves the event timestamp
    captured at the source.  It is used by cc-mini, where timing is measured in
    the Engine thread and only written by WebQA's CLI bridge.
    """
    if not _DATAFLOW_ENABLED:
        return None
    target_dir = _resolve_report_dir(report_dir)
    if target_dir is None:
        return None

    try:
        event_path = target_dir / 'data_flow_events.jsonl'
        shaped = {
            'timestamp': str(event.get('timestamp') or datetime.now().isoformat(timespec='milliseconds')),
            'stage': str(event.get('stage') or 'unknown'),
            'event_type': str(event.get('event_type') or 'unknown'),
            'payload': _sanitize_value(event.get('payload', {})),
        }
        line = json.dumps(shaped, ensure_ascii=False) + '\n'
        _EVENT_QUEUE.put_nowait((event_path, line))
        return str(event_path)
    except Exception:
        return None


def flush_data_flow_events() -> None:
    """Block until the background writer has drained all queued events."""
    _EVENT_QUEUE.join()


def _truncate_text(value: str, limit: int = 120) -> str:
    """Keep report headings short and readable."""
    compact = ' '.join(value.split())
    if len(compact) <= limit:
        return compact
    return compact[: limit - 3] + '...'


def _event_title(event: dict[str, Any]) -> str:
    """Generate a readable title for one event."""
    event_type = str(event.get('event_type', 'unknown'))
    stage = str(event.get('stage', 'unknown'))
    payload = event.get('payload', {})

    if event_type == 'stage1_filter_request':
        return 'Stage 1 Filter Request'
    if event_type == 'stage1_filter_response':
        return 'Stage 1 Filter Response'
    if event_type == 'stage2_case_planning_request':
        return 'Stage 2 Case Planning Request'
    if event_type == 'stage2_case_planning_response':
        return 'Stage 2 Case Planning Response'
    if event_type == 'stage2_case_planning_parse_error':
        return 'Stage 2 Case Planning Parse Error'
    if event_type == 'planned_test_cases':
        return 'Planned Test Cases'
    if event_type == 'case_execution_start':
        case_name = payload.get('case_name') or payload.get('case', {}).get('name', '')
        return f'Case Execution Start · {_truncate_text(str(case_name), 90)}'
    if event_type == 'step_request':
        step_index = payload.get('planned_step_index', '?')
        step_type = payload.get('step_type', 'Step')
        instruction = _truncate_text(str(payload.get('instruction', '')), 90)
        return f'Step {step_index} Request · {step_type} · {instruction}'
    if event_type == 'step_input_sent':
        step_index = payload.get('planned_step_index', '?')
        step_type = payload.get('step_type', 'Step')
        return f'Step {step_index} Input Sent · {step_type}'
    if event_type == 'step_response':
        step_index = payload.get('planned_step_index', '?')
        step_type = payload.get('step_type', 'Step')
        return f'Step {step_index} Response · {step_type}'
    if event_type == 'preamble_request':
        step_index = payload.get('preamble_step_index', payload.get('preamble_index', '?'))
        instruction = _truncate_text(str(payload.get('instruction', '')), 90)
        return f'Preamble {step_index} Request · {instruction}'
    if event_type == 'preamble_response':
        step_index = payload.get('preamble_step_index', payload.get('preamble_index', '?'))
        return f'Preamble {step_index} Response'
    if event_type == 'action_plan_request':
        instruction = _truncate_text(str(payload.get('instruction', '')), 90)
        return f'Nested UI Action Plan Request · {instruction}'
    if event_type == 'action_plan_response':
        instruction = _truncate_text(str(payload.get('instruction', '')), 90)
        return f'Nested UI Action Plan Response · {instruction}'
    if event_type == 'assertion_request':
        assertion = _truncate_text(str(payload.get('assertion', '')), 90)
        return f'Nested Assertion Request · {assertion}'
    if event_type == 'assertion_response':
        assertion = _truncate_text(str(payload.get('assertion', '')), 90)
        return f'Nested Assertion Response · {assertion}'
    if event_type == 'check_action_request':
        instruction = _truncate_text(str(payload.get('instruction', '')), 90)
        return f'Nested Check Action Request · {instruction}'
    if event_type == 'check_action_response':
        instruction = _truncate_text(str(payload.get('instruction', '')), 90)
        return f'Nested Check Action Response · {instruction}'
    if event_type == 'ux_typo_request':
        return 'Nested UX Typo Request'
    if event_type == 'ux_typo_response':
        return 'Nested UX Typo Response'
    if event_type == 'ux_layout_request':
        return 'Nested UX Layout Request'
    if event_type == 'ux_layout_response':
        return 'Nested UX Layout Response'
    if event_type == 'dom_change_request':
        return 'Dynamic Step Analysis Request'
    if event_type == 'dom_change_response':
        return 'Dynamic Step Analysis Response'
    if event_type == 'failure_recovery_request':
        return 'Failure Recovery Request'
    if event_type == 'failure_recovery_response':
        return 'Failure Recovery Response'
    if event_type == 'reflection_request':
        case_name = payload.get('case_name', '')
        return f'Reflection Request · {_truncate_text(str(case_name), 90)}'
    if event_type == 'reflection_response':
        case_name = payload.get('case_name', '')
        return f'Reflection Response · {_truncate_text(str(case_name), 90)}'
    if event_type == 'replan_enqueue':
        case_name = payload.get('case_name', '')
        return f'Replan Enqueue · {_truncate_text(str(case_name), 90)}'
    if event_type == 'case_execution_result':
        case_name = payload.get('case_name', '')
        return f'Result · {_truncate_text(str(case_name), 90)}'
    if event_type == 'run_test_cases_summary':
        return 'Run Test Cases Summary'
    if event_type == 'cc_mini_llm_call':
        model = payload.get('model') or payload.get('group_label') or 'LLM'
        turn_id = payload.get('turn_id', '?')
        return f'LLM Call T{turn_id} · {_truncate_text(str(model), 80)}'
    if event_type == 'cc_mini_tool_call':
        tool_name = payload.get('tool_name') or payload.get('group_label') or 'Tool'
        return f'Tool Call · {_truncate_text(str(tool_name), 90)}'
    if event_type == 'cc_mini_tool_result':
        tool_name = payload.get('tool_name') or payload.get('group_label') or 'Tool'
        status = payload.get('status') or 'done'
        return f'Tool Result · {_truncate_text(str(tool_name), 90)} · {status}'
    if event_type == 'cc_mini_error':
        return f'cc-mini Error · {_truncate_text(str(payload.get("message", "")), 90)}'

    return f'{stage} · {event_type}'


def _extract_token_usage(payload: dict[str, Any]) -> dict[str, int]:
    """Extract token usage from event payload with multiple fallback paths."""
    # Also search inside nested 'case_result' dict (used by case_execution_result)
    case_result = payload.get('case_result', {}) if isinstance(payload.get('case_result'), dict) else {}
    candidates: list[Any] = [
        payload.get('token_usage'),
        payload.get('usage'),
        payload.get('usage_details'),
        payload.get('llm_metrics', {}).get('token_usage')
        if isinstance(payload.get('llm_metrics'), dict)
        else None,
        case_result.get('llm_metrics', {}).get('token_usage')
        if isinstance(case_result.get('llm_metrics'), dict)
        else None,
    ]

    for candidate in candidates:
        if not isinstance(candidate, dict):
            continue
        usage: dict[str, int] = {}
        for key in ('prompt_tokens', 'completion_tokens', 'total_tokens'):
            value = candidate.get(key)
            if isinstance(value, (int, float)):
                usage[key] = int(value)
        input_value = candidate.get('input_tokens')
        if 'prompt_tokens' not in usage and isinstance(input_value, (int, float)):
            usage['prompt_tokens'] = int(input_value)
        output_value = candidate.get('output_tokens')
        if 'completion_tokens' not in usage and isinstance(output_value, (int, float)):
            usage['completion_tokens'] = int(output_value)
        if 'total_tokens' not in usage and {
            'prompt_tokens',
            'completion_tokens',
        }.issubset(usage):
            usage['total_tokens'] = usage['prompt_tokens'] + usage['completion_tokens']
        if usage:
            return usage
    return {}


def _extract_duration_seconds(payload: dict[str, Any]) -> float | None:
    """Extract event duration from payload with fallback."""
    duration = payload.get('duration_seconds')
    if isinstance(duration, (int, float)):
        return float(duration)

    llm_metrics = payload.get('llm_metrics')
    if isinstance(llm_metrics, dict):
        llm_duration = llm_metrics.get('duration_seconds')
        if isinstance(llm_duration, (int, float)):
            return float(llm_duration)

    # Fallback: search inside nested 'case_result' dict
    case_result = payload.get('case_result')
    if isinstance(case_result, dict):
        cr_duration = case_result.get('duration_seconds')
        if isinstance(cr_duration, (int, float)):
            return float(cr_duration)
        cr_llm = case_result.get('llm_metrics')
        if isinstance(cr_llm, dict):
            cr_llm_dur = cr_llm.get('duration_seconds')
            if isinstance(cr_llm_dur, (int, float)):
                return float(cr_llm_dur)

    return None


def _parse_iso_ts(value: str) -> datetime | None:
    """Parse ISO timestamp string safely."""
    if not value:
        return None
    try:
        return datetime.fromisoformat(value)
    except Exception:
        return None


def _build_interactive_gantt_tasks(
    events: list[dict[str, Any]],
    *,
    group_mode: str = 'case',
) -> list[dict[str, Any]]:
    """Build normalized gantt task entries for interactive HTML rendering."""
    tasks: list[dict[str, Any]] = []
    sorted_events = sorted(events, key=lambda e: str(e.get('timestamp', '')))
    for index, event in enumerate(sorted_events):
        payload = event.get('payload', {})
        if not isinstance(payload, dict):
            payload = {}

        stage = str(event.get('stage', 'unknown'))
        event_type = str(event.get('event_type', 'unknown'))
        ts = _parse_iso_ts(str(event.get('timestamp', '')))
        if ts is None:
            continue

        # Metadata / aggregate events carry cumulative stats from child steps;
        # treat them as zero-duration, zero-token nodes (consistent with Gen mode).
        is_metadata_event = event_type in ('case_execution_start', 'case_execution_result')
        if is_metadata_event:
            duration_seconds = 0.0
            token_usage: dict[str, int] = {}
        else:
            duration_seconds = max(float(_extract_duration_seconds(payload) or 0.0), 0.0)
            token_usage = _extract_token_usage(payload)
        start_ts = ts if duration_seconds <= 0.0 else ts - timedelta(seconds=duration_seconds)

        tasks.append(
            {
                'id': f'{stage}_{index}',
                'stage': stage,
                'event_type': event_type,
                'title': _event_title(event),
                'start_ts': start_ts.isoformat(timespec='seconds'),
                'end_ts': ts.isoformat(timespec='seconds'),
                'start_ms': int(start_ts.timestamp() * 1000),
                'end_ms': int(ts.timestamp() * 1000),
                'duration_seconds': duration_seconds,
                'group_key': payload.get('group_key'),
                'group_label': payload.get('group_label'),
                'node_kind': payload.get('node_kind'),
                'call_id': payload.get('call_id') or payload.get('correlation_id'),
                'token_usage': {
                    'prompt_tokens': int(token_usage.get('prompt_tokens', 0)),
                    'completion_tokens': int(token_usage.get('completion_tokens', 0)),
                    'total_tokens': int(token_usage.get('total_tokens', 0)),
                },
                'event': {
                    'timestamp': str(event.get('timestamp', '')),
                    'stage': stage,
                    'event_type': event_type,
                    'payload': payload,
                },
            }
        )

    # Merge request/response pairs into single duration-spanning nodes.
    # This prevents zero-duration metadata nodes from visually overlapping
    # when request_end and response_start are nearly simultaneous.
    if group_mode == 'case':
        tasks = _merge_request_response_pairs(tasks)

    return tasks


# Request → Response pairing rules: request_event_type → response_event_type
_REQUEST_RESPONSE_PAIRS: dict[str, str] = {
    'stage1_filter_request': 'stage1_filter_response',
    'stage2_case_planning_request': 'stage2_case_planning_response',
}


def _merge_request_response_pairs(tasks: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Merge known request/response event pairs into single span nodes.

    For each pair defined in ``_REQUEST_RESPONSE_PAIRS``, the request task is
    widened to span from its own start_ms to the response's end_ms and the
    standalone response task is dropped.  Token usage from the response is
    folded into the merged node.  The response payload is preserved under
    ``event.response_payload``.
    """
    by_event_type: dict[str, dict[str, Any]] = {}
    for t in tasks:
        by_event_type[t['event_type']] = t

    drop_ids: set[str] = set()

    for req_type, resp_type in _REQUEST_RESPONSE_PAIRS.items():
        req = by_event_type.get(req_type)
        resp = by_event_type.get(resp_type)
        if req is None or resp is None:
            continue

        # Widen request node to cover request→response span
        req['end_ts'] = resp['end_ts']
        req['end_ms'] = resp['end_ms']
        duration = max((req['end_ms'] - req['start_ms']) / 1000, 0.0)
        req['duration_seconds'] = round(duration, 2)

        # Fold token usage from response into merged node
        resp_usage = resp.get('token_usage', {})
        req_usage = req.get('token_usage', {})
        for key in ('prompt_tokens', 'completion_tokens', 'total_tokens'):
            req_usage[key] = int(req_usage.get(key, 0)) + int(resp_usage.get(key, 0))

        # Preserve response payload for detail panel
        req['event']['response_payload'] = resp.get('event', {}).get('payload', {})

        # Use the response event_type so includeTask (which drops *_request) keeps it
        req['event_type'] = resp_type
        req['event']['event_type'] = resp_type

        # Update title to indicate merged span
        req['title'] = req['title'].replace(' Request', '')

        drop_ids.add(resp['id'])

    return [t for t in tasks if t['id'] not in drop_ids]


def _render_interactive_gantt_html(
    tasks: list[dict[str, Any]],
    *,
    group_mode: str = 'case',
) -> str:
    """Render standalone interactive tree+heatmap HTML."""
    normalized_group_mode = 'tool' if group_mode == 'tool' else 'case'
    tasks_json = (
        json.dumps(tasks, ensure_ascii=False)
        .replace('</', '<\\/')
        .replace('\u2028', '\\u2028')
        .replace('\u2029', '\\u2029')
    )
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0" />
  <title>Interactive Data Flow Tree</title>
  <style>
    :root {{
      --bg: #f8fafc;
      --panel: #ffffff;
      --line: #e2e8f0;
      --text: #1e293b;
      --muted: #64748b;
      --selected: #2563eb;
    }}
    * {{ box-sizing: border-box; }}
    body {{
      margin: 0;
      font-family: ui-sans-serif, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
      background: var(--bg);
      color: var(--text);
      height: 100vh;
      overflow: hidden;
    }}
    .layout {{
      display: flex;
      height: 100vh;
    }}
    .left {{
      display: flex;
      flex-direction: column;
      min-width: 200px;
      flex: 1 1 65%;
      overflow: hidden;
    }}
    .header {{
      padding: 10px 16px;
      border-bottom: 1px solid var(--line);
      background: var(--panel);
      font-size: 13px;
      font-weight: 500;
      color: var(--muted);
      flex-shrink: 0;
    }}
    .tree-wrap {{
      overflow: auto;
      padding: 12px 16px 20px;
      min-width: 0;
      flex: 1;
      cursor: grab;
    }}
    .tree-wrap.dragging {{ cursor: grabbing; }}
    .tree-viewport {{
      position: relative;
    }}
    .tree-canvas {{
      position: relative;
      min-width: 920px;
      min-height: 360px;
    }}
    .links {{
      position: absolute;
      inset: 0;
      width: 100%;
      height: 100%;
      pointer-events: none;
      z-index: 1;
    }}
    .node {{
      position: absolute;
      height: 32px;
      min-width: 0;
      border-radius: 6px;
      border: none;
      box-shadow: 0 1px 3px rgba(0,0,0,0.08);
      color: #fff;
      font-size: 11px;
      font-weight: 500;
      line-height: 32px;
      padding: 0 10px;
      white-space: nowrap;
      overflow: hidden;
      text-overflow: ellipsis;
      text-align: center;
      user-select: none;
      cursor: pointer;
      z-index: 2;
      transition: box-shadow 0.15s, filter 0.15s;
    }}
    .node:hover {{
      box-shadow: 0 3px 10px rgba(0,0,0,0.15);
      filter: brightness(1.08);
    }}
    .node.selected {{
      outline: 2px solid var(--selected);
      outline-offset: 2px;
      z-index: 3;
    }}
    /* --- resizer --- */
    .resizer {{
      width: 5px;
      cursor: col-resize;
      background: var(--line);
      flex-shrink: 0;
      transition: background 0.15s;
    }}
    .resizer:hover, .resizer.active {{ background: #94a3b8; }}
    /* --- right panel --- */
    .right {{
      display: flex;
      flex-direction: column;
      min-width: 120px;
      flex: 0 0 35%;
      overflow: hidden;
      background: var(--panel);
      border-left: 1px solid var(--line);
    }}
    .detail-header {{
      padding: 10px 16px;
      border-bottom: 1px solid var(--line);
      background: var(--panel);
      font-size: 13px;
      font-weight: 500;
      color: var(--muted);
      display: flex;
      align-items: center;
      justify-content: space-between;
      flex-shrink: 0;
    }}
    .collapse-btn {{
      background: none;
      border: 1px solid var(--line);
      border-radius: 4px;
      cursor: pointer;
      font-size: 14px;
      color: var(--muted);
      padding: 2px 8px;
      line-height: 1;
    }}
    .collapse-btn:hover {{ background: #f1f5f9; color: var(--text); }}
    .detail-body {{
      padding: 12px 16px;
      overflow: auto;
      min-height: 0;
      flex: 1;
    }}
    pre {{
      margin: 0;
      white-space: pre-wrap;
      word-break: break-all;
      font-size: 12px;
      line-height: 1.5;
      color: #334155;
    }}
    .empty {{
      color: var(--muted);
      font-size: 13px;
      padding: 8px 0;
    }}
    .right.collapsed {{
      display: none;
    }}
    .resizer.collapsed {{
      display: none;
    }}
    .tooltip {{
      position: fixed;
      pointer-events: none;
      z-index: 9999;
      max-width: 380px;
      background: rgba(15,23,42,0.94);
      color: #e2e8f0;
      border-radius: 8px;
      padding: 8px 12px;
      font-size: 12px;
      line-height: 1.5;
      white-space: pre-line;
      box-shadow: 0 8px 24px rgba(0,0,0,0.18);
      display: none;
    }}
  </style>
</head>
<body>
  <div class="layout" id="layout">
    <section class="left" id="leftPanel">
      <div class="header" style="display:flex;align-items:center;justify-content:space-between;">
        <span style="display:flex;align-items:center;gap:16px;">
          <span style="display:inline-flex;align-items:center;gap:4px;"><span style="display:inline-block;width:12px;height:12px;border-radius:3px;background:#5b8def;"></span> LLM Node</span>
          <span style="display:inline-flex;align-items:center;gap:4px;"><span style="display:inline-block;width:12px;height:12px;border-radius:3px;background:#a0aec0;"></span> Non-LLM Node</span>
          <span style="display:inline-flex;align-items:center;gap:6px;color:#94a3b8;font-size:11px;">|<span style="display:inline-block;width:48px;height:10px;border-radius:3px;background:linear-gradient(to right, hsl(220,75%,75%), hsl(220,80%,40%));"></span> darker = more tokens, longer = more time</span>
        </span>
        <button class="collapse-btn" id="toggleJsonBtn" title="Toggle JSON panel">◀ JSON</button>
      </div>
      <div class="tree-wrap" id="treeWrap">
        <div id="treeViewport" class="tree-viewport">
          <div id="treeCanvas" class="tree-canvas"></div>
        </div>
      </div>
    </section>
    <div class="resizer" id="resizer"></div>
    <aside class="right" id="rightPanel">
      <div class="detail-header">Node JSON Detail</div>
      <div class="detail-body">
        <pre id="detail">Click any node to inspect event JSON.</pre>
      </div>
    </aside>
  </div>
  <div id="tooltip" class="tooltip"></div>
  <script>
    window.__ganttTasks = {tasks_json};
    const groupMode = "{normalized_group_mode}";
    const rawTasks = Array.isArray(window.__ganttTasks) ? window.__ganttTasks : [];
    const treeWrap = document.getElementById("treeWrap");
    const treeViewport = document.getElementById("treeViewport");
    const treeCanvas = document.getElementById("treeCanvas");
    const detailEl = document.getElementById("detail");
    const tooltipEl = document.getElementById("tooltip");
    let tipTimer = null;

    function showTooltip(text, x, y) {{
      tooltipEl.textContent = text;
      tooltipEl.style.display = "block";
      tooltipEl.style.left = `${{Math.min(x + 14, window.innerWidth - 400)}}px`;
      tooltipEl.style.top = `${{Math.min(y + 14, window.innerHeight - 140)}}px`;
    }}
    function hideTooltip() {{
      clearTimeout(tipTimer);
      tipTimer = null;
      tooltipEl.style.display = "none";
    }}

    /* --- resizable splitter --- */
    const layout = document.getElementById("layout");
    const leftPanel = document.getElementById("leftPanel");
    const rightPanel = document.getElementById("rightPanel");
    const resizer = document.getElementById("resizer");
    const toggleBtn = document.getElementById("toggleJsonBtn");
    let resizing = false;
    let panelHidden = true;
    /* start with JSON panel hidden */
    rightPanel.classList.add("collapsed");
    resizer.classList.add("collapsed");
    leftPanel.style.flex = "1 1 100%";

    resizer.addEventListener("mousedown", (e) => {{
      e.preventDefault();
      resizing = true;
      resizer.classList.add("active");
    }});
    window.addEventListener("mousemove", (e) => {{
      if (!resizing) return;
      const rect = layout.getBoundingClientRect();
      const pct = ((e.clientX - rect.left) / rect.width) * 100;
      const clamped = Math.min(Math.max(pct, 20), 85);
      leftPanel.style.flex = `0 0 ${{clamped}}%`;
      rightPanel.style.flex = `0 0 ${{100 - clamped}}%`;
    }});
    window.addEventListener("mouseup", () => {{
      if (resizing) {{ resizing = false; resizer.classList.remove("active"); }}
    }});

    function showJsonPanel() {{
      panelHidden = false;
      rightPanel.classList.remove("collapsed");
      resizer.classList.remove("collapsed");
      leftPanel.style.flex = "1 1 65%";
      rightPanel.style.flex = "0 0 35%";
      toggleBtn.textContent = "JSON ▶";
    }}
    function hideJsonPanel() {{
      panelHidden = true;
      rightPanel.classList.add("collapsed");
      resizer.classList.add("collapsed");
      leftPanel.style.flex = "1 1 100%";
      toggleBtn.textContent = "◀ JSON";
    }}
    toggleBtn.addEventListener("click", () => {{
      if (panelHidden) showJsonPanel(); else hideJsonPanel();
    }});

    function getCaseKey(task) {{
      const payload = (task.event && task.event.payload) || {{}};
      const caseRef = payload.case || payload.case_result || payload.recorded_case || {{}};
      const cid = payload.case_id || caseRef.case_id || "";
      const cname = payload.case_name || payload.name || caseRef.case_name || caseRef.name || "";
      if (cid) return `id:${{cid}}`;
      if (cname) return `name:${{cname}}`;
      return "global";
    }}

    function getGroupKey(task) {{
      if (groupMode !== "tool") return getCaseKey(task);
      const payload = (task.event && task.event.payload) || {{}};
      const key = task.group_key || payload.group_key || payload.tool_name || payload.tool || payload.model || "unknown";
      return String(key || "unknown");
    }}

    function groupLabel(key, tasks, index) {{
      if (groupMode !== "tool") {{
        const m = String(key).match(/id:case_(\\d+)/);
        return m ? `Case ${{m[1]}}` : `Case ${{index + 1}}`;
      }}
      const found = tasks.find((t) => getGroupKey(t) === key);
      const payload = (found && found.event && found.event.payload) || {{}};
      return String(found?.group_label || payload.group_label || payload.tool_name || payload.model || key);
    }}

    function shortLabel(task, caseIndex) {{
      const t = String(task.title || "");
      const et = String(task.event_type || "");
      const p = (task.event && task.event.payload) || {{}};
      const stepIdx = p.planned_step_index || "";
      const stepType = String(p.step_type || "").toLowerCase();

      if (groupMode === "tool") {{
        if (et === "cc_mini_llm_call") return `LLM T${{p.turn_id || "?"}}`;
        if (et === "cc_mini_tool_result") {{
          const rawTool = String(p.tool_name || p.group_label || "Tool");
          /* row gutter already shows full name; bar only needs the action verb */
          const shortTool = rawTool.replace(/^mcp__[^_]+(?:_[^_]+)*?__/, "");
          return shortTool.length > 18 ? shortTool.slice(0, 18) + "…" : shortTool;
        }}
        if (et === "cc_mini_error") {{
          const ti = p.turn_id || "?";
          const at = Number(p.attempt || 1);
          return at > 1 ? `Err T${{ti}}·a${{at}}` : `Err T${{ti}}`;
        }}
        const label = String(p.group_label || p.tool_name || p.model || t || et);
        return label.length > 20 ? label.slice(0, 20) + "…" : label;
      }}

      /* step_response: name by actual step_type */
      if (et === "step_response" && stepIdx) {{
        if (stepType.includes("action")) return `S${{stepIdx}} Action`;
        if (stepType.includes("assert")) return `S${{stepIdx}} Verify`;
        if (stepType.includes("verify")) return `S${{stepIdx}} Verify`;
        if (stepType.includes("ux")) return `S${{stepIdx}} UX`;
        return `S${{stepIdx}} Step`;
      }}
      /* step title fallback */
      const m = t.match(/Step\\s+(\\d+)\\s+(Request|Input Sent|Response)/i);
      if (m) {{
        const idx = m[1];
        if (stepType.includes("action")) return `S${{idx}} Action`;
        if (stepType.includes("assert")) return `S${{idx}} Verify`;
        if (stepType.includes("verify")) return `S${{idx}} Verify`;
        if (stepType.includes("ux")) return `S${{idx}} UX`;
        return `S${{idx}} Step`;
      }}
      if (et.includes("stage1_filter")) return "Filter Element";
      if (et.includes("stage2_case_planning")) return "Planning";
      if (et === "planned_test_cases") return "Planned";
      if (et === "preamble_response") {{
        const pi = p.preamble_step_index || "";
        const ps = String(p.status || "");
        return ps === "ok" ? `P${{pi}} Preamble` : `P${{pi}} Preamble ${{ps}}`;
      }}
      if (et === "case_execution_start") return caseIndex != null ? `Case ${{caseIndex}}` : "Case Start";
      if (et === "case_execution_result") return "Result";
      if (et === "reflection_request") return "Reflect Req";
      if (et === "reflection_response") return "Reflect Resp";
      if (et.includes("reflection")) return et.includes("request") ? "Reflect Req" : "Reflect Resp";
      if (et.includes("ux_")) return et.includes("layout") ? "UX Layout" : "UX Typo";
      return t.length > 20 ? t.slice(0, 20) + "…" : t;
    }}

    function includeTask(task) {{
      const et = String(task.event_type || "");
      const st = String(task.stage || "");
      if (st === "summary" || et === "run_test_cases_summary") return false;
      if (groupMode === "tool") {{
        if (et === "cc_mini_tool_call") return false;
        return true;
      }}
      /* keep step_input_sent as fallback when step_response is missing */
      if (et.endsWith("_request") && !et.includes("reflection")) return false;
      if (et === "step_request") return false;
      return true;
    }}

    function dedupKey(task) {{
      let et = String(task.event_type || "");
      const st = String(task.stage || "");
      const ck = getGroupKey(task);
      const p = (task.event && task.event.payload) || {{}};
      if (groupMode === "tool") {{
        const cid = task.call_id || p.call_id || p.correlation_id || p.tool_call_id || task.id;
        const seq = p.sequence ?? "";
        return `${{st}}|${{et}}|${{ck}}|${{cid}}|${{seq}}|${{task.id}}`;
      }}
      const stepIdx = p.planned_step_index ?? p.step_index ?? "";
      /* normalize step_input_sent → step_response so dedup prefers step_response */
      if (et === "step_input_sent") et = "step_response";
      return `${{st}}|${{et}}|${{ck}}|${{stepIdx}}`;
    }}

    function dedup(tasks) {{
      const seen = new Map();
      const result = [];
      for (const t of tasks) {{
        const key = dedupKey(t);
        if (seen.has(key)) {{
          const prev = seen.get(key);
          if ((t.duration_seconds || 0) > (prev.duration_seconds || 0)) {{
            const idx = result.indexOf(prev);
            if (idx >= 0) result[idx] = t;
            seen.set(key, t);
          }}
        }} else {{
          seen.set(key, t);
          result.push(t);
        }}
      }}
      return result;
    }}

    function phaseOf(task) {{
      const et = String(task.event_type || "");
      const st = String(task.stage || "");
      if (groupMode === "tool") {{
        const p = (task.event && task.event.payload) || {{}};
        return p.node_kind === "llm" ? "plan" : "execute";
      }}
      if (st === "planning" && !et.includes("reflection")) return "plan";
      if (et === "case_execution_start") return "case";
      if (et === "case_execution_result" || et.includes("reflection") || et === "replan_enqueue") return "reflect";
      return "execute";
    }}

    function isLlmTask(task) {{
      /* Metadata / aggregate nodes are never LLM tasks even if they carry
         cumulative duration or token stats from their child steps. */
      const et = task.event_type || "";
      if (groupMode === "tool") {{
        const p = (task.event && task.event.payload) || {{}};
        return p.node_kind === "llm";
      }}
      if (et === "case_execution_start" || et === "case_execution_result") return false;
      const d = Number(task.duration_seconds || 0);
      const u = task.token_usage || {{}};
      return d > 0 || (u.total_tokens || 0) > 0;
    }}

    /* color depth ∝ token usage: light-blue → deep-blue for LLM nodes */
    function phaseBg(phase, task, maxTokens) {{
      if (!isLlmTask(task)) return "#a0aec0";

      const totalTokens = (task.token_usage || {{}}).total_tokens || 0;
      if (maxTokens <= 0) return "hsl(220, 75%, 65%)";
      const ratio = Math.sqrt(totalTokens / maxTokens);
      const lightness = 75 - ratio * 35;
      const saturation = 75 + ratio * 5;
      return `hsl(220, ${{saturation}}%, ${{lightness}}%)`;
    }}


    function connectSvg(width, height, links) {{
      const svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
      svg.setAttribute("class", "links");
      svg.setAttribute("viewBox", `0 0 ${{width}} ${{height}}`);
      svg.setAttribute("preserveAspectRatio", "none");
      for (const l of links) {{
        const p = document.createElementNS("http://www.w3.org/2000/svg", "path");
        const c1x = l.x1 + (l.x2 - l.x1) * 0.45;
        const c2x = l.x1 + (l.x2 - l.x1) * 0.75;
        p.setAttribute("d", `M${{l.x1}} ${{l.y1}} C ${{c1x}} ${{l.y1}}, ${{c2x}} ${{l.y2}}, ${{l.x2}} ${{l.y2}}`);
        p.setAttribute("fill", "none");
        p.setAttribute("stroke", "#cbd5e1");
        p.setAttribute("stroke-width", "1.4");
        svg.appendChild(p);
      }}
      return svg;
    }}

    function renderTree() {{
      /* helper: format Date → HH:MM:SS */
      function fmtTime(d) {{
        return String(d.getHours()).padStart(2,"0") + ":" +
               String(d.getMinutes()).padStart(2,"0") + ":" +
               String(d.getSeconds()).padStart(2,"0");
      }}
      const tasks = dedup(rawTasks.filter(includeTask));
      if (!tasks.length) {{
        treeCanvas.innerHTML = '<div class="empty">No tree nodes available.</div>';
        return;
      }}

      const sorted = [...tasks].sort((a, b) => a.start_ms - b.start_ms);
      const filterTasks = groupMode === "tool" ? [] : sorted.filter((t) => phaseOf(t) === "plan" && String(t.event_type || "").includes("stage1_filter"));
      const planTasks = groupMode === "tool" ? [] : sorted.filter((t) => phaseOf(t) === "plan" && !String(t.event_type || "").includes("stage1_filter"));

      const caseMap = new Map();
      for (const t of sorted) {{
        const key = getGroupKey(t);
        if (key === "global") continue;
        if (!caseMap.has(key)) caseMap.set(key, []);
        caseMap.get(key).push(t);
      }}

      const caseKeys = [...caseMap.keys()];
      const nodes = [];
      const links = [];
      const nonLlmW = 80;
      const llmBaseW = 80;
      const llmMaxW = 480;
      const nodeH = 32;
      const nodeGapX = 20;
      const rowGap = 12;
      const topY = 48;
      const startX = 40;

      /* maxDur only from LLM nodes (dur > 0) */
      let maxDur = 0;
      for (const t of sorted) {{
        const d = Number(t.duration_seconds || 0);
        if (d > 0) maxDur = Math.max(maxDur, d);
      }}

      /* maxTokens for color depth scaling */
      let maxTokens = 0;
      for (const t of sorted) {{
        const u = t.token_usage || {{}};
        const tk = u.total_tokens || 0;
        if (tk > 0) maxTokens = Math.max(maxTokens, tk);
      }}

      /* LLM node width: sqrt-scale for clear visual diff across all ranges */
      function nodeWidth(task) {{
        const dur = Number(task.duration_seconds || 0);
        if (!isLlmTask(task)) {{
          if (groupMode === "tool" && dur > 0) {{
            const scale = (llmMaxW - llmBaseW) / Math.sqrt(600);
            return Math.min(Math.round(llmBaseW + Math.sqrt(dur) * scale), llmMaxW);
          }}
          return nonLlmW;
        }}
        if (dur <= 0) return llmBaseW;
        /* sqrt maps: 5s→117, 30s→170, 60s→207, 86s→231, 120s→259, 180s→300, 300s→363, 600s→480 */
        const scale = (llmMaxW - llmBaseW) / Math.sqrt(600);
        return Math.min(Math.round(llmBaseW + Math.sqrt(dur) * scale), llmMaxW);
      }}

      function nodeCenter(n) {{
        return {{ x: n.x + n.w, y: n.y + nodeH / 2 }};
      }}

      /* ── unified Gantt time range from ALL tasks (filter + plan + case) ── */
      const allUnifiedTasks = [...filterTasks, ...planTasks];
      caseKeys.forEach((ck) => {{ caseMap.get(ck).forEach((t) => allUnifiedTasks.push(t)); }});
      let ganttMinMs = Infinity, ganttMaxMs = -Infinity;
      for (const t of allUnifiedTasks) {{
        ganttMinMs = Math.min(ganttMinMs, t.start_ms);
        ganttMaxMs = Math.max(ganttMaxMs, t.end_ms);
      }}
      const ganttSpanMs = ganttMaxMs - ganttMinMs;
      const useGantt = ganttSpanMs >= 1000 && allUnifiedTasks.length > 0;
      const hasFilter = filterTasks.length > 0;

      /* dynamically size the row-label gutter so long tool/group names
         (e.g. "mcp__browser_navigate_page") never overlap the first node */
      function measureLabelWidth(text) {{
        const tmp = document.createElement("div");
        tmp.style.cssText = "position:absolute;visibility:hidden;font-size:11px;white-space:nowrap;font-family:ui-sans-serif,-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;";
        tmp.textContent = text;
        document.body.appendChild(tmp);
        const w = tmp.offsetWidth;
        document.body.removeChild(tmp);
        return w;
      }}
      const labelTexts = [];
      if (groupMode !== "tool" && hasFilter) labelTexts.push("Filter");
      if (groupMode !== "tool") labelTexts.push("Plan");
      caseKeys.forEach((ck, ci) => labelTexts.push(groupLabel(ck, sorted, ci)));
      const measuredMaxLabelW = labelTexts.reduce((m, t) => Math.max(m, measureLabelWidth(String(t))), 0);
      const labelW = Math.max(measuredMaxLabelW + 16, 56);
      let ganttAreaX = startX + labelW;
      let ganttPxPerMs = 0;
      let ganttTickInterval = 0;
      const filterRowY = topY;
      const planRowY = hasFilter ? topY + nodeH + rowGap : topY;
      const casesTopY = groupMode === "tool" ? topY : planRowY + nodeH + rowGap;
      let ganttTimelineTopY = filterRowY - 32;

      /* ── gap-compressed time mapper ── */
      let timeMapper = null;
      function buildTimeMapper(tasks) {{
        const pts = new Set();
        for (const t of tasks) {{ pts.add(t.start_ms); pts.add(t.end_ms); }}
        const sp = [...pts].sort((a, b) => a - b);
        if (sp.length < 2) return null;
        /* threshold: gaps > this get compressed */
        const durs = tasks.filter(t => t.duration_seconds > 0).map(t => t.duration_seconds * 1000);
        durs.sort((a, b) => a - b);
        const medDur = durs.length > 0 ? durs[Math.floor(durs.length / 2)] : 5000;
        const gapThr = Math.max(5000, medDur * 1.5);
        const segments = [];
        let mapped = 0;
        for (let i = 0; i < sp.length - 1; i++) {{
          const realGap = sp[i + 1] - sp[i];
          const mGap = realGap > gapThr ? gapThr : realGap;
          segments.push({{ rs: sp[i], re: sp[i + 1], ms: mapped, me: mapped + mGap }});
          mapped += mGap;
        }}
        const totalMs = mapped;
        function toMapped(ms) {{
          if (ms <= sp[0]) return 0;
          if (ms >= sp[sp.length - 1]) return totalMs;
          for (const s of segments) {{
            if (ms >= s.rs && ms <= s.re) {{
              const r = s.re === s.rs ? 0 : (ms - s.rs) / (s.re - s.rs);
              return s.ms + r * (s.me - s.ms);
            }}
          }}
          return totalMs;
        }}
        function toReal(m) {{
          if (m <= 0) return sp[0];
          if (m >= totalMs) return sp[sp.length - 1];
          for (const s of segments) {{
            if (m >= s.ms && m <= s.me) {{
              const r = s.me === s.ms ? 0 : (m - s.ms) / (s.me - s.ms);
              return s.rs + r * (s.re - s.rs);
            }}
          }}
          return sp[sp.length - 1];
        }}
        return {{ toMapped, toReal, totalMs, minMs: sp[0], maxMs: sp[sp.length - 1] }};
      }}

      if (useGantt) {{
        timeMapper = buildTimeMapper(allUnifiedTasks);
        const mappedSpanMs = timeMapper ? timeMapper.totalMs : ganttSpanMs;
        const mappedSpanSec = mappedSpanMs / 1000;
        let minLlmDur = Infinity;
        for (const t of allUnifiedTasks) {{
          const d = Number(t.duration_seconds || 0);
          if (d > 0) minLlmDur = Math.min(minLlmDur, d);
        }}
        const minStepDur = Math.max(minLlmDur === Infinity ? 5 : minLlmDur, 3);
        let pxPerSecond = Math.max(50 / minStepDur, 1200 / mappedSpanSec);
        pxPerSecond = Math.min(pxPerSecond, 6000 / mappedSpanSec);
        ganttPxPerMs = pxPerSecond / 1000;
        if (mappedSpanSec < 30) ganttTickInterval = 5;
        else if (mappedSpanSec < 120) ganttTickInterval = 10;
        else if (mappedSpanSec < 300) ganttTickInterval = 30;
        else if (mappedSpanSec < 600) ganttTickInterval = 60;
        else ganttTickInterval = 120;
        const minBarW = 40;
        const metadataW = 60;

        /* helper: real ms → pixel X (via gap-compressed mapper) */
        function msToX(ms) {{
          return ganttAreaX + (timeMapper ? timeMapper.toMapped(ms) : (ms - ganttMinMs)) * ganttPxPerMs;
        }}
        /* helper: compute Gantt node position {{x, w}} from task */
        function ganttNodePos(t) {{
          const x = msToX(t.start_ms);
          const dur = Number(t.duration_seconds || 0);
          if (!isLlmTask(t)) {{
            if (groupMode === "tool" && dur > 0) {{
              const realW = msToX(t.end_ms) - x;
              /* sub-second tools would otherwise clamp to minBarW=40 ("m…");
                 sqrt-stretch keeps long tools real-proportional via max() */
              const stretchedW = 70 + Math.sqrt(dur) * 25;
              return {{ x, w: Math.max(realW, stretchedW) }};
            }}
            return {{ x, w: metadataW }};
          }}
          const w = dur > 0
            ? Math.max(msToX(t.end_ms) - x, minBarW)
            : metadataW;
          return {{ x, w }};
        }}

        /* ── filter row: positioned by time on unified Gantt ── */
        filterTasks.forEach((t, i) => {{
          const {{x: nodeX, w: nodeW}} = ganttNodePos(t);
          nodes.push({{ id: `f_${{i}}`, task: t, phase: "plan", x: nodeX, y: filterRowY, w: nodeW }});
        }});

        /* ── plan row: positioned by time on unified Gantt ── */
        planTasks.forEach((t, i) => {{
          const {{x: nodeX, w: nodeW}} = ganttNodePos(t);
          nodes.push({{ id: `p_${{i}}`, task: t, phase: "plan", x: nodeX, y: planRowY, w: nodeW }});
        }});

        /* clamp filter/plan node widths to prevent visual overlap */
        const fpNodes = nodes.filter(n => n.id.startsWith("f_") || n.id.startsWith("p_"));
        fpNodes.sort((a, b) => a.x - b.x);
        for (let i = 0; i < fpNodes.length - 1; i++) {{
          const maxW = fpNodes[i + 1].x - fpNodes[i].x - 4;
          if (fpNodes[i].w > maxW && maxW > 0) {{
            fpNodes[i].w = Math.max(maxW, 16);
          }}
        }}

        /* ── case rows: vertically parallel, Gantt-positioned ── */
        caseKeys.forEach((ck, ci) => {{
          const rowY = casesTopY + ci * (nodeH + rowGap);
          const cTasks = caseMap.get(ck).sort((a, b) => {{
            /* case_execution_start always first */
            if (a.event_type === "case_execution_start") return -1;
            if (b.event_type === "case_execution_start") return 1;
            /* reflection_request always before reflection_response */
            if (a.event_type === "reflection_request" && b.event_type === "reflection_response") return -1;
            if (a.event_type === "reflection_response" && b.event_type === "reflection_request") return 1;
            /* use end_ms for ordering: events that finish later appear later */
            return a.end_ms - b.end_ms;
          }});
          /* clamp case_execution_start to be at/before first step */
          if (cTasks.length > 1 && cTasks[0].event_type === "case_execution_start") {{
            const firstStepStartMs = cTasks[1].start_ms;
            if (cTasks[0].start_ms > firstStepStartMs) {{
              cTasks[0] = {{ ...cTasks[0], start_ms: firstStepStartMs }};
            }}
          }}
          /* estimate duration for step_input_sent fallback (no step_response) */
          for (let si = 0; si < cTasks.length; si++) {{
            const ct = cTasks[si];
            if (ct.event_type === "step_input_sent" && Number(ct.duration_seconds || 0) <= 0) {{
              let nextMs = si + 1 < cTasks.length ? cTasks[si + 1].start_ms : 0;
              if (nextMs <= ct.start_ms) {{
                /* no next task — estimate from average step duration in this case */
                let sumD = 0, cntD = 0;
                for (const o of cTasks) {{
                  const od = Number(o.duration_seconds || 0);
                  if (od > 0) {{ sumD += od; cntD++; }}
                }}
                const avgD = cntD > 0 ? sumD / cntD : 10;
                nextMs = ct.start_ms + avgD * 1000;
              }}
              if (nextMs > ct.start_ms) {{
                const estDur = (nextMs - ct.start_ms) / 1000;
                cTasks[si] = {{ ...ct, end_ms: nextMs, duration_seconds: estDur }};
              }}
            }}
          }}
          let lastRightEdge = ganttAreaX;
          cTasks.forEach((t, idx) => {{
            let {{x: nodeX, w: nodeW}} = ganttNodePos(t);
            if (nodeX < lastRightEdge + 8 && idx > 0) {{
              nodeX = lastRightEdge + 8;
            }}
            const caseIndex = (t.event_type === "case_execution_start") ? ci + 1 : undefined;
            const phase = phaseOf(t);
            const n = {{ id: `n_${{ci}}_${{idx}}`, task: t, phase, x: nodeX, y: rowY, w: nodeW, caseIndex }};
            nodes.push(n);
            lastRightEdge = nodeX + nodeW;
          }});
        }});
      }} else {{
        /* ── fallback: original sequential layout ── */
        let curX = startX;
        filterTasks.forEach((t, i) => {{
          const w = nodeWidth(t);
          nodes.push({{ id: `f_${{i}}`, task: t, phase: "plan", x: curX, y: filterRowY, w }});
          curX += w + nodeGapX;
        }});
        curX = startX;
        planTasks.forEach((t, i) => {{
          const w = nodeWidth(t);
          nodes.push({{ id: `p_${{i}}`, task: t, phase: "plan", x: curX, y: planRowY, w }});
          curX += w + nodeGapX;
        }});
        const caseColX = curX;
        caseKeys.forEach((ck, ci) => {{
          const rowY = casesTopY + ci * (nodeH + rowGap);
          const cTasks = caseMap.get(ck).sort((a, b) => a.start_ms - b.start_ms);
          const caseStart = cTasks.find((t) => phaseOf(t) === "case") || cTasks[0];
          const cw = nonLlmW;
          const caseNode = {{ id: `c_${{ci}}`, task: caseStart, phase: "case", x: caseColX, y: rowY, w: cw, caseIndex: ci + 1 }};
          nodes.push(caseNode);
          const restTasks = cTasks.filter((t) => t !== caseStart);
          let nextX = caseColX + cw + nodeGapX;
          restTasks.forEach((t, idx) => {{
            const phase = phaseOf(t);
            const w = nodeWidth(t);
            const n = {{ id: `n_${{ci}}_${{idx}}`, task: t, phase, x: nextX, y: rowY, w }};
            nodes.push(n);
            nextX += w + nodeGapX;
          }});
        }});
      }}

      /* ensure all nodes have positive y by shifting if needed */
      let minY = Math.min(...nodes.map((n) => n.y));
      if (useGantt) minY = Math.min(minY, ganttTimelineTopY);
      if (minY < 20) {{
        const shift = 20 - minY;
        nodes.forEach((n) => {{ n.y += shift; }});
        if (useGantt) ganttTimelineTopY += shift;
      }}

      const byId = new Map(nodes.map((n) => [n.id, n]));
      const contentWidth = Math.max(...nodes.map((n) => n.x + n.w + 30), 980);
      const contentHeight = Math.max(...nodes.map((n) => n.y + nodeH + 24), 380);

      treeCanvas.innerHTML = "";
      treeCanvas.style.width = `${{contentWidth}}px`;
      treeCanvas.style.height = `${{contentHeight}}px`;
      /* ── Gantt timeline: grid lines, axis ticks, case labels ── */
      if (useGantt && ganttTickInterval > 0) {{
        const gridSvg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
        gridSvg.setAttribute("class", "links");
        gridSvg.setAttribute("viewBox", `0 0 ${{contentWidth}} ${{contentHeight}}`);
        gridSvg.setAttribute("preserveAspectRatio", "none");
        gridSvg.style.zIndex = "0";
        const axisY = ganttTimelineTopY + 18;
        const gridBottomY = Math.max(...nodes.map((n) => n.y + nodeH)) + 12;
        const mappedSpanPx = (timeMapper ? timeMapper.totalMs : ganttSpanMs) * ganttPxPerMs;
        const ganttRightX = ganttAreaX + mappedSpanPx;
        const nodesRightX = Math.max(...nodes.map((n) => n.x + n.w)) + 20;
        const axisRightX = Math.max(ganttRightX, nodesRightX);
        /* axis line */
        const axLine = document.createElementNS("http://www.w3.org/2000/svg", "line");
        axLine.setAttribute("x1", ganttAreaX);
        axLine.setAttribute("x2", axisRightX);
        axLine.setAttribute("y1", axisY);
        axLine.setAttribute("y2", axisY);
        axLine.setAttribute("stroke", "#e2e8f0");
        axLine.setAttribute("stroke-width", "1");
        gridSvg.appendChild(axLine);
        /* ticks + grid lines — use mapped time for position, real time for labels */
        const mappedTotalSec = (axisRightX - ganttAreaX) / (ganttPxPerMs * 1000);
        for (let sec = 0; sec <= mappedTotalSec; sec += ganttTickInterval) {{
          const x = ganttAreaX + sec * ganttPxPerMs * 1000;
          /* tick mark */
          const tick = document.createElementNS("http://www.w3.org/2000/svg", "line");
          tick.setAttribute("x1", x); tick.setAttribute("x2", x);
          tick.setAttribute("y1", axisY - 4); tick.setAttribute("y2", axisY + 4);
          tick.setAttribute("stroke", "#e2e8f0"); tick.setAttribute("stroke-width", "1");
          gridSvg.appendChild(tick);
          /* vertical grid line */
          const grid = document.createElementNS("http://www.w3.org/2000/svg", "line");
          grid.setAttribute("x1", x); grid.setAttribute("x2", x);
          grid.setAttribute("y1", axisY + 4); grid.setAttribute("y2", gridBottomY);
          grid.setAttribute("stroke", "#e2e8f0"); grid.setAttribute("stroke-width", "1");
          grid.setAttribute("stroke-dasharray", "4,4");
          gridSvg.appendChild(grid);
          /* tick label — convert mapped position back to real time */
          const label = document.createElementNS("http://www.w3.org/2000/svg", "text");
          label.setAttribute("x", x); label.setAttribute("y", axisY - 8);
          label.setAttribute("text-anchor", "middle");
          label.setAttribute("font-size", "10"); label.setAttribute("fill", "#94a3b8");
          label.setAttribute("font-family", "ui-sans-serif, -apple-system, sans-serif");
          const realMs = timeMapper ? timeMapper.toReal(sec * 1000) : (ganttMinMs + sec * 1000);
          label.textContent = fmtTime(new Date(realMs));
          gridSvg.appendChild(label);
        }}
        treeCanvas.appendChild(gridSvg);
        /* row labels: Filter + Plan + Case N, or tool lanes in cc-mini mode */
        const rowLabelX = startX;
        function addRowLabel(text, y) {{
          const lbl = document.createElement("div");
          lbl.style.cssText = `position:absolute;left:${{rowLabelX}}px;top:${{y + 8}}px;font-size:11px;color:#64748b;user-select:none;pointer-events:none;z-index:0;white-space:nowrap;`;
          lbl.textContent = text;
          treeCanvas.appendChild(lbl);
        }}
        if (groupMode !== "tool") {{
          if (hasFilter) addRowLabel("Filter", filterRowY);
          addRowLabel("Plan", planRowY);
        }}
        caseKeys.forEach((ck, ci) => {{
          const firstNode = nodes.find((n) => n.id === `n_${{ci}}_0`);
          if (firstNode) addRowLabel(groupLabel(ck, sorted, ci), firstNode.y);
        }});
      }}

      treeCanvas.appendChild(connectSvg(contentWidth, contentHeight, links.map((l) => {{
        const a = nodeCenter(byId.get(l.from));
        const b = nodeCenter(byId.get(l.to));
        return {{ x1: a.x, y1: a.y, x2: b.x, y2: b.y }};
      }})));

      /* ── vertical time indicator on hover ── */
      const timeIndicator = document.createElement("div");
      timeIndicator.style.cssText = "position:absolute;width:1px;background:#e2e8f0;pointer-events:none;z-index:5;display:none;";
      treeCanvas.appendChild(timeIndicator);
      const timeIndicatorLabel = document.createElement("div");
      timeIndicatorLabel.style.cssText = "position:absolute;pointer-events:none;z-index:6;display:none;font-size:10px;color:#94a3b8;font-weight:600;white-space:nowrap;font-family:ui-monospace,monospace;background:rgba(255,255,255,0.85);padding:1px 4px;border-radius:3px;";
      treeCanvas.appendChild(timeIndicatorLabel);
      const gridTopY = Math.min(...nodes.map((nd) => nd.y));
      const gridBotY = Math.max(...nodes.map((nd) => nd.y + nodeH)) + 12;

      function showTimeIndicatorAtX(canvasX) {{
        if (!useGantt || ganttPxPerMs <= 0) return;
        const clampedX = Math.max(ganttAreaX, canvasX);
        const mappedMs = (clampedX - ganttAreaX) / ganttPxPerMs;
        const ms = timeMapper ? timeMapper.toReal(mappedMs) : (ganttMinMs + mappedMs);
        timeIndicator.style.left = `${{clampedX}}px`;
        timeIndicator.style.top = `${{gridTopY}}px`;
        timeIndicator.style.height = `${{gridBotY - gridTopY}}px`;
        timeIndicator.style.display = "block";
        timeIndicatorLabel.textContent = fmtTime(new Date(ms));
        timeIndicatorLabel.style.left = `${{clampedX + 4}}px`;
        timeIndicatorLabel.style.top = `${{gridTopY - 16}}px`;
        timeIndicatorLabel.style.display = "block";
      }}
      function hideTimeIndicator() {{
        timeIndicator.style.display = "none";
        timeIndicatorLabel.style.display = "none";
      }}
      /* show indicator anywhere on the canvas */
      treeCanvas.addEventListener("mousemove", (e) => {{
        if (dragging) return;
        const rect = treeCanvas.getBoundingClientRect();
        const canvasX = e.clientX - rect.left;
        if (canvasX >= ganttAreaX) {{
          showTimeIndicatorAtX(canvasX);
        }} else {{
          hideTimeIndicator();
        }}
      }});
      treeCanvas.addEventListener("mouseleave", () => {{ hideTimeIndicator(); }});

      let selected = null;
      nodes.forEach((n) => {{
        const el = document.createElement("div");
        el.className = "node";
        el.style.left = `${{n.x}}px`;
        el.style.top = `${{n.y}}px`;
        el.style.width = `${{n.w}}px`;
        el.style.background = phaseBg(n.phase, n.task, maxTokens);
        el.textContent = shortLabel(n.task, n.caseIndex != null ? n.caseIndex : null);

        /* custom tooltip with 500ms delay */
        const u = n.task.token_usage || {{}};
        const dur = Number(n.task.duration_seconds || 0);
        const durStr = dur >= 1 ? dur.toFixed(2) + "s" : dur > 0 ? (dur * 1000).toFixed(0) + "ms" : "-";
        const hasMeasurement = dur > 0 || (u.total_tokens || 0) > 0;
        const tip = `${{n.task.title}}\\nphase: ${{n.phase}}\\n` +
          (hasMeasurement
            ? `duration: ${{durStr}}\\nprompt_tokens: ${{u.prompt_tokens || 0}}\\ncompletion_tokens: ${{u.completion_tokens || 0}}\\ntotal_tokens: ${{u.total_tokens || 0}}`
            : `(metadata node, no LLM measurement)`);

        el.addEventListener("mouseenter", (e) => {{
          tipTimer = setTimeout(() => showTooltip(tip, e.clientX, e.clientY), 500);
        }});
        el.addEventListener("mousemove", (e) => {{
          if (tooltipEl.style.display === "block") {{
            tooltipEl.style.left = `${{Math.min(e.clientX + 14, window.innerWidth - 400)}}px`;
            tooltipEl.style.top = `${{Math.min(e.clientY + 14, window.innerHeight - 140)}}px`;
          }}
        }});
        el.addEventListener("mouseleave", hideTooltip);

        el.addEventListener("click", () => {{
          if (selected) selected.classList.remove("selected");
          el.classList.add("selected");
          selected = el;
          detailEl.textContent = JSON.stringify(n.task.event, null, 2);
          /* auto-expand right panel if collapsed */
          if (panelHidden) showJsonPanel();
        }});
        treeCanvas.appendChild(el);
      }});

      treeViewport.style.width = `${{contentWidth}}px`;
      treeViewport.style.height = `${{contentHeight}}px`;
      treeWrap.scrollLeft = 0;
      /* vertically center the tree in viewport */
      const wrapH = treeWrap.clientHeight;
      if (contentHeight < wrapH) {{
        treeViewport.style.marginTop = `${{Math.floor((wrapH - contentHeight) / 2)}}px`;
      }} else {{
        treeViewport.style.marginTop = "0";
        treeWrap.scrollTop = Math.max(0, Math.floor((contentHeight - wrapH) / 2));
      }}
    }}

    renderTree();
    window.addEventListener("resize", renderTree);

    /* --- drag to scroll tree --- */
    let dragging = false;
    let dragStartX = 0;
    let dragStartY = 0;
    let startLeft = 0;
    let startTop = 0;
    treeWrap.addEventListener("mousedown", (e) => {{
      if (e.button !== 0) return;
      dragging = true;
      dragStartX = e.clientX;
      dragStartY = e.clientY;
      startLeft = treeWrap.scrollLeft;
      startTop = treeWrap.scrollTop;
      treeWrap.classList.add("dragging");
    }});
    window.addEventListener("mousemove", (e) => {{
      if (!dragging) return;
      treeWrap.scrollLeft = startLeft - (e.clientX - dragStartX);
      treeWrap.scrollTop = startTop - (e.clientY - dragStartY);
    }});
    window.addEventListener("mouseup", () => {{
      dragging = false;
      treeWrap.classList.remove("dragging");
    }});
  </script>
</body>
</html>
"""


def generate_data_flow_report(
    report_dir: str | None = None,
    *,
    group_mode: str = 'case',
) -> str | None:
    """Generate interactive HTML report from collected JSONL events.

    Reads ``data_flow_events.jsonl`` and produces
    ``data_flow_report.html`` in the same directory.
    """
    # Ensure all queued events are flushed to disk before reading
    flush_data_flow_events()

    target_dir = _resolve_report_dir(report_dir)
    if target_dir is None:
        return None

    event_path = target_dir / 'data_flow_events.jsonl'
    if not event_path.exists():
        return None

    try:
        events: list[dict[str, Any]] = []
        with event_path.open('r', encoding='utf-8') as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                events.append(json.loads(line))

        if not events:
            return None

        normalized_group_mode = 'tool' if group_mode == 'tool' else 'case'
        interactive_tasks = _build_interactive_gantt_tasks(
            events,
            group_mode=normalized_group_mode,
        )
        interactive_html = _render_interactive_gantt_html(
            interactive_tasks,
            group_mode=normalized_group_mode,
        )
        interactive_path = target_dir / 'data_flow_report.html'
        interactive_path.write_text(interactive_html, encoding='utf-8')
        return str(interactive_path)
    except Exception:
        return None

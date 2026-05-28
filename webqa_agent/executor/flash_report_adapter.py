"""Adapter: Flash RunResult → gen-mode report payload.

Keeps the underlying Flash engine library free of any dependency on
``webqa_agent``. This mapping layer lives here so the CLI can render
Flash runs using the existing gen-mode React frontend (the same
``static/index.html`` template inlined by :class:`ResultAggregator`).

Two mapping targets:

* :func:`run_result_to_aggregated_data` returns the
  ``{"gen": {"case_1_<safe>": {...}, "index": {...}}}`` dict that the
  React frontend ACTUALLY consumes. ``ResultAggregator`` normally builds
  this by scanning per-case JSON files written during a gen-mode run;
  Flash has no such files, so we synthesize the dict in memory.
* :func:`run_result_to_session` returns a lightweight
  :class:`ParallelTestSession` carrying session-level metadata
  (``report_path``, config). Its ``to_dict`` shape is NOT what the
  frontend reads — passing it alone yields an empty report. Always
  combine it with ``run_result_to_aggregated_data`` when rendering.

Mapping:
    * One Flash run → one "case" entry (``case_1_<safe_name>``)
    * Each Flash ``Step`` → one step dict with ``modelIO`` holding the
      tool input + result as JSON. Screenshots are left empty for now —
      Flash stores them inside MCP tool output, not as separate paths.
      (Extracting them is a future enhancement; the UI tolerates ``[]``.)
"""
from __future__ import annotations

import json
import uuid
from datetime import datetime
from typing import Any

from webqa_agent.data.gen_structures import (ParallelTestSession,
                                             SubTestReport, SubTestResult,
                                             SubTestStep, TestCategory,
                                             TestResult, TestStatus)
# Shared with mini (report + progress must agree on pass/fail).
from webqa_agent.executor.flash.core.outcome_status import (
    derive_status, extract_final_outcome, strip_final_outcome_block)
from webqa_agent.utils.reporting_utils import sanitize_case_name

# Soft cap on how much of each tool result we embed in the report.
# Flash tool outputs are sometimes multi-KB (accessibility snapshots,
# full DOM dumps) and inlining them verbatim would bloat every report.
_RESULT_TEXT_LIMIT = 4000

# Hard cap on the storage-safe portion of a case name. The full task text
# stays in ``display_name`` for the UI to render (with CSS ellipsis as
# needed); ``safe_name`` is only used for filenames and dict keys, where
# a 200-char task string makes ``ls`` and HTML payloads unreadable.
# Counted in characters, so CJK and ASCII share the budget fairly.
_MAX_SAFE_NAME_CHARS = 40


def _truncate_safe_name(name: str) -> str:
    """Cap a sanitized case name at :data:`_MAX_SAFE_NAME_CHARS` characters.

    Cuts on the last underscore at or after the midpoint when possible so we
    don't slice through a "word" mid-token; otherwise hard-truncates.
    Trailing underscores from sanitization are stripped for cleanliness.
    Returns a non-empty string (falls back to ``'flash_run'``).
    """
    if not name:
        return 'flash_run'
    if len(name) <= _MAX_SAFE_NAME_CHARS:
        return name
    cut = name[:_MAX_SAFE_NAME_CHARS]
    midpoint = _MAX_SAFE_NAME_CHARS // 2
    last_sep = cut.rfind('_')
    if last_sep >= midpoint:
        cut = cut[:last_sep]
    cut = cut.rstrip('_')
    return cut or 'flash_run'


def _bare_tool_name(tool: str) -> str:
    """Strip MCP namespace prefix; e.g. 'mcp__browser__click' -> 'click'."""
    return tool.split('__')[-1] if '__' in tool else tool


def _int_attr(obj: Any, name: str) -> int:
    """Read integer-like attribute with a safe zero fallback."""
    return int(getattr(obj, name, 0) or 0)


def run_result_to_session(
    run_result: Any,
    *,
    url: str,
    task: str,
    report_dir: str | None = None,
    language: str = 'zh-CN',
) -> ParallelTestSession:
    """Convert a Flash ``RunResult`` to a ``ParallelTestSession``.

    Args:
        run_result: The object returned by ``run_cc_mini``. Must expose
            ``final_text``, ``steps``, ``aborted``, ``input_tokens``,
            ``output_tokens`` attributes (duck-typed; concrete class not
            imported to keep this module independent of the Flash engine).
        url: Target URL of the run (populates ``target_url`` + step 0).
        task: Task description given to the Flash run (used as the test name).
        report_dir: Optional report directory — stored on the session so
            ``ResultAggregator`` can find it during rendering.
        language: Report language; stored in ``TestConfiguration.report_config``
            so ``ParallelTestSession.to_dict`` picks the right category titles.

    Returns:
        A fully-populated :class:`ParallelTestSession` ready to be passed
        to :meth:`ResultAggregator.generate_html_report_fully_inlined`.
    """
    raw_steps = list(getattr(run_result, 'steps', None) or [])
    sub_steps: list[SubTestStep] = [
        _map_step(i, step) for i, step in enumerate(raw_steps, start=1)
    ]

    raw_final_text = getattr(run_result, 'final_text', '') or ''
    aborted = bool(getattr(run_result, 'aborted', False))
    failed_count = sum(1 for s in sub_steps if s.status == TestStatus.FAILED)
    outcome = extract_final_outcome(raw_final_text)
    final_text = strip_final_outcome_block(raw_final_text)
    overall_status_name, status_source = derive_status(
        aborted=aborted, failed_count=failed_count, outcome=outcome,
    )
    overall_status = (
        TestStatus.PASSED if overall_status_name in ('passed', 'warning') else TestStatus.FAILED
    )
    report_sections: list[SubTestReport] = []
    if final_text.strip():
        report_sections.append(SubTestReport(title='Summary', issues=final_text))

    now = datetime.now()
    sub_test_id = f'flash-sub-{uuid.uuid4().hex[:8]}'
    sub = SubTestResult(
        sub_test_id=sub_test_id,
        name=task or 'Flash run',
        status=overall_status,
        metrics={
            'total_steps': len(sub_steps),
            'passed_steps': len(sub_steps) - failed_count,
            'failed_steps': failed_count,
            'input_tokens': _int_attr(run_result, 'input_tokens'),
            'output_tokens': _int_attr(run_result, 'output_tokens'),
            'aborted': aborted,
            'status_source': status_source,
        },
        steps=sub_steps,
        start_time=now.isoformat(timespec='seconds'),
        end_time=now.isoformat(timespec='seconds'),
        final_summary=final_text,
        user_summary=final_text,
        report=report_sections,
    )

    test_id = f'flash-{uuid.uuid4().hex[:8]}'
    test = TestResult(
        test_id=test_id,
        test_name=_truncate(f'Flash — {task}' if task else 'Flash run', 120),
        status=overall_status,
        category=TestCategory.FUNCTION,
        start_time=now,
        end_time=now,
        sub_tests=[sub],
        metrics={
            'test_case_count': 1,
            'passed_test_cases': 1 if overall_status in (TestStatus.PASSED, TestStatus.WARNING) else 0,
            'failed_test_cases': 1 if overall_status == TestStatus.FAILED else 0,
            'total_steps': len(sub_steps),
            'input_tokens': _int_attr(run_result, 'input_tokens'),
            'output_tokens': _int_attr(run_result, 'output_tokens'),
            'status_source': status_source,
        },
    )
    if overall_status == TestStatus.FAILED:
        test.error_message = (
            'Flash run aborted' if aborted
            else (
                'final outcome marked objective_achieved=false'
                if status_source == 'final_outcome'
                else f'{failed_count} step(s) failed'
            )
        )

    from webqa_agent.data.gen_structures import TestConfiguration
    test_cfg = TestConfiguration(
        test_id=test_id,
        test_name=test.test_name,
        enabled=True,
        report_config={'language': language, 'report_dir': report_dir or ''},
    )

    session = ParallelTestSession(
        session_id=f'flash-{uuid.uuid4().hex[:8]}',
        target_url=url,
        test_configurations=[test_cfg],
        test_results={test_id: test},
        start_time=now,
        end_time=now,
        report_path=report_dir or '',
    )
    return session


def _map_step(index: int, step: Any) -> SubTestStep:
    description = getattr(step, 'description', '') or ''
    is_error = bool(getattr(step, 'is_error', False))
    screenshots = list(getattr(step, 'screenshots', []) or [])
    tool_calls = getattr(step, 'tool_calls', None)
    if tool_calls:
        try:
            model_io = json.dumps(
                [{'tool': tc.tool, 'input': tc.input,
                  'result': _truncate(tc.result or '', _RESULT_TEXT_LIMIT)}
                 for tc in tool_calls],
                ensure_ascii=False, indent=2,
            )
        except Exception:
            model_io = ''
        error_text = '\n'.join(tc.result for tc in tool_calls if tc.is_error)
    else:
        tool, is_error, input_dict, result_text, screenshots = _extract_step_fields(step)
        model_io = _build_model_io(tool=tool, input_dict=input_dict, result_text=result_text)
        error_text = result_text if is_error else ''
        description = description or _describe_step(tool, input_dict)

    return SubTestStep(
        id=index,
        description=description,
        screenshots=screenshots,
        modelIO=model_io,
        actions=[],
        status=TestStatus.FAILED if is_error else TestStatus.PASSED,
        errors=error_text,
    )


def _describe_step(tool: str, input_dict: dict) -> str:
    """Build a one-line human summary of a tool invocation."""
    # Well-known browser actions get a friendlier description so readers
    # don't have to expand the payload to see intent. Unknown tools fall
    # back to their raw name.
    if tool in ('navigate_page', 'navigate', 'goto') and 'url' in input_dict:
        return f"Navigate to {input_dict['url']}"
    if tool in ('click', 'click_element'):
        target = input_dict.get('selector') or input_dict.get('uid') or input_dict.get('text')
        if target:
            return f'Click {target}'
    if tool in ('fill', 'type', 'input'):
        target = input_dict.get('selector') or input_dict.get('uid') or input_dict.get('label')
        if target:
            return f'Fill {target}'
    if tool.startswith(('take_screenshot', 'screenshot')):
        return 'Take screenshot'
    if tool.startswith(('snapshot', 'accessibility')):
        return 'Take accessibility snapshot'
    return tool


def _truncate(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text
    return text[: max(0, limit - 3)] + '...'


def _truncate_with_flag(text: str, limit: int) -> tuple[str, bool]:
    if len(text) <= limit:
        return text, False
    return text[: max(0, limit - 3)] + '...', True


def run_result_to_aggregated_data(
    run_result: Any,
    *,
    url: str,
    task: str,
    language: str = 'zh-CN',
    model: str | None = None,
    filter_model: str | None = None,
) -> dict:
    """Build the gen-mode aggregated dict the React frontend consumes.

    The React shell keyed off ``window.testResultData`` expects a shape
    that :meth:`ResultAggregator.aggregate_report_json` normally produces
    by scanning per-case JSON files. Flash has no such files, so this
    function synthesizes the equivalent structure in memory::

        {
            "gen": {
                "case_1_<safe_name>": {
                    "name", "case_id", "start_time", "end_time",
                    "duration", "steps": [...], "status", "sub_test_id",
                    ...
                },
                "index": {
                    "session_info": {...},
                    "aggregated_results": {
                        "count": {...},
                        "test_items": [...],
                        "gen_result": [{...}],
                    },
                },
            },
        }

    Pass this as the ``aggregated_data`` kwarg to
    :meth:`ResultAggregator.generate_html_report_fully_inlined`; the
    ``ParallelTestSession`` falls back role of carrying session metadata
    (``report_path``) while this dict drives the UI.
    """
    return run_results_to_aggregated_data(
        [run_result], url=url, tasks=[task], language=language,
        model=model, filter_model=filter_model,
    )


def run_results_to_aggregated_data(
    run_results: list[Any],
    *,
    url: str,
    tasks: list[str],
    language: str = 'zh-CN',
    model: str | None = None,
    filter_model: str | None = None,
) -> dict:
    """Multi-case version of :func:`run_result_to_aggregated_data`.

    Each ``RunResult`` becomes one ``case_<n>_<safe>`` entry; the index
    block aggregates pass/fail/warning counts and lists every case under
    ``gen_result``. ``run_results`` and ``tasks`` are zipped positionally
    — they must have the same length.

    Used by :class:`webqa_agent.executor.flash_executor.FlashExecutor`
    to render one HTML report containing every concurrent task.
    """
    if len(run_results) != len(tasks):
        raise ValueError(
            f'run_results ({len(run_results)}) and tasks ({len(tasks)}) '
            'must have the same length.'
        )
    if not run_results:
        raise ValueError('run_results must not be empty.')

    now = datetime.now()
    now_iso = now.isoformat(timespec='seconds')

    gen_block: dict[str, Any] = {}
    gen_results: list[dict[str, Any]] = []
    summaries: list[str] = []
    total_steps_all = 0
    count = {'total': 0, 'passed': 0, 'failed': 0, 'warning': 0}

    # Collect step timestamps across all run_results to compute session timing.
    all_start_ts: list[float] = []
    all_end_ts: list[float] = []

    for idx, (run_result, task) in enumerate(zip(run_results, tasks), start=1):
        payload = build_case_payload(
            run_result=run_result,
            task=task,
            case_index=idx,
            now_iso=now_iso,
        )
        gen_block[payload['case_key']] = payload['case_entry']
        # The React frontend's ``loadMonitorData`` looks for a sibling key
        # named ``<fileName>_monitor`` inside the same mode block (see
        # webqa_agent/static/assets/index.js). Same shape as the per-case
        # ``case_<n>_<safe>_monitor.json`` written into ``<report_dir>/tmp/``.
        if payload['monitor_entry'] is not None:
            gen_block[f'{payload["case_key"]}_monitor'] = payload['monitor_entry']
        gen_results.append(payload['gen_result_entry'])
        if payload['summary_text']:
            summaries.append(f'[case-{idx}] {payload["summary_text"]}')
        total_steps_all += int(
            payload['case_entry']['metrics'].get('total_steps', 0) or 0,
        )
        status = payload['case_entry']['status']
        count['total'] += 1
        if status in count:
            count[status] += 1
        else:  # status not in canonical bucket falls back to 'failed'
            count['failed'] += 1

        first_ts, last_ts = payload['session_timestamps']
        if first_ts:
            all_start_ts.append(first_ts)
        if last_ts:
            all_end_ts.append(last_ts)

    index_entry = build_index_entry(
        url=url,
        language=language,
        model=model,
        filter_model=filter_model,
        now_iso=now_iso,
        count=count,
        total_steps=total_steps_all,
        summaries=summaries,
        gen_results=gen_results,
        session_start_ts=min(all_start_ts) if all_start_ts else None,
        session_end_ts=max(all_end_ts) if all_end_ts else None,
    )

    gen_block['index'] = index_entry
    return {'gen': gen_block}


def build_case_payload(
    *,
    run_result: Any,
    task: str,
    case_index: int,
    now_iso: str | None = None,
) -> dict[str, Any]:
    """Build a per-case payload for one ``RunResult``.

    Returned dict keys::

        case_key:           "case_<n>_<safe_name>"
        case_entry:          the dict that goes into ``gen_block[case_key]``
        gen_result_entry:    minimal {name, status, sub_test_id, ...} entry
                             for the index block
        summary_text:        final-summary text (for index aggregation)
        monitor_entry:       the wrapped monitor payload (same shape as the
                             tmp sidecar file) or None when monitoring was
                             disabled
        session_timestamps:  (first_step_ts, last_step_ts) — floats or 0;
                             callers feed these into the session start/end
                             aggregation in :func:`build_index_entry`.

    Pure dict construction — safe to call from concurrent worker threads.
    """
    now_iso = now_iso or datetime.now().isoformat(timespec='seconds')
    case_key, case_entry, gen_entry, summary_text = _build_case_entry(
        run_result=run_result, task=task,
        case_index=case_index, now_iso=now_iso,
    )

    monitor_entry: dict[str, Any] | None = None
    monitoring_data = getattr(run_result, 'monitoring_data', None)
    if monitoring_data is not None:
        try:
            from webqa_agent.executor.flash.features.monitor import \
                wrap_monitor_payload
            wrapped = wrap_monitor_payload(
                monitoring_data,
                sub_test_id=case_entry['sub_test_id'],
                name=case_entry['display_name'],
                display_name=case_entry['display_name'],
                safe_name=case_entry['safe_name'],
            )
            monitor_entry = next(iter(wrapped.values()))
        except Exception:
            monitor_entry = None

    steps = list(getattr(run_result, 'steps', None) or [])
    first_ts: float = float(getattr(steps[0], 'timestamp', 0) or 0.0) if steps else 0.0
    last_step = steps[-1] if steps else None
    last_ts: float = float(
        (getattr(last_step, 'end_ts', 0) or getattr(last_step, 'timestamp', 0) or 0.0)
        if last_step is not None else 0.0
    )

    return {
        'case_key': case_key,
        'case_entry': case_entry,
        'gen_result_entry': gen_entry,
        'summary_text': summary_text,
        'monitor_entry': monitor_entry,
        'session_timestamps': (first_ts, last_ts),
    }


def build_index_entry(
    *,
    url: str,
    language: str,
    model: str | None,
    filter_model: str | None,
    now_iso: str,
    count: dict[str, int],
    total_steps: int,
    summaries: list[str],
    gen_results: list[dict[str, Any]],
    session_start_ts: float | None,
    session_end_ts: float | None,
) -> dict[str, Any]:
    """Build the ``index`` entry of the gen block from already-aggregated stats.

    Split out so both the in-memory path
    (:func:`run_results_to_aggregated_data`) and the disk-pipeline path
    (:func:`assemble_aggregated_data_from_tmp`) can produce identical index
    blocks without duplicating the layout.
    """
    session_start_iso = (
        datetime.fromtimestamp(session_start_ts).isoformat(timespec='seconds')
        if session_start_ts else now_iso
    )
    session_end_iso = (
        datetime.fromtimestamp(session_end_ts).isoformat(timespec='seconds')
        if session_end_ts else now_iso
    )

    test_items = [{
        'name': '功能测试' if language != 'en-US' else 'Functional',
        'item': (
            f'执行了 {total_steps} 个步骤(共 {count["total"]} 个 case)'
            if language != 'en-US'
            else f'Executed {total_steps} steps across {count["total"]} cases'
        ),
    }]
    summary_text = '\n\n'.join(summaries)

    return {
        'session_info': {
            'session_id': f'flash-{uuid.uuid4().hex[:8]}',
            'target_url': url,
            'start_time': session_start_iso,
            'end_time': session_end_iso,
        },
        'aggregated_results': {
            'title': 'Overview',
            'mode': 'gen',
            'count': count,
            'test_items': test_items,
            'summary': summary_text,
            'gen_result': gen_results,
        },
        'count': count,
        'config': {
            'target_url': url,
            'llm_config': {
                'model': model or '',
                'filter_model': filter_model or '',
            },
            'browser_config': {},
        },
    }


def _extract_case_timing(
    raw_steps: list[Any], now_iso: str,
) -> tuple[str, str, float]:
    """Derive (start_iso, end_iso, duration_seconds) from step timestamps.

    Falls back to ``now_iso`` / zero duration when steps carry no timestamps.
    """
    if not raw_steps:
        return now_iso, now_iso, 0.0

    first_ts: float = getattr(raw_steps[0], 'timestamp', 0) or 0.0
    last_step = raw_steps[-1]
    last_ts: float = (
        getattr(last_step, 'end_ts', 0)
        or getattr(last_step, 'timestamp', 0)
        or 0.0
    )

    start_iso = (
        datetime.fromtimestamp(first_ts).isoformat(timespec='seconds')
        if first_ts else now_iso
    )
    end_iso = (
        datetime.fromtimestamp(last_ts).isoformat(timespec='seconds')
        if last_ts else now_iso
    )
    duration = max(0.0, last_ts - first_ts) if (first_ts and last_ts) else 0.0
    return start_iso, end_iso, duration


def _build_case_entry(
    *,
    run_result: Any,
    task: str,
    case_index: int,
    now_iso: str,
) -> tuple[str, dict[str, Any], dict[str, Any], str]:
    """Build (case_key, case_entry, gen_result_entry, summary_text) for one
    run."""
    raw_steps = list(getattr(run_result, 'steps', None) or [])
    step_dicts: list[dict] = [
        _map_step_dict(i, step) for i, step in enumerate(raw_steps, start=1)
    ]

    raw_final_text = (getattr(run_result, 'final_text', '') or '').strip()
    outcome = extract_final_outcome(raw_final_text)
    final_text = strip_final_outcome_block(raw_final_text)
    aborted = bool(getattr(run_result, 'aborted', False))
    failed_count = sum(1 for s in step_dicts if s['status'] == 'failed')
    overall_status, status_source = derive_status(
        aborted=aborted, failed_count=failed_count, outcome=outcome,
    )

    display_name = (task or 'Flash run').strip()
    # ``display_name`` stays intact for the UI (full task text). ``safe_name``
    # is what feeds into filenames and dict keys downstream, so we cap it —
    # see :func:`_truncate_safe_name`. ``case_id`` already guarantees per-case
    # uniqueness within a batch, so the truncation is collision-safe.
    safe_name = _truncate_safe_name(
        sanitize_case_name(display_name) or 'flash_run',
    )
    case_id = f'case_{case_index}'
    case_key = f'{case_id}_{safe_name}'
    sub_test_id = case_id

    case_start_iso, case_end_iso, duration = _extract_case_timing(raw_steps, now_iso)

    case_entry: dict[str, Any] = {
        'name': safe_name,
        'display_name': display_name,
        'safe_name': safe_name,
        'case_id': case_id,
        'sub_test_id': sub_test_id,
        'start_time': case_start_iso,
        'end_time': case_end_iso,
        'duration': duration,
        'status': overall_status,
        'steps': step_dicts,
        'case_info': {
            'name': display_name,
            'objective': display_name,
            'test_category': 'function',
            'steps': [],
        },
        'final_summary': final_text,
        'user_summary': final_text,
        'metrics': {
            'total_steps': len(step_dicts),
            'passed_steps': len(step_dicts) - failed_count,
            'failed_steps': failed_count,
            'input_tokens': _int_attr(run_result, 'input_tokens'),
            'output_tokens': _int_attr(run_result, 'output_tokens'),
            'aborted': aborted,
            'status_source': status_source,
        },
    }
    if outcome is not None:
        case_entry['final_outcome'] = outcome
    if final_text:
        case_entry['report'] = [{'title': 'Summary', 'issues': final_text}]

    gen_result_entry = {
        'name': safe_name,
        'display_name': display_name,
        'safe_name': safe_name,
        'status': overall_status,
        'sub_test_id': sub_test_id,
    }
    return case_key, case_entry, gen_result_entry, final_text


def _map_step_dict(index: int, step: Any) -> dict:
    """Map a Flash ``Step`` into the step-dict shape the React UI renders."""
    description = getattr(step, 'description', '') or ''
    is_error = bool(getattr(step, 'is_error', False))
    screenshots = list(getattr(step, 'screenshots', []) or [])
    step_ts = getattr(step, 'timestamp', None)
    now_iso = (
        datetime.fromtimestamp(step_ts).isoformat(timespec='seconds')
        if step_ts
        else datetime.now().isoformat(timespec='seconds')
    )
    status = 'failed' if is_error else 'passed'

    # Build actions from all tool_calls in this step
    tool_calls = getattr(step, 'tool_calls', None)
    if tool_calls:
        actions = [
            {
                'description': _bare_tool_name(tc.tool),
                'success': not tc.is_error,
                'message': _bare_tool_name(tc.tool),
                'index': i,
            }
            for i, tc in enumerate(tool_calls, start=1)
        ]
        # modelIO: show all tool calls
        try:
            model_io = json.dumps(
                [{'tool': tc.tool, 'input': tc.input,
                  'result': _truncate(tc.result or '', _RESULT_TEXT_LIMIT)}
                 for tc in tool_calls],
                ensure_ascii=False, indent=2,
            )
        except Exception:
            model_io = ''
        error_text = '\n'.join(tc.result for tc in tool_calls if tc.is_error)
        if not description.strip():
            first_tc = tool_calls[0]
            bare_tool = _bare_tool_name(first_tc.tool)
            description = _describe_step(bare_tool, first_tc.input or {})
            if len(tool_calls) > 1:
                description += f' (+{len(tool_calls) - 1} more)'
    else:
        # fallback for old-style Step
        tool, is_error, input_dict, result_text, screenshots = _extract_step_fields(step)
        bare = _bare_tool_name(tool)
        actions = [{'description': bare, 'success': not is_error, 'message': bare, 'index': 1}]
        model_io = _build_model_io(tool=tool, input_dict=input_dict, result_text=result_text)
        error_text = result_text if is_error else ''
        description = description or _describe_step(tool, input_dict)

    return {
        'id': index,
        'number': index,
        'type': 'action',
        'description': description,
        'screenshots': screenshots,
        'modelIO': model_io,
        'actions': actions,
        'status': status,
        'timestamp': now_iso,
        'errors': error_text,
    }


def _extract_step_fields(step: Any) -> tuple[str, bool, dict[str, Any], str, list[dict[str, str]]]:
    """Extract normalized step attributes from a duck-typed Flash step."""
    tool = str(getattr(step, 'tool', '') or 'unknown')
    is_error = bool(getattr(step, 'is_error', False))
    input_dict = getattr(step, 'input', {}) or {}
    result_text = str(getattr(step, 'result', '') or '')
    raw_screenshots = getattr(step, 'screenshots', []) or []
    screenshots = raw_screenshots if isinstance(raw_screenshots, list) else []
    return tool, is_error, input_dict, result_text, screenshots


def _build_model_io(*, tool: str, input_dict: dict[str, Any], result_text: str) -> str:
    """Build compact modelIO JSON payload used by both output shapes."""
    try:
        truncated_result, truncated = _truncate_with_flag(
            result_text, _RESULT_TEXT_LIMIT,
        )
        model_io_obj: dict[str, Any] = {
            'tool': tool,
            'input': input_dict,
            'result': truncated_result,
        }
        if truncated:
            model_io_obj['result_truncated'] = True
            model_io_obj['full_result_length'] = len(result_text)
        return json.dumps(
            model_io_obj, ensure_ascii=False, indent=2, default=str,
        )
    except (TypeError, ValueError):
        return repr({'tool': tool, 'input': input_dict, 'result': result_text})


# ---------------------------------------------------------------------------
# Disk pipeline: per-case dump + tmp-assemble + test_results.json
# ---------------------------------------------------------------------------

TMP_SUBDIR = 'tmp'


def dump_case_artifacts_to_tmp(
    payload: dict[str, Any],
    *,
    report_dir: str,
) -> dict[str, str]:
    """Persist a case payload as two JSON files under ``<report_dir>/tmp/``.

    Writes:
      * ``<tmp>/<case_key>_data.json``    — case_entry (unwrapped)
      * ``<tmp>/<case_key>_monitor.json`` — monitor_entry (unwrapped); skipped
        when ``payload['monitor_entry']`` is None.

    Files are written as soon as a case completes, so a mid-batch crash
    still preserves the artifacts for cases that finished. Returns the
    paths actually written (keys: ``data``, optionally ``monitor``).
    """
    from pathlib import Path as _Path
    tmp_dir = _Path(report_dir) / TMP_SUBDIR
    tmp_dir.mkdir(parents=True, exist_ok=True)

    case_key = payload['case_key']
    written: dict[str, str] = {}

    data_path = tmp_dir / f'{case_key}_data.json'
    data_path.write_text(
        json.dumps(payload['case_entry'], ensure_ascii=False, indent=2, default=str),
        encoding='utf-8',
    )
    written['data'] = str(data_path)

    if payload.get('monitor_entry') is not None:
        monitor_path = tmp_dir / f'{case_key}_monitor.json'
        monitor_path.write_text(
            json.dumps(payload['monitor_entry'], ensure_ascii=False, indent=2, default=str),
            encoding='utf-8',
        )
        written['monitor'] = str(monitor_path)

    return written


def _case_index_from_entry(case_entry: dict[str, Any]) -> int:
    """Extract the 1-based case index from a case_entry.

    Reads ``sub_test_id`` (e.g. ``"case_3"``) or falls back to ``case_id``;
    returns a large sentinel when both are unparsable so unknown-index
    entries sort to the end without crashing.
    """
    raw = case_entry.get('sub_test_id') or case_entry.get('case_id') or ''
    if isinstance(raw, str) and raw.startswith('case_'):
        try:
            return int(raw.removeprefix('case_'))
        except ValueError:
            pass
    return 10**9


def _iso_to_epoch(iso_str: str) -> float:
    """Parse an ISO timestamp; return 0.0 on failure."""
    if not iso_str:
        return 0.0
    try:
        return datetime.fromisoformat(iso_str).timestamp()
    except (TypeError, ValueError):
        return 0.0


def assemble_aggregated_data_from_tmp(
    *,
    report_dir: str,
    url: str,
    language: str = 'zh-CN',
    model: str | None = None,
    filter_model: str | None = None,
    write_test_results_json: bool = True,
) -> dict[str, Any]:
    """Reconstruct ``aggregated_data`` from per-case JSONs in ``<report_dir>/tmp/``.

    Reads every ``case_<n>_<safe>_data.json`` (and the matching
    ``_monitor.json`` if present), orders by case index, builds the index
    block, and — when ``write_test_results_json`` is True — writes the
    merged structure to ``<report_dir>/test_results.json``.

    Robust to partial state: missing data files for some indexes are
    skipped (still rendered as empty gen block if zero cases produced
    artifacts) so a half-crashed batch can still render whatever finished.
    """
    from pathlib import Path as _Path
    tmp_dir = _Path(report_dir) / TMP_SUBDIR
    gen_block: dict[str, Any] = {}
    case_entries: list[dict[str, Any]] = []

    if tmp_dir.is_dir():
        data_files = sorted(tmp_dir.glob('case_*_data.json'))
        loaded: list[tuple[int, str, dict[str, Any]]] = []
        for f in data_files:
            try:
                entry = json.loads(f.read_text(encoding='utf-8'))
            except (OSError, json.JSONDecodeError):
                continue
            if not isinstance(entry, dict):
                continue
            stem = f.stem  # case_<n>_<safe>_data
            case_key = stem[:-len('_data')] if stem.endswith('_data') else stem
            loaded.append((_case_index_from_entry(entry), case_key, entry))

        loaded.sort(key=lambda triple: triple[0])
        for _, case_key, entry in loaded:
            gen_block[case_key] = entry
            case_entries.append(entry)
            monitor_file = tmp_dir / f'{case_key}_monitor.json'
            if monitor_file.exists():
                try:
                    monitor_entry = json.loads(
                        monitor_file.read_text(encoding='utf-8'),
                    )
                except (OSError, json.JSONDecodeError):
                    monitor_entry = None
                if isinstance(monitor_entry, dict):
                    gen_block[f'{case_key}_monitor'] = monitor_entry

    now_iso = datetime.now().isoformat(timespec='seconds')
    count = {'total': 0, 'passed': 0, 'failed': 0, 'warning': 0}
    total_steps_all = 0
    summaries: list[str] = []
    gen_results: list[dict[str, Any]] = []
    all_start_ts: list[float] = []
    all_end_ts: list[float] = []

    for entry in case_entries:
        status = entry.get('status', 'failed')
        count['total'] += 1
        if status in count:
            count[status] += 1
        else:
            count['failed'] += 1
        metrics = entry.get('metrics') or {}
        total_steps_all += int(metrics.get('total_steps', 0) or 0)
        idx = _case_index_from_entry(entry)
        summary_text = entry.get('final_summary') or ''
        if summary_text:
            summaries.append(f'[case-{idx}] {summary_text}')
        gen_results.append({
            'name': entry.get('safe_name') or entry.get('name') or '',
            'display_name': entry.get('display_name') or entry.get('name') or '',
            'safe_name': entry.get('safe_name') or entry.get('name') or '',
            'status': status,
            'sub_test_id': entry.get('sub_test_id') or f'case_{idx}',
        })
        start_ts = _iso_to_epoch(entry.get('start_time') or '')
        end_ts = _iso_to_epoch(entry.get('end_time') or '')
        if start_ts:
            all_start_ts.append(start_ts)
        if end_ts:
            all_end_ts.append(end_ts)

    index_entry = build_index_entry(
        url=url,
        language=language,
        model=model,
        filter_model=filter_model,
        now_iso=now_iso,
        count=count,
        total_steps=total_steps_all,
        summaries=summaries,
        gen_results=gen_results,
        session_start_ts=min(all_start_ts) if all_start_ts else None,
        session_end_ts=max(all_end_ts) if all_end_ts else None,
    )

    gen_block['index'] = index_entry
    aggregated_data: dict[str, Any] = {'gen': gen_block}

    if write_test_results_json:
        out_path = _Path(report_dir) / 'test_results.json'
        try:
            out_path.write_text(
                json.dumps(aggregated_data, ensure_ascii=False, indent=2, default=str),
                encoding='utf-8',
            )
        except OSError:
            # Best-effort — the HTML render still works from the in-memory
            # ``aggregated_data`` even if the sidecar write fails.
            pass

    return aggregated_data

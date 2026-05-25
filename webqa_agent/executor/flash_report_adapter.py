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
        case_key, case_entry, gen_entry, summary_text = _build_case_entry(
            run_result=run_result,
            task=task,
            case_index=idx,
            now_iso=now_iso,
        )
        gen_block[case_key] = case_entry
        gen_results.append(gen_entry)
        if summary_text:
            summaries.append(f'[case-{idx}] {summary_text}')
        total_steps_all += int(case_entry['metrics'].get('total_steps', 0) or 0)
        status = case_entry['status']
        count['total'] += 1
        if status in count:
            count[status] += 1
        else:  # status not in canonical bucket falls back to 'failed'
            count['failed'] += 1

        # Accumulate per-run timestamps for session-level start/end.
        steps = list(getattr(run_result, 'steps', None) or [])
        if steps:
            first_ts: float = getattr(steps[0], 'timestamp', 0) or 0.0
            last_step = steps[-1]
            last_ts: float = (
                getattr(last_step, 'end_ts', 0)
                or getattr(last_step, 'timestamp', 0)
                or 0.0
            )
            if first_ts:
                all_start_ts.append(first_ts)
            if last_ts:
                all_end_ts.append(last_ts)

    session_start_iso = (
        datetime.fromtimestamp(min(all_start_ts)).isoformat(timespec='seconds')
        if all_start_ts else now_iso
    )
    session_end_iso = (
        datetime.fromtimestamp(max(all_end_ts)).isoformat(timespec='seconds')
        if all_end_ts else now_iso
    )

    test_items = [{
        'name': '功能测试' if language != 'en-US' else 'Functional',
        'item': (
            f'执行了 {total_steps_all} 个步骤(共 {count["total"]} 个 case)'
            if language != 'en-US'
            else f'Executed {total_steps_all} steps across {count["total"]} cases'
        ),
    }]
    summary_text = '\n\n'.join(summaries)

    index_entry = {
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

    gen_block['index'] = index_entry
    return {'gen': gen_block}


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
    safe_name = sanitize_case_name(display_name) or 'flash_run'
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

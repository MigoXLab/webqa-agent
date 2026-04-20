"""Adapter: cc-mini RunResult → gen-mode ParallelTestSession.

Keeps the cc-mini library (``webqa-cc-mini/``) free of any dependency on
``webqa_agent``. This mapping layer lives here so the CLI can render
cc-mini runs using the existing gen-mode React frontend (the same
``static/index.html`` template inlined by :class:`ResultAggregator`).

Why a separate module:
    The user can run cc-mini as a standalone library and get a light
    HTML artifact via ``webqa_cc_mini.features.report.render_html_report``.
    When running under the webqa_agent CLI (``use_cc_mini: true``),
    however, the expected deliverable is the *same* UI that gen mode
    produces. This module bridges the two without polluting cc-mini.

Mapping:
    * One cc-mini run → one :class:`ParallelTestSession`
    * The run itself → one :class:`TestResult` (category=FUNCTION)
    * All tool steps → one :class:`SubTestResult` (sequential steps)
    * Each cc-mini ``Step`` → one :class:`SubTestStep` with ``modelIO``
      holding the tool input + result as JSON. cc-mini does not separate
      screenshot attachments — they live inside the MCP tool output — so
      ``screenshots`` is left empty for now. (Extracting screenshots from
      MCP results is a future enhancement; the UI handles an empty list
      gracefully.)
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

# Soft cap on how much of each tool result we embed in the report.
# cc-mini tool outputs are sometimes multi-KB (accessibility snapshots,
# full DOM dumps) and inlining them verbatim would bloat every report.
_RESULT_TEXT_LIMIT = 4000


def run_result_to_session(
    run_result: Any,
    *,
    url: str,
    task: str,
    report_dir: str | None = None,
    language: str = 'zh-CN',
) -> ParallelTestSession:
    """Convert a cc-mini ``RunResult`` to a ``ParallelTestSession``.

    Args:
        run_result: The object returned by ``run_cc_mini``. Must expose
            ``final_text``, ``steps``, ``aborted``, ``input_tokens``,
            ``output_tokens`` attributes (duck-typed; concrete class not
            imported to keep this module independent of cc-mini).
        url: Target URL of the run (populates ``target_url`` + step 0).
        task: Task description given to cc-mini (used as the test name).
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

    aborted = bool(getattr(run_result, 'aborted', False))
    failed_count = sum(1 for s in sub_steps if s.status == TestStatus.FAILED)
    overall_status = (
        TestStatus.FAILED if (aborted or failed_count) else TestStatus.PASSED
    )

    final_text = getattr(run_result, 'final_text', '') or ''
    report_sections: list[SubTestReport] = []
    if final_text.strip():
        report_sections.append(SubTestReport(title='Summary', issues=final_text))

    now = datetime.now()
    sub_test_id = f'cc-mini-sub-{uuid.uuid4().hex[:8]}'
    sub = SubTestResult(
        sub_test_id=sub_test_id,
        name=task or 'cc-mini run',
        status=overall_status,
        metrics={
            'total_steps': len(sub_steps),
            'passed_steps': len(sub_steps) - failed_count,
            'failed_steps': failed_count,
            'input_tokens': int(getattr(run_result, 'input_tokens', 0) or 0),
            'output_tokens': int(getattr(run_result, 'output_tokens', 0) or 0),
            'aborted': aborted,
        },
        steps=sub_steps,
        start_time=now.isoformat(timespec='seconds'),
        end_time=now.isoformat(timespec='seconds'),
        final_summary=final_text,
        user_summary=final_text,
        report=report_sections,
    )

    test_id = f'cc-mini-{uuid.uuid4().hex[:8]}'
    test = TestResult(
        test_id=test_id,
        test_name=_truncate(f'cc-mini — {task}' if task else 'cc-mini run', 120),
        status=overall_status,
        category=TestCategory.FUNCTION,
        start_time=now,
        end_time=now,
        sub_tests=[sub],
        metrics={
            'test_case_count': 1,
            'passed_test_cases': 0 if overall_status == TestStatus.FAILED else 1,
            'failed_test_cases': 1 if overall_status == TestStatus.FAILED else 0,
            'total_steps': len(sub_steps),
            'input_tokens': int(getattr(run_result, 'input_tokens', 0) or 0),
            'output_tokens': int(getattr(run_result, 'output_tokens', 0) or 0),
        },
    )
    if overall_status == TestStatus.FAILED:
        test.error_message = (
            'cc-mini run aborted' if aborted
            else f'{failed_count} step(s) failed'
        )

    from webqa_agent.data.gen_structures import TestConfiguration
    test_cfg = TestConfiguration(
        test_id=test_id,
        test_name=test.test_name,
        enabled=True,
        report_config={'language': language, 'report_dir': report_dir or ''},
    )

    session = ParallelTestSession(
        session_id=f'cc-mini-{uuid.uuid4().hex[:8]}',
        target_url=url,
        test_configurations=[test_cfg],
        test_results={test_id: test},
        start_time=now,
        end_time=now,
        report_path=report_dir or '',
    )
    return session


def _map_step(index: int, step: Any) -> SubTestStep:
    tool = str(getattr(step, 'tool', '') or 'unknown')
    is_error = bool(getattr(step, 'is_error', False))
    input_dict = getattr(step, 'input', {}) or {}
    result_text = str(getattr(step, 'result', '') or '')

    # modelIO holds a concise JSON envelope the gen-mode UI renders as a
    # collapsible payload. Truncate noisy tool results to keep the report
    # artefact small without losing the "what did the agent do" signal.
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
        model_io = json.dumps(
            model_io_obj, ensure_ascii=False, indent=2, default=str,
        )
    except (TypeError, ValueError):
        model_io = repr({'tool': tool, 'input': input_dict, 'result': result_text})

    return SubTestStep(
        id=index,
        description=_describe_step(tool, input_dict),
        modelIO=model_io,
        actions=[],
        status=TestStatus.FAILED if is_error else TestStatus.PASSED,
        errors=result_text if is_error else '',
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

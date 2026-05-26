"""Concurrent batch executor for Flash engine runs.

Owns the scheduling logic that turns ``test_config.business_objectives``
(a single string OR a list of strings) into N concurrent ``run_cc_mini``
invocations gated by ``target.max_concurrent_tests``.

Design:

* Each task gets a unique ``worker_id = idx`` so it acquires its own
  Chromium profile dir and CDP port (``9222 + idx``). No two tasks ever
  collide because :func:`webqa_cc_mini.runner._default_browser_mcp`
  derives both from ``worker_id``.
* An ``asyncio.Semaphore`` caps in-flight tasks at ``max_concurrent``;
  finished tasks free a slot for the next queued task automatically.
* Per-task exceptions are caught inside the worker coroutine and turned
  into a synthetic ``RunResult(aborted=True, final_text='Error: ...')``
  so a single failure never cancels its siblings.
* After ``asyncio.gather`` returns, all ``RunResult``s are aggregated
  into one HTML report (each task becomes a ``case_<n>`` entry) plus
  one consolidated data-flow report when enabled.

The CLI (``webqa_agent/cli.py``) is reduced to: build ``shared_kwargs``
(model/api_key/extensions/etc.), construct ``FlashExecutor``, await
``execute(tasks)``, print the summary lines from ``FlashBatchResult``.
"""
from __future__ import annotations

import asyncio
import logging
from contextlib import nullcontext
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, ContextManager, Optional

logger = logging.getLogger(__name__)


@dataclass
class FlashBatchResult:
    """Outcome of a concurrent Flash batch run.

    ``run_results`` and ``statuses`` are positional with respect to the
    ``tasks`` list passed to :meth:`FlashExecutor.execute`.
    """
    run_results: list[Any] = field(default_factory=list)
    statuses: list[str] = field(default_factory=list)
    overall_status: str = 'failed'
    report_path: Optional[str] = None
    dataflow_path: Optional[str] = None
    total_input_tokens: int = 0
    total_output_tokens: int = 0
    total_steps: int = 0


class FlashExecutor:
    """Run N Flash tasks concurrently and render one consolidated report.

    Args:
        shared_kwargs: Keyword arguments forwarded to every
            ``webqa_agent.cli.execute_cc_mini_mode`` call (provider/model/...);
            per-task fields (``task``, ``worker_id``, ``screenshot_dir``,
            ``on_event``, ``data_flow_sink``) are injected by the
            executor and must NOT appear here.
        max_concurrent: Maximum in-flight tasks; clamped to ``[1, len(tasks)]``
            inside :meth:`execute`.
        report_dir: Absolute path where the consolidated report (and
            per-case screenshot subdirs) is written.
        url: Target URL — needed for the report header.
        language: Report language (``'zh-CN'`` or ``'en-US'``).
        save_screenshots: When True, each task gets its own
            ``screenshots/case_<n>/`` subdir.
        save_dataflow: When True, the consolidated data-flow report is
            generated after all tasks finish.
        invoke_runner: Async callable matching
            ``execute_cc_mini_mode(**shared_kwargs, task=..., worker_id=...,
            on_event=..., data_flow_sink=..., screenshot_dir=...)`` and
            returning a ``RunResult``. Injected for testability; CLI
            passes ``webqa_agent.cli._execute_cc_mini_mode`` (same object as
            ``execute_cc_mini_mode``).
    """

    def __init__(
        self,
        *,
        shared_kwargs: dict[str, Any],
        max_concurrent: int,
        report_dir: str,
        url: str,
        language: str = 'zh-CN',
        save_screenshots: bool = False,
        save_dataflow: bool = True,
        invoke_runner: Callable[..., Any],
        log_sink: Optional[Callable[[str], None]] = None,
        tracker_factory: Optional[Callable[[str], ContextManager]] = None,
    ) -> None:
        """Construct a concurrent Flash batch executor.

        ``tracker_factory(task_text)`` is expected to return a context
        manager whose ``__enter__`` yields an object with a settable
        ``result`` attribute. ``Display.display`` (from
        ``webqa_agent.utils.task_display_util``) satisfies this contract
        directly — it is callable and returns a ``_Tracker`` that records
        per-case lifecycle (start/end, error from raised exception,
        ``result`` set externally) into the singleton's running/completed
        lists.

        The executor only relies on the public protocol; it never reaches
        into Display internals, so swapping in any compatible tracker
        (e.g. a no-op stub for tests) just works.
        """
        self._shared_kwargs = dict(shared_kwargs)
        self._max_concurrent = max(1, int(max_concurrent))
        self._report_dir = report_dir
        self._url = url
        self._language = language
        self._save_screenshots = bool(save_screenshots)
        self._save_dataflow = bool(save_dataflow)
        self._invoke_runner = invoke_runner
        self._log_sink = log_sink
        self._tracker_factory = tracker_factory

        # Reject parameter collisions early so misuse surfaces at construction
        # rather than as a confusing TypeError mid-run.
        for forbidden in (
            'task', 'worker_id', 'on_event', 'data_flow_sink',
            'screenshot_dir',
        ):
            if forbidden in self._shared_kwargs:
                raise ValueError(
                    f'shared_kwargs must not contain {forbidden!r}; the '
                    'executor injects this per-task.'
                )

    async def execute(self, tasks: list[str]) -> FlashBatchResult:
        """Run ``tasks`` concurrently and return the aggregated result.

        ``tasks`` must be non-empty; an empty list raises ``ValueError``.
        """
        if not tasks:
            raise ValueError('tasks must not be empty')
        cleaned = [t.strip() for t in tasks if isinstance(t, str) and t.strip()]
        if not cleaned:
            raise ValueError('tasks must contain at least one non-empty string')

        n = len(cleaned)
        concurrency = min(self._max_concurrent, n)
        sem = asyncio.Semaphore(concurrency)
        is_multi = n > 1

        logger.info(
            'Flash batch: %d task(s), concurrency=%d', n, concurrency,
        )

        async def _run_one(idx: int, task_text: str) -> Any:
            async with sem:
                return await self._invoke_one(
                    idx=idx,
                    total=n,
                    task_text=task_text,
                    is_multi=is_multi,
                )

        run_results = await asyncio.gather(
            *[_run_one(i, t) for i, t in enumerate(cleaned)],
        )

        statuses = [_derive_case_status(r) for r in run_results]
        overall = (
            'passed' if all(s == 'passed' for s in statuses) else 'failed'
        )

        report_path = self._render_report(cleaned, run_results)
        dataflow_path = self._render_dataflow() if self._save_dataflow else None

        total_in = sum(int(getattr(r, 'input_tokens', 0) or 0) for r in run_results)
        total_out = sum(int(getattr(r, 'output_tokens', 0) or 0) for r in run_results)
        total_steps = sum(len(getattr(r, 'steps', None) or []) for r in run_results)

        return FlashBatchResult(
            run_results=run_results,
            statuses=statuses,
            overall_status=overall,
            report_path=report_path,
            dataflow_path=dataflow_path,
            total_input_tokens=total_in,
            total_output_tokens=total_out,
            total_steps=total_steps,
        )

    async def _invoke_one(
        self, *, idx: int, total: int, task_text: str, is_multi: bool,
    ) -> Any:
        """Run a single task; convert any exception into a synthetic RunResult.

        The synthetic result keeps the report rendering pipeline uniform —
        every task has a RunResult to render, even if the runner itself crashed
        before producing one.
        """
        screenshot_dir: str | None = None
        if self._save_screenshots:
            # Multi-case: nest each case under screenshots/ as case_N/ —
            # cc-mini's runner detects the parent dir name and emits URLs
            # starting with "screenshots/case_N/", which the report frontend
            # accepts (it requires the "screenshots/" prefix).
            # Single-case: keep the legacy flat layout for backward compat.
            sub = (
                f'screenshots/case_{idx + 1}' if is_multi
                else 'screenshots'
            )
            screenshot_dir = str(Path(self._report_dir) / sub)

        per_task_kwargs = {
            **self._shared_kwargs,
            'task': task_text,
            'worker_id': idx,
            'screenshot_dir': screenshot_dir,
            'on_event': _build_stream_handler(
                case_idx=idx, total=total, log_sink=self._log_sink,
            ),
            'data_flow_sink': _build_data_flow_sink(
                report_dir=self._report_dir,
                save_dataflow=self._save_dataflow,
                case_idx=idx,
                total=total,
            ),
        }

        # Use the tracker as a plain ``with`` block: ``__enter__`` records
        # the start in ``Display.display.running``, ``__exit__`` moves it to
        # ``completed`` — pulling the failure string from any exception that
        # escapes. We set ``tracker.result`` only on the success path; if
        # the runner crashes, the tracker writes ``error=str(exc)`` and
        # ``result=None``, which the frontend renders as "异常中断 / -".
        cm = (
            self._tracker_factory(task_text)
            if self._tracker_factory is not None
            else nullcontext()
        )
        try:
            with cm as tracker:
                result = await self._invoke_runner(**per_task_kwargs)
                if result is None:
                    raise RuntimeError('runner returned None')
                if tracker is not None and hasattr(tracker, 'result'):
                    tracker.result = _derive_case_status(result)
            return result
        except Exception as exc:
            logger.exception('Flash case %d/%d aborted', idx + 1, total)
            return _synthesize_failure_result(exc)

    def _render_report(
        self, tasks: list[str], run_results: list[Any],
    ) -> str | None:
        from webqa_agent.utils.flash_utils import render_flash_multi_report

        model = str(self._shared_kwargs.get('model') or '')
        filter_model = str(self._shared_kwargs.get('filter_model') or '')

        try:
            return render_flash_multi_report(
                run_results,
                report_dir=self._report_dir,
                url=self._url,
                tasks=tasks,
                language=self._language,
                model=model or None,
                filter_model=filter_model or None,
            )
        except Exception:
            logger.exception('Flash multi-report rendering failed')
            return None

    def _render_dataflow(self) -> str | None:
        try:
            from webqa_agent.utils.data_flow_reporter import \
                generate_data_flow_report
            return generate_data_flow_report(
                self._report_dir,
                group_mode='tool',
            )
        except Exception:
            logger.exception('Flash data-flow report generation failed')
            return None


# ---------------------------------------------------------------------------
# Per-task helpers
# ---------------------------------------------------------------------------

def _build_stream_handler(
    *, case_idx: int, total: int, log_sink: 'Callable[[str], None] | None' = None,
):
    """Return an ``on_event`` handler that prefixes lines with ``[case-i/N]``.

    Adds a case prefix so concurrent stdout streams stay attributable to a
    task. For single-task runs the prefix is omitted to preserve the prior
    user-facing format.

    When ``log_sink`` is provided, each complete line is also forwarded to it
    so the caller can collect output for progress reporting without needing to
    intercept stdout.
    """
    text_open = [False]
    text_buf: list[str] = []
    prefix = '' if total <= 1 else f'[case-{case_idx + 1}/{total}] '

    def _close_text() -> None:
        if text_open[0]:
            print('', flush=True)
            text_open[0] = False
        if log_sink and text_buf:
            log_sink(''.join(text_buf))
            text_buf.clear()

    def _sink_line(line: str) -> None:
        if log_sink:
            log_sink(line)

    def handle(evt) -> None:
        kind = evt[0]
        if kind == 'text':
            chunk = evt[1]
            if prefix and not text_open[0]:
                print(prefix, end='', flush=True)
            print(chunk, end='', flush=True)
            text_open[0] = not chunk.endswith('\n')
            # Accumulate chunks; flush complete lines to sink immediately.
            if log_sink:
                text_buf.append(chunk)
                while True:
                    joined = ''.join(text_buf)
                    nl = joined.find('\n')
                    if nl == -1:
                        text_buf.clear()
                        text_buf.append(joined)
                        break
                    log_sink(joined[:nl])
                    remainder = joined[nl + 1:]
                    text_buf.clear()
                    if remainder:
                        text_buf.append(remainder)
        elif kind == 'waiting':
            _close_text()
        elif kind == 'tool_call':
            _close_text()
            _, name, _tool_input, activity = evt
            line = f'{prefix}🔧 {activity or name}'
            print(line, flush=True)
            _sink_line(line)
        elif kind == 'tool_result':
            _, name, _input, result = evt
            if getattr(result, 'is_error', False):
                content = (
                    result.content if isinstance(result.content, str)
                    else str(result.content)
                )
                snippet = content[:200].replace('\n', ' ')
                line = f'{prefix}   ❌ [{name}] {snippet}'
                print(line, flush=True)
                _sink_line(line)
        elif kind == 'usage':
            u = evt[1]
            inp = getattr(u, 'input_tokens', 0) or 0
            out = getattr(u, 'output_tokens', 0) or 0
            line = f'{prefix}   📊 {inp}↑ {out}↓'
            print(line, flush=True)
            _sink_line(line)
        elif kind == 'error':
            _close_text()
            line = f'{prefix}⚠️  {evt[1]}'
            print(line, flush=True)
            _sink_line(line)

    return handle


def _build_data_flow_sink(
    *, report_dir: str, save_dataflow: bool, case_idx: int, total: int,
):
    """Return a sink that records data-flow events and tags them per case.

    Returns ``None`` when dataflow recording is disabled — runner accepts
    ``None`` and skips the sink callbacks entirely.
    """
    if not save_dataflow:
        return None

    from webqa_agent.utils.data_flow_reporter import \
        record_data_flow_event_object

    def _sink(event: dict[str, Any]) -> None:
        # record_data_flow_event_object only persists timestamp/stage/
        # event_type/payload, so case_index lives inside payload.
        if total > 1:
            payload = event.get('payload')
            if isinstance(payload, dict):
                payload.setdefault('case_index', case_idx + 1)
                payload.setdefault('case_total', total)
        record_data_flow_event_object(event, report_dir=report_dir)

    return _sink


def _derive_case_status(run_result: Any) -> str:
    """Re-derive a status label for one case using Flash's shared logic."""
    # Local import keeps Flash sys.path patching out of module load.
    from webqa_agent.executor.flash_report_adapter import \
        _build_case_entry  # noqa: F401

    # _build_case_entry already calls derive_status; reuse it instead of
    # duplicating the outcome-parsing logic here.
    _, case_entry, _, _ = _build_case_entry(
        run_result=run_result,
        task='',
        case_index=1,
        now_iso='',
    )
    return str(case_entry.get('status', 'failed'))


def _synthesize_failure_result(exc: BaseException) -> Any:
    """Build a duck-typed RunResult for a task that crashed mid-flight.

    Loads the real RunResult dataclass when available so downstream code
    that does ``isinstance`` checks (none today) keeps working; falls
    back to a SimpleNamespace if the runner module can't be loaded
    (e.g. webqa-cc-mini tree missing in unit tests).
    """
    try:
        from webqa_agent.executor.flash.runner import RunResult
        return RunResult(
            final_text=f'Error: {exc}',
            steps=[],
            aborted=True,
            input_tokens=0,
            output_tokens=0,
        )
    except Exception:
        logger.debug(
            'falling back to SimpleNamespace synthetic RunResult',
            exc_info=True,
        )

    from types import SimpleNamespace
    return SimpleNamespace(
        final_text=f'Error: {exc}',
        steps=[],
        aborted=True,
        input_tokens=0,
        output_tokens=0,
        extensions_failed=[],
        data_flow_events=[],
    )

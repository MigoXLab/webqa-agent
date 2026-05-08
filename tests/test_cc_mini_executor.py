"""Unit tests for the cc-mini concurrent batch executor.

Validates:
* concurrency cap (semaphore actually limits in-flight tasks)
* per-task worker_id assignment (so Chromium profile/CDP port stay isolated)
* per-task exception isolation (one crash doesn't kill siblings)
* overall_status: passed only when every case is passed
* report rendering is invoked once per batch with all results
"""
from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import Any
from unittest.mock import patch

import pytest

from webqa_agent.executor.cc_mini_executor import CcMiniExecutor


@dataclass
class _Step:
    tool: str = 'tool'
    input: dict = field(default_factory=dict)
    result: str = 'ok'
    is_error: bool = False


@dataclass
class _RunResult:
    final_text: str = ''
    steps: list = field(default_factory=list)
    aborted: bool = False
    input_tokens: int = 0
    output_tokens: int = 0
    extensions_failed: list = field(default_factory=list)
    data_flow_events: list = field(default_factory=list)


def _make_executor(
    *, invoke_runner, max_concurrent=2, save_dataflow=False, save_screenshots=False,
    shared_kwargs=None, report_dir='/tmp/cc-mini-test',
):
    return CcMiniExecutor(
        shared_kwargs=shared_kwargs or {'provider': 'anthropic', 'model': 'sonnet'},
        max_concurrent=max_concurrent,
        report_dir=report_dir,
        url='https://example.com',
        save_screenshots=save_screenshots,
        save_dataflow=save_dataflow,
        invoke_runner=invoke_runner,
    )


# ---------------------------------------------------------------------------
# Construction guards
# ---------------------------------------------------------------------------

class TestConstruction:
    def test_rejects_per_task_kwargs_in_shared(self):
        async def _fake(**kwargs):
            return _RunResult()

        with pytest.raises(ValueError, match='task'):
            CcMiniExecutor(
                shared_kwargs={'task': 'x'},
                max_concurrent=1,
                report_dir='/tmp',
                url='u',
                invoke_runner=_fake,
            )

    def test_rejects_worker_id_in_shared(self):
        async def _fake(**kwargs):
            return _RunResult()

        with pytest.raises(ValueError, match='worker_id'):
            CcMiniExecutor(
                shared_kwargs={'worker_id': 0},
                max_concurrent=1,
                report_dir='/tmp',
                url='u',
                invoke_runner=_fake,
            )

    def test_max_concurrent_clamped_to_one(self):
        async def _fake(**kwargs):
            return _RunResult()

        ex = _make_executor(invoke_runner=_fake, max_concurrent=0)
        assert ex._max_concurrent == 1


# ---------------------------------------------------------------------------
# Empty-input guards
# ---------------------------------------------------------------------------

class TestExecuteInputs:
    def test_empty_tasks_raises(self):
        async def _fake(**kwargs):
            return _RunResult()

        ex = _make_executor(invoke_runner=_fake)
        with pytest.raises(ValueError, match='must not be empty'):
            asyncio.run(ex.execute([]))

    def test_blank_tasks_raise(self):
        async def _fake(**kwargs):
            return _RunResult()

        ex = _make_executor(invoke_runner=_fake)
        with pytest.raises(ValueError, match='at least one non-empty'):
            asyncio.run(ex.execute(['', '   ']))


# ---------------------------------------------------------------------------
# Per-task scheduling
# ---------------------------------------------------------------------------

class TestScheduling:
    def test_each_task_gets_unique_worker_id(self):
        seen_ids: list[int] = []

        async def _fake(**kwargs):
            seen_ids.append(kwargs['worker_id'])
            return _RunResult()

        ex = _make_executor(invoke_runner=_fake, max_concurrent=2)
        with patch(
            'webqa_agent.utils.cc_mini_utils.render_cc_mini_multi_report',
            return_value=None,
        ):
            asyncio.run(ex.execute(['t1', 't2', 't3']))
        assert sorted(seen_ids) == [0, 1, 2]

    def test_each_task_receives_its_own_text(self):
        seen_tasks: list[str] = []

        async def _fake(**kwargs):
            seen_tasks.append(kwargs['task'])
            return _RunResult()

        ex = _make_executor(invoke_runner=_fake, max_concurrent=3)
        with patch(
            'webqa_agent.utils.cc_mini_utils.render_cc_mini_multi_report',
            return_value=None,
        ):
            asyncio.run(ex.execute(['alpha', 'beta', 'gamma']))
        assert sorted(seen_tasks) == ['alpha', 'beta', 'gamma']

    def test_concurrency_actually_limited(self):
        """With concurrency=2 and 4 tasks, max in-flight is 2."""
        in_flight = 0
        peak = 0
        lock = asyncio.Lock()

        async def _fake(**kwargs):
            nonlocal in_flight, peak
            async with lock:
                in_flight += 1
                peak = max(peak, in_flight)
            await asyncio.sleep(0.05)
            async with lock:
                in_flight -= 1
            return _RunResult()

        ex = _make_executor(invoke_runner=_fake, max_concurrent=2)
        with patch(
            'webqa_agent.utils.cc_mini_utils.render_cc_mini_multi_report',
            return_value=None,
        ):
            asyncio.run(ex.execute(['t1', 't2', 't3', 't4']))
        assert peak == 2

    def test_screenshot_dir_per_case_when_multi(self):
        """Multi-case nests case_N/ under screenshots/ so the runner's parent-
        name detection emits URLs starting with `screenshots/`."""
        seen_dirs: list[str] = []

        async def _fake(**kwargs):
            seen_dirs.append(kwargs['screenshot_dir'])
            return _RunResult()

        ex = _make_executor(
            invoke_runner=_fake, max_concurrent=2,
            save_screenshots=True, report_dir='/tmp/cc-mini',
        )
        with patch(
            'webqa_agent.utils.cc_mini_utils.render_cc_mini_multi_report',
            return_value=None,
        ):
            asyncio.run(ex.execute(['t1', 't2']))
        assert sorted(seen_dirs) == [
            '/tmp/cc-mini/screenshots/case_1',
            '/tmp/cc-mini/screenshots/case_2',
        ]

    def test_screenshot_dir_flat_when_single(self):
        seen_dirs: list[str] = []

        async def _fake(**kwargs):
            seen_dirs.append(kwargs['screenshot_dir'])
            return _RunResult()

        ex = _make_executor(
            invoke_runner=_fake, max_concurrent=1,
            save_screenshots=True, report_dir='/tmp/cc-mini',
        )
        with patch(
            'webqa_agent.utils.cc_mini_utils.render_cc_mini_multi_report',
            return_value=None,
        ):
            asyncio.run(ex.execute(['solo']))
        assert seen_dirs == ['/tmp/cc-mini/screenshots']

    def test_screenshot_dir_none_when_disabled(self):
        seen_dirs: list[Any] = []

        async def _fake(**kwargs):
            seen_dirs.append(kwargs['screenshot_dir'])
            return _RunResult()

        ex = _make_executor(invoke_runner=_fake, save_screenshots=False)
        with patch(
            'webqa_agent.utils.cc_mini_utils.render_cc_mini_multi_report',
            return_value=None,
        ):
            asyncio.run(ex.execute(['t']))
        assert seen_dirs == [None]


# ---------------------------------------------------------------------------
# Failure isolation
# ---------------------------------------------------------------------------

class TestFailureIsolation:
    def test_one_task_raises_does_not_kill_siblings(self):
        async def _fake(**kwargs):
            if kwargs['worker_id'] == 1:
                raise RuntimeError('case-2 boom')
            return _RunResult()

        ex = _make_executor(invoke_runner=_fake, max_concurrent=3)
        with patch(
            'webqa_agent.utils.cc_mini_utils.render_cc_mini_multi_report',
            return_value=None,
        ):
            batch = asyncio.run(ex.execute(['t1', 't2', 't3']))
        # Three RunResults returned even though one raised
        assert len(batch.run_results) == 3
        # The crashed case's synthetic result is aborted with an Error: prefix
        crashed = batch.run_results[1]
        assert getattr(crashed, 'aborted', False) is True
        assert str(getattr(crashed, 'final_text', '')).startswith('Error:')
        # Siblings stayed healthy
        assert getattr(batch.run_results[0], 'aborted', True) is False
        assert getattr(batch.run_results[2], 'aborted', True) is False

    def test_overall_status_failed_when_any_case_fails(self):
        async def _fake(**kwargs):
            if kwargs['worker_id'] == 0:
                raise RuntimeError('boom')
            return _RunResult()

        ex = _make_executor(invoke_runner=_fake, max_concurrent=2)
        with patch(
            'webqa_agent.utils.cc_mini_utils.render_cc_mini_multi_report',
            return_value=None,
        ):
            batch = asyncio.run(ex.execute(['t1', 't2']))
        assert batch.overall_status == 'failed'
        assert batch.statuses[0] == 'failed'
        assert batch.statuses[1] == 'passed'

    def test_overall_status_passed_when_all_cases_pass(self):
        async def _fake(**kwargs):
            # outcome marker forces the status derivation to 'passed'
            return _RunResult(
                final_text='<final_outcome>'
                           '{"objective_achieved": true}'
                           '</final_outcome>',
            )

        ex = _make_executor(invoke_runner=_fake, max_concurrent=2)
        with patch(
            'webqa_agent.utils.cc_mini_utils.render_cc_mini_multi_report',
            return_value=None,
        ):
            batch = asyncio.run(ex.execute(['t1', 't2']))
        assert batch.overall_status == 'passed'
        assert all(s == 'passed' for s in batch.statuses)


# ---------------------------------------------------------------------------
# Aggregation
# ---------------------------------------------------------------------------

class TestAggregation:
    def test_token_totals_summed(self):
        async def _fake(**kwargs):
            return _RunResult(input_tokens=100, output_tokens=20)

        ex = _make_executor(invoke_runner=_fake, max_concurrent=2)
        with patch(
            'webqa_agent.utils.cc_mini_utils.render_cc_mini_multi_report',
            return_value=None,
        ):
            batch = asyncio.run(ex.execute(['t1', 't2', 't3']))
        assert batch.total_input_tokens == 300
        assert batch.total_output_tokens == 60

    def test_total_steps_summed(self):
        async def _fake(**kwargs):
            return _RunResult(steps=[_Step(), _Step()])

        ex = _make_executor(invoke_runner=_fake, max_concurrent=2)
        with patch(
            'webqa_agent.utils.cc_mini_utils.render_cc_mini_multi_report',
            return_value=None,
        ):
            batch = asyncio.run(ex.execute(['t1', 't2']))
        assert batch.total_steps == 4

    def test_report_renderer_called_with_all_results(self):
        async def _fake(**kwargs):
            return _RunResult()

        ex = _make_executor(invoke_runner=_fake, max_concurrent=2)
        with patch(
            'webqa_agent.utils.cc_mini_utils.render_cc_mini_multi_report',
        ) as mock_render:
            mock_render.return_value = '/tmp/report.html'
            batch = asyncio.run(ex.execute(['t1', 't2', 't3']))
        assert batch.report_path == '/tmp/report.html'
        mock_render.assert_called_once()
        kwargs = mock_render.call_args.kwargs
        assert kwargs['tasks'] == ['t1', 't2', 't3']
        assert len(mock_render.call_args.args[0]) == 3


# ---------------------------------------------------------------------------
# Multi-case adapter
# ---------------------------------------------------------------------------

class TestMultiCaseAdapter:
    def test_all_cases_appear_in_aggregated_data(self):
        from webqa_agent.executor.cc_mini_report_adapter import \
            run_results_to_aggregated_data

        results = [_RunResult() for _ in range(3)]
        agg = run_results_to_aggregated_data(
            results, url='u', tasks=['a', 'b', 'c'],
        )
        gen = agg['gen']
        case_keys = [k for k in gen if k.startswith('case_')]
        assert len(case_keys) == 3
        assert any(k.startswith('case_1_') for k in case_keys)
        assert any(k.startswith('case_2_') for k in case_keys)
        assert any(k.startswith('case_3_') for k in case_keys)

    def test_index_count_aggregates_passes(self):
        from webqa_agent.executor.cc_mini_report_adapter import \
            run_results_to_aggregated_data

        results = [
            _RunResult(final_text='<final_outcome>{"objective_achieved": true}</final_outcome>'),
            _RunResult(aborted=True, final_text='Error: x'),
            _RunResult(final_text='<final_outcome>{"objective_achieved": true}</final_outcome>'),
        ]
        agg = run_results_to_aggregated_data(
            results, url='u', tasks=['a', 'b', 'c'],
        )
        count = agg['gen']['index']['aggregated_results']['count']
        assert count == {'total': 3, 'passed': 2, 'failed': 1, 'warning': 0}

    def test_length_mismatch_raises(self):
        from webqa_agent.executor.cc_mini_report_adapter import \
            run_results_to_aggregated_data

        with pytest.raises(ValueError, match='must have the same length'):
            run_results_to_aggregated_data(
                [_RunResult()], url='u', tasks=['a', 'b'],
            )

    def test_empty_inputs_raise(self):
        from webqa_agent.executor.cc_mini_report_adapter import \
            run_results_to_aggregated_data

        with pytest.raises(ValueError, match='must not be empty'):
            run_results_to_aggregated_data([], url='u', tasks=[])

    def test_single_case_backward_compat(self):
        """run_result_to_aggregated_data still returns case_1 for a single
        run."""
        from webqa_agent.executor.cc_mini_report_adapter import \
            run_result_to_aggregated_data

        agg = run_result_to_aggregated_data(_RunResult(), url='u', task='t')
        case_keys = [k for k in agg['gen'] if k.startswith('case_')]
        assert len(case_keys) == 1
        assert case_keys[0].startswith('case_1_')

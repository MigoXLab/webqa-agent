"""Unit tests for the cc-mini → gen-mode report adapter.

The adapter is a pure data mapper: RunResult → ParallelTestSession. No
filesystem or LLM side effects. Tests cover the mapping contract so CLI
users get a stable structure regardless of how cc-mini evolves.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from webqa_agent.data.gen_structures import (ParallelTestSession, TestCategory,
                                             TestStatus)
from webqa_agent.executor.cc_mini_report_adapter import (
    _bare_tool_name, _map_step_dict, run_result_to_aggregated_data,
    run_result_to_session)


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


# ---------------------------------------------------------------------------
# Top-level shape
# ---------------------------------------------------------------------------

class TestSessionShape:
    def test_returns_parallel_test_session(self):
        session = run_result_to_session(
            _RunResult(), url='https://x', task='t',
        )
        assert isinstance(session, ParallelTestSession)

    def test_single_test_result_with_function_category(self):
        session = run_result_to_session(
            _RunResult(), url='https://x', task='t',
        )
        assert len(session.test_results) == 1
        test = next(iter(session.test_results.values()))
        assert test.category == TestCategory.FUNCTION

    def test_target_url_propagated(self):
        session = run_result_to_session(
            _RunResult(), url='https://example.com/foo', task='t',
        )
        assert session.target_url == 'https://example.com/foo'

    def test_task_appears_in_test_name(self):
        session = run_result_to_session(
            _RunResult(), url='u', task='verify login flow',
        )
        test = next(iter(session.test_results.values()))
        assert 'verify login flow' in test.test_name

    def test_report_path_stored_on_session(self):
        session = run_result_to_session(
            _RunResult(), url='u', task='t', report_dir='/tmp/out',
        )
        assert session.report_path == '/tmp/out'

    def test_language_stored_in_test_configuration(self):
        session = run_result_to_session(
            _RunResult(), url='u', task='t', language='en-US',
        )
        assert session.test_configurations[0].report_config['language'] == 'en-US'


# ---------------------------------------------------------------------------
# Status derivation
# ---------------------------------------------------------------------------

class TestStatusDerivation:
    def test_all_passing_steps_yields_passed(self):
        rr = _RunResult(steps=[
            _Step(result='ok', is_error=False),
            _Step(result='ok', is_error=False),
        ])
        session = run_result_to_session(rr, url='u', task='t')
        test = next(iter(session.test_results.values()))
        assert test.status == TestStatus.PASSED
        assert test.sub_tests[0].status == TestStatus.PASSED

    def test_any_error_step_yields_failed(self):
        rr = _RunResult(steps=[
            _Step(is_error=False),
            _Step(is_error=True, result='boom'),
        ])
        session = run_result_to_session(rr, url='u', task='t')
        test = next(iter(session.test_results.values()))
        assert test.status == TestStatus.FAILED

    def test_aborted_run_without_error_steps_still_failed(self):
        rr = _RunResult(aborted=True, steps=[_Step(is_error=False)])
        session = run_result_to_session(rr, url='u', task='t')
        test = next(iter(session.test_results.values()))
        assert test.status == TestStatus.FAILED
        assert 'aborted' in test.error_message

    def test_error_message_counts_failed_steps(self):
        rr = _RunResult(steps=[
            _Step(is_error=True), _Step(is_error=True), _Step(is_error=False),
        ])
        session = run_result_to_session(rr, url='u', task='t')
        test = next(iter(session.test_results.values()))
        assert '2' in test.error_message

    def test_empty_steps_list_yields_passed(self):
        session = run_result_to_session(_RunResult(), url='u', task='t')
        test = next(iter(session.test_results.values()))
        assert test.status == TestStatus.PASSED


# ---------------------------------------------------------------------------
# Step mapping
# ---------------------------------------------------------------------------

class TestStepMapping:
    def test_step_count_matches(self):
        rr = _RunResult(steps=[_Step() for _ in range(5)])
        session = run_result_to_session(rr, url='u', task='t')
        sub = next(iter(session.test_results.values())).sub_tests[0]
        assert len(sub.steps) == 5

    def test_step_ids_are_sequential_from_one(self):
        rr = _RunResult(steps=[_Step() for _ in range(3)])
        session = run_result_to_session(rr, url='u', task='t')
        sub = next(iter(session.test_results.values())).sub_tests[0]
        assert [s.id for s in sub.steps] == [1, 2, 3]

    def test_error_step_status_and_errors_populated(self):
        rr = _RunResult(steps=[_Step(is_error=True, result='element missing')])
        session = run_result_to_session(rr, url='u', task='t')
        step = next(iter(session.test_results.values())).sub_tests[0].steps[0]
        assert step.status == TestStatus.FAILED
        assert step.errors == 'element missing'

    def test_ok_step_has_empty_errors(self):
        rr = _RunResult(steps=[_Step(is_error=False, result='ok')])
        session = run_result_to_session(rr, url='u', task='t')
        step = next(iter(session.test_results.values())).sub_tests[0].steps[0]
        assert step.status == TestStatus.PASSED
        assert step.errors == ''

    def test_model_io_contains_tool_input_result(self):
        rr = _RunResult(steps=[
            _Step(tool='click', input={'selector': '#x'}, result='done'),
        ])
        session = run_result_to_session(rr, url='u', task='t')
        step = next(iter(session.test_results.values())).sub_tests[0].steps[0]
        assert '"tool"' in step.modelIO
        assert 'click' in step.modelIO
        assert '#x' in step.modelIO
        assert 'done' in step.modelIO

    def test_navigate_description_has_url(self):
        rr = _RunResult(steps=[
            _Step(tool='navigate_page', input={'url': 'https://target'}),
        ])
        session = run_result_to_session(rr, url='u', task='t')
        step = next(iter(session.test_results.values())).sub_tests[0].steps[0]
        assert 'Navigate to https://target' in step.description

    def test_click_description_has_selector(self):
        rr = _RunResult(steps=[
            _Step(tool='click', input={'selector': '#login'}),
        ])
        session = run_result_to_session(rr, url='u', task='t')
        step = next(iter(session.test_results.values())).sub_tests[0].steps[0]
        assert step.description == 'Click #login'

    def test_unknown_tool_falls_back_to_tool_name(self):
        rr = _RunResult(steps=[_Step(tool='custom_tool', input={'x': 1})])
        session = run_result_to_session(rr, url='u', task='t')
        step = next(iter(session.test_results.values())).sub_tests[0].steps[0]
        assert step.description == 'custom_tool'

    def test_long_result_text_is_truncated(self):
        big = 'x' * 10_000
        rr = _RunResult(steps=[_Step(tool='snap', result=big)])
        session = run_result_to_session(rr, url='u', task='t')
        step = next(iter(session.test_results.values())).sub_tests[0].steps[0]
        # modelIO should be substantially smaller than the raw 10KB result,
        # and should flag truncation.
        assert len(step.modelIO) < 6_000
        assert 'result_truncated' in step.modelIO
        assert 'full_result_length' in step.modelIO


# ---------------------------------------------------------------------------
# Metrics + summary
# ---------------------------------------------------------------------------

class TestMetricsAndSummary:
    def test_token_counts_propagate_to_metrics(self):
        rr = _RunResult(input_tokens=1234, output_tokens=567)
        session = run_result_to_session(rr, url='u', task='t')
        test = next(iter(session.test_results.values()))
        assert test.metrics['input_tokens'] == 1234
        assert test.metrics['output_tokens'] == 567
        assert test.sub_tests[0].metrics['input_tokens'] == 1234

    def test_final_text_becomes_summary_sections(self):
        rr = _RunResult(final_text='Everything works.')
        session = run_result_to_session(rr, url='u', task='t')
        sub = next(iter(session.test_results.values())).sub_tests[0]
        assert sub.final_summary == 'Everything works.'
        assert sub.user_summary == 'Everything works.'
        assert len(sub.report) == 1
        assert 'Everything works.' in sub.report[0].issues

    def test_empty_final_text_omits_report_section(self):
        rr = _RunResult(final_text='')
        session = run_result_to_session(rr, url='u', task='t')
        sub = next(iter(session.test_results.values())).sub_tests[0]
        assert sub.report == []

    def test_session_to_dict_contains_function_category(self):
        """Gen-mode renderer reads the grouped output of ``to_dict``; this test
        pins the path so a schema regression here breaks the HTML report tests
        immediately."""
        rr = _RunResult(steps=[_Step()])
        session = run_result_to_session(rr, url='u', task='t')
        d = session.to_dict()
        assert 'function_test_results' in d['test_results']
        items = d['test_results']['function_test_results']['items']
        assert len(items) == 1
        assert len(items[0]['sub_tests'][0]['steps']) == 1


# ---------------------------------------------------------------------------
# Aggregated-data mapping — the shape the React frontend actually reads
# ---------------------------------------------------------------------------

class TestAggregatedDataShape:
    """The frontend reads ``window.testResultData`` expecting the gen-mode
    aggregated dict (``{"gen": {"case_1_<safe>": ..., "index": ...}}``).

    Passing ``ParallelTestSession.to_dict()`` alone renders empty — that
    regression is why this module exists. These tests pin the contract.
    """

    def test_top_level_has_gen_key(self):
        agg = run_result_to_aggregated_data(_RunResult(), url='u', task='t')
        assert set(agg.keys()) == {'gen'}

    def test_has_index_and_single_case(self):
        agg = run_result_to_aggregated_data(_RunResult(), url='u', task='t')
        keys = set(agg['gen'].keys())
        assert 'index' in keys
        case_keys = keys - {'index'}
        assert len(case_keys) == 1

    def test_case_key_uses_case_1_prefix_and_sanitized_name(self):
        agg = run_result_to_aggregated_data(
            _RunResult(), url='u', task='verify search flow',
        )
        case_keys = [k for k in agg['gen'] if k != 'index']
        # sanitize_case_name collapses whitespace/punct to underscores
        assert case_keys == ['case_1_verify_search_flow']

    def test_empty_task_gets_fallback_safe_name(self):
        agg = run_result_to_aggregated_data(_RunResult(), url='u', task='')
        case_keys = [k for k in agg['gen'] if k != 'index']
        # sanitize_case_name preserves '-' so the fallback keeps the dash.
        assert case_keys == ['case_1_cc-mini_run']

    def test_case_entry_has_required_fields(self):
        agg = run_result_to_aggregated_data(
            _RunResult(steps=[_Step()]), url='u', task='t',
        )
        case = next(v for k, v in agg['gen'].items() if k != 'index')
        for field_name in (
            'name', 'display_name', 'safe_name', 'case_id', 'sub_test_id',
            'start_time', 'end_time', 'status', 'steps', 'case_info',
        ):
            assert field_name in case, f'missing {field_name}'

    def test_index_has_session_info_and_gen_result(self):
        agg = run_result_to_aggregated_data(
            _RunResult(), url='https://x.test', task='t',
        )
        idx = agg['gen']['index']
        assert idx['session_info']['target_url'] == 'https://x.test'
        assert idx['aggregated_results']['gen_result']
        assert idx['aggregated_results']['gen_result'][0]['sub_test_id'] == 'case_1'

    def test_passed_run_produces_passed_count(self):
        agg = run_result_to_aggregated_data(
            _RunResult(steps=[_Step(is_error=False)]), url='u', task='t',
        )
        count = agg['gen']['index']['aggregated_results']['count']
        assert count == {'total': 1, 'passed': 1, 'failed': 0, 'warning': 0}

    def test_failed_run_produces_failed_count(self):
        agg = run_result_to_aggregated_data(
            _RunResult(steps=[_Step(is_error=True)]), url='u', task='t',
        )
        count = agg['gen']['index']['aggregated_results']['count']
        assert count['failed'] == 1 and count['passed'] == 0

    def test_aborted_run_reported_as_failed(self):
        agg = run_result_to_aggregated_data(
            _RunResult(aborted=True), url='u', task='t',
        )
        case = next(v for k, v in agg['gen'].items() if k != 'index')
        assert case['status'] == 'failed'

    def test_steps_have_frontend_fields(self):
        rr = _RunResult(steps=[_Step(tool='navigate_page', input={'url': 'https://x'})])
        agg = run_result_to_aggregated_data(rr, url='u', task='t')
        case = next(v for k, v in agg['gen'].items() if k != 'index')
        step = case['steps'][0]
        # Fields the React step renderer looks up
        for key in ('id', 'number', 'type', 'description', 'screenshots',
                    'modelIO', 'actions', 'status', 'timestamp'):
            assert key in step, f'missing step field {key}'
        assert step['type'] == 'action'
        assert step['description'] == 'Navigate to https://x'
        assert step['actions'] and step['actions'][0]['success'] is True

    def test_failed_step_actions_marked_unsuccessful(self):
        rr = _RunResult(steps=[_Step(is_error=True, result='element missing')])
        agg = run_result_to_aggregated_data(rr, url='u', task='t')
        case = next(v for k, v in agg['gen'].items() if k != 'index')
        step = case['steps'][0]
        assert step['status'] == 'failed'
        assert step['actions'][0]['success'] is False
        assert step['errors'] == 'element missing'

    def test_summary_becomes_report_section(self):
        agg = run_result_to_aggregated_data(
            _RunResult(final_text='All good.'), url='u', task='t',
        )
        case = next(v for k, v in agg['gen'].items() if k != 'index')
        assert case['report'][0]['issues'] == 'All good.'

    def test_language_swaps_test_item_labels(self):
        agg_en = run_result_to_aggregated_data(
            _RunResult(steps=[_Step()]), url='u', task='t', language='en-US',
        )
        agg_zh = run_result_to_aggregated_data(
            _RunResult(steps=[_Step()]), url='u', task='t', language='zh-CN',
        )
        items_en = agg_en['gen']['index']['aggregated_results']['test_items']
        items_zh = agg_zh['gen']['index']['aggregated_results']['test_items']
        assert items_en[0]['name'] == 'Functional'
        assert items_zh[0]['name'] == '功能测试'


# ---------------------------------------------------------------------------
# Adapter fallback: empty description uses _describe_step on first tool_call
# ---------------------------------------------------------------------------

@dataclass
class _ToolCall:
    tool: str
    input: dict = field(default_factory=dict)
    result: str = 'ok'
    is_error: bool = False
    start_ts: float = 0.0
    end_ts: float = 0.0


@dataclass
class _StepWithToolCalls:
    """Mimics runner.Step with tool_calls list (new style)."""
    description: str = ''
    tool_calls: list = field(default_factory=list)
    screenshots: list = field(default_factory=list)
    timestamp: float = 0.0
    end_ts: float = 0.0
    input_tokens: int = 0
    output_tokens: int = 0
    is_error: bool = False


class TestAdapterDescriptionFallback:
    """Edit 2 (A.3): when description == '' and tool_calls exist,
    _map_step_dict must derive a description from the first tool_call via
    _describe_step."""

    def test_empty_description_falls_back_to_first_tool_navigate(self):
        step = _StepWithToolCalls(
            description='',
            tool_calls=[
                _ToolCall(
                    tool='mcp__browser__navigate_page',
                    input={'url': 'https://example.com'},
                ),
            ],
        )
        result = _map_step_dict(1, step)
        assert result['description'] == 'Navigate to https://example.com', (
            f'Fallback description wrong: {result["description"]!r}'
        )

    def test_empty_description_multiple_tool_calls_adds_suffix(self):
        step = _StepWithToolCalls(
            description='',
            tool_calls=[
                _ToolCall(
                    tool='mcp__browser__navigate_page',
                    input={'url': 'https://example.com'},
                ),
                _ToolCall(tool='mcp__browser__snapshot', input={}),
                _ToolCall(tool='mcp__browser__click', input={'selector': '#x'}),
            ],
        )
        result = _map_step_dict(1, step)
        assert result['description'] == 'Navigate to https://example.com (+2 more)', (
            f'Fallback with suffix wrong: {result["description"]!r}'
        )

    def test_non_empty_description_is_not_overwritten(self):
        step = _StepWithToolCalls(
            description='click the login button',
            tool_calls=[
                _ToolCall(
                    tool='mcp__browser__navigate_page',
                    input={'url': 'https://example.com'},
                ),
            ],
        )
        result = _map_step_dict(1, step)
        # Description must NOT be overwritten when already set
        assert result['description'] == 'click the login button', (
            f'Existing description should be preserved: {result["description"]!r}'
        )


# ---------------------------------------------------------------------------
# A1: _bare_tool_name helper
# ---------------------------------------------------------------------------

class TestBareToolName:
    def test_bare_tool_name_strips_mcp_prefix(self):
        assert _bare_tool_name('mcp__browser__click') == 'click'
        assert _bare_tool_name('navigate') == 'navigate'
        assert _bare_tool_name('') == ''

    def test_bare_tool_name_multi_segment(self):
        assert _bare_tool_name('mcp__browser__navigate_page') == 'navigate_page'

    def test_bare_tool_name_single_segment_no_change(self):
        assert _bare_tool_name('click') == 'click'

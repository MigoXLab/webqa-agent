"""Unit tests for the cc-mini event-loop dispatchers.

Tests cover:
  - Bug 1: 'waiting' must NOT backfill description onto the step that just
    finished (the description belongs to the UPCOMING step's tool calls).
  - Bug 2 revert: a trailing pure-text turn (no tool_calls) must be DROPPED —
    the final summary reaches the report via RunResult.final_text.
  - Regression: normal single-step flow still works.
  - Accumulation: consecutive no-text tool turns share one Step.
"""
from __future__ import annotations

import types

from webqa_agent.executor.flash.runner import (_EventLoopState,
                                               _finalize_steps, _handle_event)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_tool_result(content: str = 'ok', is_error: bool = False) -> types.SimpleNamespace:
    return types.SimpleNamespace(content=content, is_error=is_error, content_blocks=[])


def _drive(events: list[tuple], state: _EventLoopState | None = None) -> _EventLoopState:
    """Process a sequence of events through _handle_event and return state."""
    if state is None:
        state = _EventLoopState()
    for evt in events:
        _handle_event(evt, state)
    return state


# ---------------------------------------------------------------------------
# Bug 1: 'waiting' must NOT backfill description onto the previous step
# ---------------------------------------------------------------------------

class TestWaitingDoesNotBackfillPreviousStep:
    """Bug 1 regression: line 772 used _cur_step.description = _cur_step.description or description.

    Before the fix, the description from a 'waiting' event is retroactively
    written onto the step that just finished, making step[0].description ==
    step[1].description.  After the fix, step[0].description stays ''.
    """

    def test_waiting_does_not_backfill_previous_step_description(self):
        tr = _make_tool_result()
        events = [
            # Turn 1: tool_call + tool_result with NO preceding text
            ('tool_call', 'mcp__browser__navigate_page', {'url': 'https://example.com'}),
            ('tool_result', 'mcp__browser__navigate_page', None, tr),
            # Agent narrates for upcoming Turn 2 then waits
            ('text', 'click dropdown'),
            ('waiting',),
            # Turn 2: another tool_call
            ('tool_call', 'mcp__browser__click', {'selector': '#dropdown'}),
            ('tool_result', 'mcp__browser__click', None, tr),
        ]
        state = _drive(events)
        _finalize_steps(state)

        assert len(state.steps) == 2, f'Expected 2 steps, got {len(state.steps)}'
        step0, step1 = state.steps[0], state.steps[1]

        # Step 0 finished before "click dropdown" was emitted — it should have ''
        assert step0.description == '', (
            f'Bug 1: step[0].description should be empty string, got {step0.description!r}'
        )
        # Step 1 carries the narration that preceded its tool calls
        assert step1.description == 'click dropdown', (
            f'step[1].description should be "click dropdown", got {step1.description!r}'
        )
        # The two must differ
        assert step0.description != step1.description, (
            'Bug 1: step[0] and step[1] should have different descriptions'
        )

    def test_backfill_guard_for_text_before_first_turn(self):
        """Text before the very first tool_call also stays on step[0] only."""
        tr = _make_tool_result()
        events = [
            ('text', 'navigating to page'),
            ('waiting',),
            ('tool_call', 'mcp__browser__navigate_page', {'url': 'https://x.com'}),
            ('tool_result', 'mcp__browser__navigate_page', None, tr),
        ]
        state = _drive(events)
        _finalize_steps(state)

        assert len(state.steps) == 1
        assert state.steps[0].description == 'navigating to page'


# ---------------------------------------------------------------------------
# Trailing pure-text turn must be dropped — the summary already reaches the
# report via RunResult.final_text → case.final_summary (top "Summary" card).
# Including it as a Step would be duplicate content.
# ---------------------------------------------------------------------------

class TestTrailingTextOnlyTurnDropped:
    """Final-summary turn (text + waiting, no tools) is not added to
    ``state.steps`` — it is exposed via ``RunResult.final_text`` instead."""

    def test_trailing_text_only_turn_is_dropped(self):
        tr = _make_tool_result()
        events = [
            # Turn 1: a tool call
            ('tool_call', 'mcp__browser__navigate_page', {'url': 'https://example.com'}),
            ('tool_result', 'mcp__browser__navigate_page', None, tr),
            # Agent emits final summary text and waits, then no more tools
            ('text', '**Status**: passed'),
            ('waiting',),
        ]
        state = _drive(events)
        _finalize_steps(state)

        assert len(state.steps) == 1, (
            f'Trailing summary step must be dropped (it surfaces via '
            f'RunResult.final_text instead); got {len(state.steps)} steps'
        )
        assert state.steps[0].tool_calls, 'the surviving step is the tool-calls one'
        # The summary text still lives on state.cur_step (unflushed); the
        # outer run_cc_mini ignores it because final_summary is sourced from
        # engine.last_assistant_text() at RunResult construction time.
        assert state.cur_step is not None
        assert state.cur_step.description == '**Status**: passed'

    def test_empty_text_trailing_step_is_dropped(self):
        """A trailing step with neither tool_calls nor description is
        discarded."""
        tr = _make_tool_result()
        events = [
            ('tool_call', 'mcp__browser__navigate_page', {'url': 'https://example.com'}),
            ('tool_result', 'mcp__browser__navigate_page', None, tr),
            # Waiting with empty text buffer — no description, no tools
            ('waiting',),
        ]
        state = _drive(events)
        _finalize_steps(state)

        # The trailing empty step (description='', tool_calls=[]) must be dropped
        assert len(state.steps) == 1, (
            f'Empty trailing step should be discarded, got {len(state.steps)} steps'
        )


# ---------------------------------------------------------------------------
# Regression: normal single-step still works
# ---------------------------------------------------------------------------

class TestNormalSingleStep:
    def test_normal_single_step_still_works(self):
        tr = _make_tool_result(content='navigated ok')
        events = [
            ('text', 'navigating to the target URL'),
            ('waiting',),
            ('tool_call', 'mcp__browser__navigate_page', {'url': 'https://x.com'}),
            ('tool_result', 'mcp__browser__navigate_page', None, tr),
        ]
        state = _drive(events)
        _finalize_steps(state)

        assert len(state.steps) == 1
        step = state.steps[0]
        assert step.description == 'navigating to the target URL'
        assert len(step.tool_calls) == 1
        assert step.tool_calls[0].tool == 'mcp__browser__navigate_page'
        assert step.tool_calls[0].result == 'navigated ok'


# ---------------------------------------------------------------------------
# Accumulation: multiple tool calls in one turn share a single Step
# ---------------------------------------------------------------------------

class TestMultiToolCallsAccumulateInOneStep:
    def test_no_text_turns_accumulate_into_one_step(self):
        """Two consecutive tool_call/tool_result pairs without a 'waiting'
        between them should both land in the same Step object."""
        tr = _make_tool_result()
        events = [
            ('tool_call', 'mcp__browser__navigate_page', {'url': 'https://x.com'}),
            ('tool_result', 'mcp__browser__navigate_page', None, tr),
            ('tool_call', 'mcp__browser__snapshot', {}),
            ('tool_result', 'mcp__browser__snapshot', None, tr),
        ]
        state = _drive(events)
        _finalize_steps(state)

        # Both tool_calls land on the same (only) step
        assert len(state.steps) == 1, (
            f'Expected 1 step (both calls in same turn), got {len(state.steps)}'
        )
        assert len(state.steps[0].tool_calls) == 2


# ---------------------------------------------------------------------------
# Critical bug: AbortedError mid-loop must preserve accumulated steps
# ---------------------------------------------------------------------------

class TestAbortedRunPreservesSteps:
    """Critical bug regression: the except AbortedError handler referenced
    a stale outer 'steps = []' that the event loop never mutated (the loop
    mutates state.steps only, with a post-loop bridge that is skipped on abort).
    """

    def test_aborted_run_preserves_accumulated_steps(self, monkeypatch, tmp_path):
        """When the engine aborts mid-loop, partial steps and metrics must
        survive into RunResult via the except handler."""
        from types import SimpleNamespace

        from webqa_agent.executor.flash.core.engine import AbortedError
        from webqa_agent.executor.flash.runner import run_cc_mini  # noqa: F401

        class FakeMCP:
            _servers: dict = {}

            def __init__(self, *args, **kwargs):
                self._servers = {}

            def start_and_collect_tools(self):
                return []

            def shutdown_all(self):
                pass

        class FakeEngine:
            def __init__(self, *args, **kwargs):
                self._client = SimpleNamespace()
                self._aborted_flag = False
                self.system_prompt = ''

            def submit(self, seed):
                # Yield a tool_call + tool_result pair so a step is built.
                yield ('tool_call', 'mcp__browser__navigate_page', {'url': 'http://x'}, None)
                yield ('tool_result', 'mcp__browser__navigate_page', {'url': 'http://x'},
                       SimpleNamespace(content='ok', is_error=False, content_blocks=[]))
                # Then abort mid-stream.
                raise AbortedError()

            def last_assistant_text(self):
                return ''

            def set_context_overflow_handler(self, handler):
                pass

            def abort(self):
                self._aborted_flag = True

            def get_messages(self):
                return []

            def get_model(self):
                return 'fake-model'

            def set_messages(self, msgs):
                pass

        class FakeCompact:
            def __init__(self, *args, **kwargs):
                pass

            def compact(self, messages, system_prompt):
                return messages, None

        monkeypatch.setattr('webqa_agent.executor.flash.runner.MCPManager', FakeMCP)
        monkeypatch.setattr('webqa_agent.executor.flash.runner.Engine', FakeEngine)
        monkeypatch.setattr('webqa_agent.executor.flash.runner.CompactService', FakeCompact)
        monkeypatch.setattr('webqa_agent.executor.flash.runner.should_compact', lambda *a, **kw: False)
        monkeypatch.setattr('webqa_agent.executor.flash.runner.signal.signal', lambda s, h: None)

        result = run_cc_mini(
            url='http://x',
            user_input='t',
            api_key='fake',
            model='gpt-4o-mini',
            provider='openai',
            enable_display_progress=False,
        )

        assert result.aborted is True, 'aborted flag must be set'
        assert len(result.steps) >= 1, (
            'partial steps must survive an abort; was the except handler '
            'referencing the stale outer steps=[]?'
        )
        assert result.steps[0].tool_calls, 'the surviving step should have its tool_call'

"""Tests for post-action screenshot hash comparison in the engine."""
from __future__ import annotations

from webqa_agent.executor.flash.core.engine import (Engine,
                                                    _screenshot_content_hash)
from webqa_agent.executor.flash.core.tool import ToolResult


class TestScreenshotContentHash:
    def test_returns_md5_for_image_block(self):
        result = ToolResult(
            content='Took a screenshot',
            content_blocks=[{
                'type': 'image',
                'data': 'iVBORw0KGgoAAAANSUhEUg==',
                'mimeType': 'image/png',
            }],
        )
        h = _screenshot_content_hash(result)
        assert h is not None
        assert len(h) == 32

    def test_returns_none_for_no_image(self):
        result = ToolResult(content='Some text', content_blocks=[])
        assert _screenshot_content_hash(result) is None

    def test_returns_none_for_text_only_blocks(self):
        result = ToolResult(
            content='text',
            content_blocks=[{'type': 'text', 'text': 'hello'}],
        )
        assert _screenshot_content_hash(result) is None

    def test_returns_none_for_empty_data(self):
        result = ToolResult(
            content='screenshot',
            content_blocks=[{'type': 'image', 'data': '', 'mimeType': 'image/png'}],
        )
        assert _screenshot_content_hash(result) is None

    def test_same_data_same_hash(self):
        blocks = [{'type': 'image', 'data': 'AAAA', 'mimeType': 'image/png'}]
        r1 = ToolResult(content='a', content_blocks=list(blocks))
        r2 = ToolResult(content='b', content_blocks=list(blocks))
        assert _screenshot_content_hash(r1) == _screenshot_content_hash(r2)

    def test_different_data_different_hash(self):
        r1 = ToolResult(
            content='a',
            content_blocks=[{'type': 'image', 'data': 'AAAA', 'mimeType': 'image/png'}],
        )
        r2 = ToolResult(
            content='b',
            content_blocks=[{'type': 'image', 'data': 'BBBB', 'mimeType': 'image/png'}],
        )
        assert _screenshot_content_hash(r1) != _screenshot_content_hash(r2)

    def test_uses_first_image_block(self):
        result = ToolResult(
            content='multi',
            content_blocks=[
                {'type': 'image', 'data': 'FIRST', 'mimeType': 'image/png'},
                {'type': 'image', 'data': 'SECOND', 'mimeType': 'image/png'},
            ],
        )
        h = _screenshot_content_hash(result)
        single = ToolResult(
            content='single',
            content_blocks=[{'type': 'image', 'data': 'FIRST', 'mimeType': 'image/png'}],
        )
        assert h == _screenshot_content_hash(single)


class TestFailureCounter:
    """Tests for _update_failure_counter — consecutive failure tracking."""

    def _make_engine(self):
        from unittest.mock import MagicMock
        return Engine(
            tools=[],
            system_prompt='test',
            permission_checker=MagicMock(),
        )

    def _error_result(self):
        return {
            'type': 'tool_result',
            'tool_use_id': 'test',
            'content': 'Tool error: timeout',
            'is_error': True,
        }

    def _ok_result(self):
        return {
            'type': 'tool_result',
            'tool_use_id': 'test',
            'content': (
                'Took a screenshot\n'
                '[post-action observation: page visual state '
                'changed since previous screenshot]'
            ),
            'is_error': False,
        }

    def test_counter_increments_on_error(self):
        e = self._make_engine()
        results = [self._error_result()]
        e._update_failure_counter(results, turn_has_mutation=True)
        assert e._consecutive_failures == 1

    def test_counter_increments_on_unchanged_visual(self):
        e = self._make_engine()
        e._turn_visual_state = 'unchanged'
        results = [self._ok_result()]
        e._update_failure_counter(results, turn_has_mutation=True)
        assert e._consecutive_failures == 1

    def test_counter_resets_on_changed_visual(self):
        e = self._make_engine()
        e._consecutive_failures = 2
        e._turn_visual_state = 'changed'
        results = [self._ok_result()]
        e._update_failure_counter(results, turn_has_mutation=True)
        assert e._consecutive_failures == 0

    def test_no_signal_below_threshold(self):
        e = self._make_engine()
        results = [self._error_result()]
        e._update_failure_counter(results, turn_has_mutation=True)
        e._update_failure_counter(results, turn_has_mutation=True)
        assert e._consecutive_failures == 2
        assert len(results) == 1

    def test_signal_appended_at_threshold(self):
        e = self._make_engine()
        e._consecutive_failures = 2
        results = [self._error_result()]
        e._update_failure_counter(results, turn_has_mutation=True)
        assert e._consecutive_failures == 3
        assert len(results) == 1
        assert 'consecutive failure #3' in results[0]['content']
        assert 'not working' in results[0]['content']

    def test_signal_continues_above_threshold(self):
        e = self._make_engine()
        e._consecutive_failures = 4
        e._turn_visual_state = 'unchanged'
        results = [self._ok_result()]
        e._update_failure_counter(results, turn_has_mutation=True)
        assert e._consecutive_failures == 5
        assert 'consecutive failure #5' in results[0]['content']

    def test_non_mutating_turn_ignored(self):
        e = self._make_engine()
        results = [self._error_result()]
        e._update_failure_counter(results, turn_has_mutation=False)
        assert e._consecutive_failures == 0

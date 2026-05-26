from __future__ import annotations

import copy
from typing import Any
from unittest.mock import patch

from webqa_agent.executor.flash.core.engine import Engine, _strip_old_images
from webqa_agent.executor.flash.core.llm import LLMMessage
from webqa_agent.executor.flash.core.permissions import PermissionChecker
from webqa_agent.executor.flash.core.tool import Tool, ToolResult


class _ScreenshotTool(Tool):
    def __init__(self) -> None:
        self.calls = 0

    @property
    def name(self) -> str:
        return 'mcp__browser__take_screenshot'

    @property
    def description(self) -> str:
        return 'take screenshot'

    @property
    def input_schema(self) -> dict:
        return {'type': 'object', 'properties': {}}

    def execute(self, **kwargs: Any) -> ToolResult:
        self.calls += 1
        return ToolResult(
            content=f'screenshot {self.calls}',
            is_error=False,
            content_blocks=[{
                'type': 'image',
                'mimeType': 'image/jpeg',
                'data': f'image-data-{self.calls}',
            }],
        )


class _FakeStream:
    def __init__(self, content: list[dict[str, Any]], text: str = '') -> None:
        self._message = LLMMessage(content=content)
        self.text_stream = iter([text] if text else [])

    def __enter__(self) -> '_FakeStream':
        return self

    def __exit__(self, exc_type: Any, exc: Any, tb: Any) -> bool:
        return False

    def close(self) -> None:
        return None

    def get_final_message(self) -> LLMMessage:
        return self._message


def _tool_result_with_image(
    tool_use_id: str,
    data: str,
    *,
    is_error: bool = False,
) -> dict[str, Any]:
    return {
        'type': 'tool_result',
        'tool_use_id': tool_use_id,
        'content': [
            {'type': 'text', 'text': f'screenshot result {tool_use_id}'},
            {
                'type': 'image',
                'source': {
                    'type': 'base64',
                    'media_type': 'image/jpeg',
                    'data': data,
                },
            },
        ],
        'is_error': is_error,
    }


def test_strip_old_images_keeps_latest_image_and_preserves_tool_result_shape() -> None:
    messages = [
        {
            'role': 'user',
            'content': [_tool_result_with_image('shot_1', 'a' * 10, is_error=True)],
        },
        {
            'role': 'user',
            'content': [_tool_result_with_image('shot_2', 'b' * 20)],
        },
    ]

    _strip_old_images(messages, keep_recent=1)

    old_block = messages[0]['content'][0]
    new_block = messages[1]['content'][0]

    assert old_block['type'] == 'tool_result'
    assert old_block['tool_use_id'] == 'shot_1'
    assert old_block['is_error'] is True
    assert all(part.get('type') != 'image' for part in old_block['content'])
    assert any(
        'tool_use_id=shot_1' in part.get('text', '')
        and 'image_1_media_type=image/jpeg' in part.get('text', '')
        and 'image_1_base64_chars=10' in part.get('text', '')
        for part in old_block['content']
    )
    assert any(part.get('type') == 'image' for part in new_block['content'])


def test_strip_old_images_is_idempotent() -> None:
    messages = [
        {'role': 'user', 'content': [_tool_result_with_image('shot_1', 'a' * 10)]},
        {'role': 'user', 'content': [_tool_result_with_image('shot_2', 'b' * 20)]},
    ]

    _strip_old_images(messages, keep_recent=1)
    once = copy.deepcopy(messages)
    _strip_old_images(messages, keep_recent=1)

    assert messages == once


def test_engine_strips_consumed_images_before_each_follow_up_llm_call() -> None:
    tool = _ScreenshotTool()
    engine = Engine(
        tools=[tool],
        system_prompt='system',
        permission_checker=PermissionChecker(),
        api_key='test-key',
    )
    streams = [
        _FakeStream([{
            'type': 'tool_use',
            'id': 'shot_1',
            'name': 'mcp__browser__take_screenshot',
            'input': {},
        }]),
        _FakeStream([{
            'type': 'tool_use',
            'id': 'shot_2',
            'name': 'mcp__browser__take_screenshot',
            'input': {},
        }]),
        _FakeStream([{'type': 'text', 'text': 'done'}], text='done'),
    ]

    with patch.object(engine._client, 'stream_messages', side_effect=streams) as stream:
        list(engine.submit('take two screenshots'))

    third_call_messages = stream.call_args_list[2].kwargs['messages']
    tool_result_messages = [
        msg for msg in third_call_messages
        if msg.get('role') == 'user' and isinstance(msg.get('content'), list)
    ]
    first_result = tool_result_messages[0]['content'][0]
    second_result = tool_result_messages[1]['content'][0]

    assert all(part.get('type') != 'image' for part in first_result['content'])
    assert any('tool_use_id=shot_1' in part.get('text', '') for part in first_result['content'])
    assert any(part.get('type') == 'image' for part in second_result['content'])

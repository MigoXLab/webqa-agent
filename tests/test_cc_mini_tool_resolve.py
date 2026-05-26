"""Tests for the engine's tool-name fallback resolution.

When the LLM calls a native tool (e.g. ``wait_for_dom_stable``) using the
MCP-prefixed form (``mcp__browser__wait_for_dom_stable``), the engine should
strip the prefix and resolve to the correct tool rather than returning
'Unknown tool' — which wastes an LLM turn on every such call.
"""
from __future__ import annotations

from webqa_agent.executor.flash.core.engine import Engine
from webqa_agent.executor.flash.core.permissions import PermissionChecker
from webqa_agent.executor.flash.core.tool import Tool, ToolResult


class _StubTool(Tool):
    """Minimal concrete Tool for testing."""

    def __init__(self, name: str) -> None:
        self._name = name

    @property
    def name(self) -> str:
        return self._name

    @property
    def description(self) -> str:
        return 'stub'

    @property
    def input_schema(self) -> dict:
        return {'type': 'object', 'properties': {}}

    def execute(self, **kwargs: object) -> ToolResult:
        return ToolResult(content='ok')


def _make_engine(*tool_names: str) -> Engine:
    tools = [_StubTool(n) for n in tool_names]
    return Engine(
        tools=tools,
        system_prompt='test',
        permission_checker=PermissionChecker(),
        provider='openai',
        model='gpt-4o-mini',
        api_key='fake-key',
    )


def _tool_use(name: str, **kwargs: object) -> dict:
    return {'type': 'tool_use', 'id': 'tu_1', 'name': name, 'input': kwargs}


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestToolNameFallback:
    """LLM-issued MCP-prefixed names for native tools should resolve by
    stripping the prefix."""

    def test_exact_name_resolves_normally(self) -> None:
        engine = _make_engine('wait_for_dom_stable')
        result = engine._execute_tool(_tool_use('wait_for_dom_stable'))
        assert not result.is_error
        assert result.content == 'ok'

    def test_mcp_prefixed_name_resolves_via_fallback(self) -> None:
        engine = _make_engine('wait_for_dom_stable')
        result = engine._execute_tool(
            _tool_use('mcp__browser__wait_for_dom_stable'),
        )
        assert not result.is_error, (
            f'Expected fallback resolution, got error: {result.content}'
        )
        assert 'ok' in result.content

    def test_fallback_result_contains_correction_note(self) -> None:
        engine = _make_engine('wait_for_dom_stable')
        result = engine._execute_tool(
            _tool_use('mcp__browser__wait_for_dom_stable'),
        )
        assert not result.is_error
        assert 'resolved' in result.content.lower(), (
            f'Expected a correction note with "resolved"; got: {result.content!r}'
        )

    def test_genuinely_unknown_tool_still_errors(self) -> None:
        engine = _make_engine('wait_for_dom_stable')
        result = engine._execute_tool(_tool_use('nonexistent_tool'))
        assert result.is_error
        assert 'Unknown tool' in result.content

    def test_mcp_prefixed_unknown_still_errors(self) -> None:
        engine = _make_engine('wait_for_dom_stable')
        result = engine._execute_tool(
            _tool_use('mcp__browser__nonexistent'),
        )
        assert result.is_error
        assert 'Unknown tool' in result.content

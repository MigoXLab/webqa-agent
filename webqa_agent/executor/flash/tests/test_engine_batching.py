"""Concurrency-batch behaviour after the heavy-tool isolation fix.

Verifies that:

* heavy MCP read-only tools (chrome-devtools-mcp ``take_snapshot`` /
  ``take_screenshot``) are flagged ``concurrent_safe = False`` so the engine
  keeps them in singleton sequential batches instead of fanning them out
  alongside cheap reads — the original "5 read-only tools timeout at 60s
  simultaneously" failure mode.
* Stateful read-only native tools (``DownloadCheckTool``) carry the same
  flag at class scope.
* The engine's ``ThreadPoolExecutor`` cap matches ``_MAX_CONCURRENT_TOOLS``
  rather than the legacy hard-coded 10.
* The same-named tool on a non-``browser`` MCP server is NOT downgraded
  (server-name-scoped heavy classification).
"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor as _RealThreadPoolExecutor
from pathlib import Path
from typing import Any
from unittest.mock import patch

from webqa_agent.executor.flash.core.engine import (
    _MAX_CONCURRENT_TOOLS, _WAIT_FOR_DEFAULT_TIMEOUT_MS,
    _WAIT_FOR_MAX_TIMEOUT_MS, Engine)
from webqa_agent.executor.flash.core.llm import LLMMessage
from webqa_agent.executor.flash.core.mcp_client import MCPServer, MCPTool
from webqa_agent.executor.flash.core.permissions import PermissionChecker
from webqa_agent.executor.flash.core.tool import Tool, ToolResult
from webqa_agent.executor.flash.tools.download_tool import DownloadCheckTool
from webqa_agent.executor.flash.tools.verify_tool import VerifyTool

# --------------------------------------------------------------------------- helpers


def _make_mcp_tool(server_name: str, tool_name: str, *, read_only_hint: bool | None = None) -> MCPTool:
    """Construct an MCPTool without spawning a real subprocess.

    MCPServer's __init__ does not start the process; that only happens via
    ``start()``.  We just need ``server.name`` for the heavy classification.
    """
    server = MCPServer(name=server_name, command='/bin/true')
    annotations: dict[str, Any] = {}
    if read_only_hint is not None:
        annotations['readOnlyHint'] = read_only_hint
    spec = {
        'name': tool_name,
        'description': f'fake {tool_name}',
        'inputSchema': {'type': 'object', 'properties': {}},
        'annotations': annotations,
    }
    return MCPTool(server, spec)


class _FakeStream:
    def __init__(self, content: list[dict[str, Any]], text: str = '') -> None:
        self._message = LLMMessage(content=content)
        self.text_stream = iter([text] if text else [])

    def __enter__(self) -> '_FakeStream':
        return self

    def __exit__(self, *_args: Any) -> bool:
        return False

    def close(self) -> None:
        return None

    def get_final_message(self) -> LLMMessage:
        return self._message


class _ImmediateTool(Tool):
    """Read-only tool that returns instantly; engine partitioner only reads
    ``concurrent_safe``, not the body."""

    def __init__(self, tool_name: str, *, concurrent_safe: bool = True) -> None:
        self._tool_name = tool_name
        self.concurrent_safe = concurrent_safe
        self.calls = 0

    @property
    def name(self) -> str:
        return self._tool_name

    @property
    def description(self) -> str:
        return f'fake {self._tool_name}'

    @property
    def input_schema(self) -> dict:
        return {'type': 'object', 'properties': {}}

    def is_read_only(self) -> bool:
        return True

    def execute(self, **_kwargs: Any) -> ToolResult:
        self.calls += 1
        return ToolResult(content=f'{self._tool_name}#{self.calls}')


def _tool_use(tool_id: str, tool_name: str) -> dict[str, Any]:
    return {
        'type': 'tool_use',
        'id': tool_id,
        'name': tool_name,
        'input': {},
    }


# --------------------------------------------------------------------------- classification


def test_tool_base_class_default_concurrent_safe_is_true() -> None:
    class _T(Tool):
        @property
        def name(self) -> str:
            return 'x'

        @property
        def description(self) -> str:
            return ''

        @property
        def input_schema(self) -> dict:
            return {}

        def execute(self, **_kwargs: Any) -> ToolResult:
            return ToolResult(content='')

    assert _T.concurrent_safe is True
    assert _T().concurrent_safe is True


def test_download_check_tool_is_not_concurrent_safe(tmp_path: Path) -> None:
    """Stateful read-only tool must opt out at class scope."""
    assert DownloadCheckTool.concurrent_safe is False
    instance = DownloadCheckTool(tmp_path)
    assert instance.concurrent_safe is False
    # The original read-only contract is unchanged — only the concurrency flag flips.
    assert instance.is_read_only() is True


def test_mcp_tool_heavy_browser_tools_are_not_concurrent_safe() -> None:
    snapshot = _make_mcp_tool('browser', 'take_snapshot')
    screenshot = _make_mcp_tool('browser', 'take_screenshot')
    assert snapshot.is_read_only() is True
    assert screenshot.is_read_only() is True
    assert snapshot.concurrent_safe is False
    assert screenshot.concurrent_safe is False


def test_mcp_tool_cheap_browser_reads_remain_concurrent_safe() -> None:
    for name in ('list_console_messages', 'list_network_requests', 'list_pages'):
        tool = _make_mcp_tool('browser', name)
        assert tool.is_read_only() is True, name
        assert tool.concurrent_safe is True, name


def test_mcp_tool_non_read_only_is_not_concurrent_safe() -> None:
    """``readOnlyHint=False`` and a non-read-only name → both flags False."""
    tool = _make_mcp_tool('browser', 'navigate_page', read_only_hint=False)
    assert tool.is_read_only() is False
    assert tool.concurrent_safe is False


def test_mcp_tool_explicit_read_only_hint_false_is_honoured() -> None:
    """Regression guard: a tool with a heuristic-matching name (`get_*`,
    `list_*`, etc.) but an explicit ``readOnlyHint=False`` from the server
    must be treated as mutating — the name heuristic only fires when the
    hint is omitted entirely.  Otherwise hybrid names like
    ``get_and_clear_cache`` get fanned out alongside real reads."""
    tool = _make_mcp_tool('browser', 'get_and_clear_cache', read_only_hint=False)
    assert tool.is_read_only() is False
    assert tool.concurrent_safe is False


def test_mcp_tool_heuristic_only_applies_when_hint_omitted() -> None:
    """Counterpart: when ``readOnlyHint`` is genuinely missing (None), the
    heuristic still infers read-only from the name — preserving the
    pre-existing behaviour for chrome-devtools-mcp / playwright-mcp which
    rarely set the annotation at all."""
    tool = _make_mcp_tool('browser', 'list_console_messages')  # no hint
    assert tool.is_read_only() is True
    assert tool.concurrent_safe is True


def test_mcp_tool_heavy_classification_is_server_scoped() -> None:
    """Same tool name on a different MCP server is not auto-downgraded."""
    other = _make_mcp_tool('analytics', 'take_screenshot')
    assert other.is_read_only() is True
    assert other.concurrent_safe is True


# --------------------------------------------------------------------------- engine batching


def _engine_with_tools(tools: list[Tool]) -> Engine:
    return Engine(
        tools=tools,
        system_prompt='system',
        permission_checker=PermissionChecker(),
        api_key='fake-key',
    )


def _drive_engine(engine: Engine, tool_uses: list[dict[str, Any]]) -> list[tuple]:
    """Run one assistant turn that emits ``tool_uses``, then a second turn that
    finishes with text — captures every event."""
    streams = [
        _FakeStream(tool_uses),
        _FakeStream([{'type': 'text', 'text': 'done'}], text='done'),
    ]
    with patch.object(engine._client, 'stream_messages', side_effect=streams):
        return list(engine.submit('seed'))


def test_heavy_tool_runs_in_singleton_sequential_batch() -> None:
    """Two consecutive ``take_snapshot`` calls must NOT be batched together
    (heavy ⇒ ``concurrent_safe=False``); each gets its own sequential batch.

    The signature is: no ThreadPoolExecutor is constructed at all because no
    batch satisfies ``is_concurrent and len(batch) > 1``.
    """
    snapshot_tool = _ImmediateTool('mcp__browser__take_snapshot', concurrent_safe=False)
    list_tool = _ImmediateTool('mcp__browser__list_console_messages', concurrent_safe=True)
    engine = _engine_with_tools([snapshot_tool, list_tool])

    pool_calls: list[int] = []

    class _RecordingPool(_RealThreadPoolExecutor):
        def __init__(self, *args: Any, max_workers: int | None = None, **kwargs: Any) -> None:
            pool_calls.append(int(max_workers or 0))
            super().__init__(*args, max_workers=max_workers, **kwargs)

    with patch('webqa_agent.executor.flash.core.engine.ThreadPoolExecutor', _RecordingPool):
        _drive_engine(engine, [
            _tool_use('s1', 'mcp__browser__take_snapshot'),
            _tool_use('s2', 'mcp__browser__take_snapshot'),
        ])

    # Both snapshots executed sequentially; pool never used.
    assert pool_calls == []
    assert snapshot_tool.calls == 2


def test_concurrent_batch_caps_max_workers_at_three() -> None:
    """Five cheap reads in one turn → exactly one parallel batch of width 3
    (was 5 under the old ``min(N, 10)`` rule)."""
    cheap = _ImmediateTool('mcp__browser__list_console_messages', concurrent_safe=True)
    engine = _engine_with_tools([cheap])

    pool_calls: list[int] = []

    class _RecordingPool(_RealThreadPoolExecutor):
        def __init__(self, *args: Any, max_workers: int | None = None, **kwargs: Any) -> None:
            pool_calls.append(int(max_workers or 0))
            super().__init__(*args, max_workers=max_workers, **kwargs)

    with patch('webqa_agent.executor.flash.core.engine.ThreadPoolExecutor', _RecordingPool):
        _drive_engine(engine, [
            _tool_use(f'c{i}', 'mcp__browser__list_console_messages')
            for i in range(5)
        ])

    assert pool_calls == [_MAX_CONCURRENT_TOOLS]
    assert _MAX_CONCURRENT_TOOLS == 3
    assert cheap.calls == 5


def test_heavy_and_cheap_mix_isolates_heavy_then_parallelises_cheap() -> None:
    """Original observed failure: ``[take_screenshot, list_console_messages,
    list_network_requests, take_screenshot, take_snapshot]`` all fanned out
    and timed out together.  After the fix the heavy ones are isolated and
    only the two cheap reads share a parallel batch (width=2)."""
    screenshot = _ImmediateTool('mcp__browser__take_screenshot', concurrent_safe=False)
    snapshot = _ImmediateTool('mcp__browser__take_snapshot', concurrent_safe=False)
    console = _ImmediateTool('mcp__browser__list_console_messages', concurrent_safe=True)
    network = _ImmediateTool('mcp__browser__list_network_requests', concurrent_safe=True)
    engine = _engine_with_tools([screenshot, snapshot, console, network])

    pool_calls: list[int] = []

    class _RecordingPool(_RealThreadPoolExecutor):
        def __init__(self, *args: Any, max_workers: int | None = None, **kwargs: Any) -> None:
            pool_calls.append(int(max_workers or 0))
            super().__init__(*args, max_workers=max_workers, **kwargs)

    with patch('webqa_agent.executor.flash.core.engine.ThreadPoolExecutor', _RecordingPool):
        _drive_engine(engine, [
            _tool_use('a', 'mcp__browser__take_screenshot'),
            _tool_use('b', 'mcp__browser__list_console_messages'),
            _tool_use('c', 'mcp__browser__list_network_requests'),
            _tool_use('d', 'mcp__browser__take_screenshot'),
            _tool_use('e', 'mcp__browser__take_snapshot'),
        ])

    # The two cheap reads land in one parallel batch of width 2; everything
    # else runs in singleton sequential batches (no pool).
    assert pool_calls == [2]
    assert screenshot.calls == 2
    assert snapshot.calls == 1
    assert console.calls == 1
    assert network.calls == 1


def test_mutating_native_tool_inheriting_default_concurrent_safe_runs_sequentially() -> None:
    """Regression guard for the read-only gate: a non-read-only native tool
    that simply inherits the base class default ``concurrent_safe = True``
    must NOT enter the parallel batch.  Before the gate was added, removing
    the ``is_read_only()`` check meant Nuclei scans and switch_account would
    have been silently fanned out across the same browser session."""
    mutating = _ImmediateTool('mcp__browser__click', concurrent_safe=True)
    # is_read_only defaults to True on _ImmediateTool — flip it to model a
    # mutating native tool (NucleiScanTool / SwitchAccountTool).
    mutating.is_read_only = lambda: False  # type: ignore[method-assign]

    engine = _engine_with_tools([mutating])

    pool_calls: list[int] = []

    class _RecordingPool(_RealThreadPoolExecutor):
        def __init__(self, *args: Any, max_workers: int | None = None, **kwargs: Any) -> None:
            pool_calls.append(int(max_workers or 0))
            super().__init__(*args, max_workers=max_workers, **kwargs)

    with patch('webqa_agent.executor.flash.core.engine.ThreadPoolExecutor', _RecordingPool):
        _drive_engine(engine, [
            _tool_use('m1', 'mcp__browser__click'),
            _tool_use('m2', 'mcp__browser__click'),
        ])

    # Both calls run sequentially; no concurrent batch ever opens.
    assert pool_calls == []
    assert mutating.calls == 2


def test_verify_tool_is_not_concurrent_safe() -> None:
    """VerifyTool is read-only by contract but its execute() internally calls
    take_snapshot + take_screenshot, so running it in a parallel batch with
    sibling reads queues everything on the same renderer thread.

    Class-level flag, no instance construction needed.
    """
    assert VerifyTool.concurrent_safe is False


# --------------------------------------------------------------------------- wait_for clamp


class _WaitForCapturingTool(Tool):
    """Stand-in for ``mcp__browser__wait_for`` that records the kwargs it
    receives.

    Lets us assert what the engine actually forwarded after the clamp ran,
    without spinning up chrome-devtools-mcp.
    """

    concurrent_safe = False  # match real wait_for: mutating-ish, never batched

    def __init__(self) -> None:
        self.captured_inputs: list[dict[str, Any]] = []

    @property
    def name(self) -> str:
        return 'mcp__browser__wait_for'

    @property
    def description(self) -> str:
        return 'fake wait_for'

    @property
    def input_schema(self) -> dict:
        return {'type': 'object', 'properties': {}}

    def is_read_only(self) -> bool:
        return False

    def execute(self, **kwargs: Any) -> ToolResult:
        self.captured_inputs.append(dict(kwargs))
        return ToolResult(content='ok')


def _wait_for_tool_use(timeout: Any) -> dict[str, Any]:
    return {
        'type': 'tool_use',
        'id': 'w1',
        'name': 'mcp__browser__wait_for',
        'input': {'text': 'Loaded', 'timeout': timeout},
    }


def test_wait_for_clamp_zero_falls_back_to_default() -> None:
    """Chrome-devtools-mcp treats ``timeout=0`` as "use server default", which
    lets an unmet condition stall the renderer past our outer 60s call timeout.

    The clamp replaces 0 with the short default so the renderer is released
    long before the outer clock fires.
    """
    wait_tool = _WaitForCapturingTool()
    engine = _engine_with_tools([wait_tool])

    _drive_engine(engine, [_wait_for_tool_use(timeout=0)])

    assert wait_tool.captured_inputs == [
        {'text': 'Loaded', 'timeout': _WAIT_FOR_DEFAULT_TIMEOUT_MS},
    ]


def test_wait_for_clamp_over_max_is_capped() -> None:
    """Anything above ``_WAIT_FOR_MAX_TIMEOUT_MS`` is capped so the cdm retry
    tail plus the cancel/response round-trip on stdio still has headroom before
    the outer ``_DEFAULT_CALL_TIMEOUT`` fires.

    The cap also bounds wasted wait time when the requested text never matches
    (icon buttons, shadow DOM, dynamic labels).
    """
    wait_tool = _WaitForCapturingTool()
    engine = _engine_with_tools([wait_tool])

    _drive_engine(engine, [_wait_for_tool_use(timeout=60_000)])

    assert wait_tool.captured_inputs == [
        {'text': 'Loaded', 'timeout': _WAIT_FOR_MAX_TIMEOUT_MS},
    ]


def test_wait_for_clamp_within_range_is_preserved() -> None:
    """Regression guard: a request that fits within the bound passes
    through untouched.  Uses 25s to stay safely below the 30s defensive
    ceiling while still exceeding the default 8s fallback — this is the
    core ``preserve user intent within range`` invariant."""
    wait_tool = _WaitForCapturingTool()
    engine = _engine_with_tools([wait_tool])

    _drive_engine(engine, [_wait_for_tool_use(timeout=25_000)])

    assert wait_tool.captured_inputs == [
        {'text': 'Loaded', 'timeout': 25_000},
    ]


def test_stateful_read_only_tool_runs_sequentially(tmp_path: Path) -> None:
    """``DownloadCheckTool`` is read-only but stateful; even when its own
    invocations would otherwise be co-batched with cheap reads, it must drop
    into sequential mode."""
    download = DownloadCheckTool(tmp_path)
    cheap = _ImmediateTool('mcp__browser__list_console_messages', concurrent_safe=True)
    engine = _engine_with_tools([download, cheap])

    pool_calls: list[int] = []

    class _RecordingPool(_RealThreadPoolExecutor):
        def __init__(self, *args: Any, max_workers: int | None = None, **kwargs: Any) -> None:
            pool_calls.append(int(max_workers or 0))
            super().__init__(*args, max_workers=max_workers, **kwargs)

    with patch('webqa_agent.executor.flash.core.engine.ThreadPoolExecutor', _RecordingPool):
        _drive_engine(engine, [
            _tool_use('d1', 'check_download'),
            _tool_use('d2', 'check_download'),
        ])

    # Both download calls run sequentially; pool never created.
    assert pool_calls == []

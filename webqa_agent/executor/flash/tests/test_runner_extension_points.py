"""Tests for runner.py's generic extension points.

Covers the changes introduced in the cookie-injection plan PR-1:

* [o1] worker_id upper-bound validation
* force-start uses ``list_pages`` (read-only, no extra tab) rather than
  ``new_page`` (which would leave a blank tab) or ``navigate_page``
  (which needs a selected page that doesn't exist on fresh Chromium)
* ordering: force-start call fires BEFORE ``pre_engine_hook``
* [c2] ``Tool.bind_mcp(server, port)`` receives the right port
* [c4] hook exceptions are recorded in ``RunResult.extensions_failed``
* [n4] ``extra_tools`` is bound even when ``pre_engine_hook`` is None
* ``extra_section`` is appended to the system prompt
* security hardening: ``_default_browser_mcp`` passes loopback + no-telemetry flags
"""
from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from webqa_agent.executor.flash import runner
from webqa_agent.executor.flash.core.tool import Tool, ToolResult


class _FakeMCPServer:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict]] = []
        self.fail_on: set[str] = set()

    def call_tool(self, name: str, args: dict) -> ToolResult:
        self.calls.append((name, dict(args)))
        if name in self.fail_on:
            raise RuntimeError(f'simulated failure in {name}')
        return ToolResult(content='ok', is_error=False)


class _FakeMCPManager:
    def __init__(self, server: _FakeMCPServer) -> None:
        self._servers = {'browser': server}

    def start_and_collect_tools(self) -> list:
        return []

    def shutdown_all(self) -> None:
        pass


class _RecorderTool(Tool):
    """Native Tool that records every bind_mcp / execute call."""

    def __init__(self, name: str = 'recorder') -> None:
        self._name = name
        self.bound: list[tuple[object, int]] = []
        self.executed: list[dict] = []

    @property
    def name(self) -> str:
        return self._name

    @property
    def description(self) -> str:
        return 'recorder tool'

    @property
    def input_schema(self) -> dict:
        return {'type': 'object', 'properties': {}}

    def execute(self, **kwargs) -> ToolResult:
        self.executed.append(dict(kwargs))
        return ToolResult(content='ok', is_error=False)

    def bind_mcp(self, mcp_server, port: int) -> None:
        self.bound.append((mcp_server, port))


class _FakeEngine:
    """Minimal Engine stand-in.

    Captures the system prompt + tools for assertions, yields zero events from
    submit() so run_cc_mini returns immediately with empty steps.
    """

    last_instance: '_FakeEngine | None' = None

    def __init__(self, tools, system_prompt, **_kwargs) -> None:
        self.tools = list(tools)
        self.system_prompt = system_prompt
        self._client = MagicMock()
        self._model = 'claude-sonnet-4-6'
        _FakeEngine.last_instance = self

    def submit(self, seed):
        return iter([])

    def abort(self) -> None:
        pass

    def get_messages(self) -> list:
        return []

    def set_messages(self, messages) -> None:
        pass

    def get_model(self) -> str:
        return self._model

    def last_assistant_text(self) -> str:
        return 'done'


@pytest.fixture
def patched_runner(monkeypatch):
    """Patch MCPManager + Engine + CompactService to isolate extension-point
    logic."""
    server = _FakeMCPServer()

    def _fake_manager_factory(configs):
        return _FakeMCPManager(server)

    class _NoopCompact:
        def __init__(self, *a, **kw):
            pass

        def compact(self, messages, system_prompt):
            return (messages, 0)

    monkeypatch.setattr(runner, 'MCPManager', _fake_manager_factory)
    monkeypatch.setattr(runner, 'Engine', _FakeEngine)
    monkeypatch.setattr(runner, 'CompactService', _NoopCompact)
    monkeypatch.setattr(runner, 'should_compact', lambda *a, **kw: False)
    monkeypatch.setattr(runner, '_can_bind_tcp_port', lambda host, port: True)
    monkeypatch.setattr(runner, '_probe_cdp_http_endpoint', lambda host, port: None)
    _FakeEngine.last_instance = None
    yield server


# ---------------------------------------------------------------------- tests


def test_worker_id_below_zero_raises():
    with pytest.raises(ValueError, match='worker_id'):
        runner.run_cc_mini('https://example.com', 'task', worker_id=-1)


def test_worker_id_above_max_raises():
    with pytest.raises(ValueError, match='worker_id'):
        runner.run_cc_mini('https://example.com', 'task', worker_id=56314)


def test_default_mcp_args_include_security_flags():
    configs = runner._default_browser_mcp('/tmp/profile-x', worker_id=0)
    args = tuple(configs[0].args)
    joined = ' '.join(args)
    assert '--chrome-arg=--remote-debugging-address=127.0.0.1' in joined
    assert '--no-usage-statistics' in args
    # The port must reach Chromium via --chrome-arg=… — bare
    # --remote-debugging-port is silently dropped by chrome-devtools-mcp's
    # yargs parser (see _default_browser_mcp docstring).
    assert '--chrome-arg=--remote-debugging-port=9222' in joined, (
        'port must be wrapped as --chrome-arg=... to reach Chromium')
    assert '--remote-debugging-port=9222' not in args, (
        'bare --remote-debugging-port arg is a silent no-op; use the '
        '--chrome-arg=... form instead')


def test_force_start_uses_list_pages_not_tab_opening_tools(patched_runner):
    """Force-start must be side-effect-free.

    ``new_page`` opens an extra blank tab beside Chromium's startup tab;
    ``navigate_page`` requires a selected page that doesn't exist yet.
    ``list_pages`` is read-only and simply triggers chrome-devtools-mcp's
    lazy Chromium launch so the CDP port binds before the hook fires.
    """
    server = patched_runner
    hook_calls: list[tuple[object, int]] = []

    def hook(mcp, port):
        hook_calls.append((mcp, port))

    runner.run_cc_mini(
        'https://example.com', 'task',
        worker_id=3,
        pre_engine_hook=hook,
        api_key='fake-key',
    )

    tool_names = [name for name, _ in server.calls]
    assert 'list_pages' in tool_names
    assert 'new_page' not in tool_names
    assert 'navigate_page' not in tool_names


def test_force_start_fires_before_pre_engine_hook(patched_runner):
    """The hook needs port bound; force-start must run first."""
    server = patched_runner
    hook_called_with_calls_so_far: list[list[str]] = []

    def hook(mcp, port):
        hook_called_with_calls_so_far.append(
            [name for name, _ in server.calls])

    runner.run_cc_mini(
        'https://example.com', 'task',
        worker_id=0,
        pre_engine_hook=hook,
        api_key='fake-key',
    )

    assert hook_called_with_calls_so_far, 'hook should have been invoked'
    # At the time the hook ran, force-start was already in the call list
    assert hook_called_with_calls_so_far[0] == ['list_pages']


def test_hook_receives_correct_port(patched_runner):
    captured: list[int] = []

    def hook(mcp, port):
        captured.append(port)

    runner.run_cc_mini(
        'https://example.com', 'task',
        worker_id=7,
        pre_engine_hook=hook,
        api_key='fake-key',
    )

    assert captured == [9222 + 7]


def test_hook_exception_recorded_in_extensions_failed(patched_runner):
    def bad_hook(mcp, port):
        raise RuntimeError('boom')

    result = runner.run_cc_mini(
        'https://example.com', 'task',
        worker_id=0,
        pre_engine_hook=bad_hook,
        api_key='fake-key',
    )

    assert result.extensions_failed
    assert any('pre_engine_hook' in line and 'boom' in line
               for line in result.extensions_failed)


def test_bind_mcp_called_with_server_and_port(patched_runner):
    tool = _RecorderTool()
    runner.run_cc_mini(
        'https://example.com', 'task',
        worker_id=2,
        extra_tools=[tool],
        api_key='fake-key',
    )

    assert len(tool.bound) == 1
    mcp_server, port = tool.bound[0]
    assert port == 9222 + 2
    # The server reference should be the _FakeMCPServer we injected
    assert mcp_server is patched_runner


def test_bind_mcp_called_even_without_pre_engine_hook(patched_runner):
    """[n4] extra_tools bind happens independently of pre_engine_hook."""
    tool = _RecorderTool()
    runner.run_cc_mini(
        'https://example.com', 'task',
        worker_id=0,
        extra_tools=[tool],
        pre_engine_hook=None,          # explicitly no hook
        api_key='fake-key',
    )
    assert len(tool.bound) == 1


def test_extra_tools_appear_in_engine_tool_list(patched_runner):
    tool = _RecorderTool('unique_recorder_name')
    runner.run_cc_mini(
        'https://example.com', 'task',
        extra_tools=[tool],
        api_key='fake-key',
    )

    engine = _FakeEngine.last_instance
    assert engine is not None
    tool_names = [t.name for t in engine.tools]
    assert 'unique_recorder_name' in tool_names


def test_extra_section_appended_to_system_prompt(patched_runner):
    marker_section = '## Marker Section\n\nhello world 1729'
    runner.run_cc_mini(
        'https://example.com', 'task',
        extra_section=marker_section,
        api_key='fake-key',
    )

    engine = _FakeEngine.last_instance
    assert engine is not None
    assert '## Marker Section' in engine.system_prompt
    assert 'hello world 1729' in engine.system_prompt


def test_force_start_failure_recorded_in_extensions_failed(patched_runner):
    server = patched_runner
    server.fail_on = {'list_pages'}

    def hook(mcp, port):
        # Shouldn't reach here if force-start fails — the except block
        # catches the RuntimeError and records it, then skips to extra_tools.
        pass

    result = runner.run_cc_mini(
        'https://example.com', 'task',
        pre_engine_hook=hook,
        api_key='fake-key',
    )

    # Our implementation wraps both force-start and hook in one try-except,
    # so a list_pages failure shows up as 'pre_engine_hook: <exc>' in the
    # extensions_failed list — still visible, just labelled by the block.
    assert result.extensions_failed
    assert any('simulated failure in list_pages' in line
               for line in result.extensions_failed)


def test_no_extensions_no_failures(patched_runner):
    """Backward-compat: no extensions means empty extensions_failed."""
    result = runner.run_cc_mini(
        'https://example.com', 'task',
        api_key='fake-key',
    )
    assert result.extensions_failed == []


class _FakeConfig:
    """Shape-compatible with MCPServerConfig for _resolve_cdp_port's args
    attribute reads; we avoid importing the real dataclass so the tests don't
    break on signature additions."""

    def __init__(self, name: str, args: tuple) -> None:
        self.name = name
        self.args = args


class TestResolveCdpPort:
    """_resolve_cdp_port: priority browser-url > ws-endpoint > chrome-arg port."""

    def test_default_config_returns_worker_port(self):
        configs = runner._default_browser_mcp('/tmp/profile', worker_id=5)
        assert runner._resolve_cdp_port(configs, worker_id=5) == 9227

    def test_browser_url_wins_over_chrome_arg_port(self):
        cfg = _FakeConfig('browser', (
            '--browser-url=ws://127.0.0.1:40000/devtools/browser/abc',
            '--chrome-arg=--remote-debugging-port=50000',
        ))
        assert runner._resolve_cdp_port([cfg], worker_id=0) == 40000

    def test_browserUrl_camelcase_also_works(self):
        cfg = _FakeConfig('browser', (
            '--browserUrl=ws://host:9999/x',
        ))
        assert runner._resolve_cdp_port([cfg], worker_id=0) == 9999

    def test_ws_endpoint_used_when_no_browser_url(self):
        cfg = _FakeConfig('browser', (
            '--ws-endpoint=ws://127.0.0.1:12345/devtools/browser/xyz',
            '--chrome-arg=--remote-debugging-port=50000',
        ))
        assert runner._resolve_cdp_port([cfg], worker_id=0) == 12345

    def test_wsEndpoint_camelcase_also_works(self):
        cfg = _FakeConfig('browser', (
            '--wsEndpoint=ws://127.0.0.1:33333/x',
        ))
        assert runner._resolve_cdp_port([cfg], worker_id=0) == 33333

    def test_chrome_arg_port_used_when_no_url(self):
        cfg = _FakeConfig('browser', (
            '--chrome-arg=--remote-debugging-port=44444',
        ))
        assert runner._resolve_cdp_port([cfg], worker_id=0) == 44444

    def test_custom_config_without_port_returns_none(self):
        cfg = _FakeConfig('browser', ('--headless',))
        assert runner._resolve_cdp_port([cfg], worker_id=0) is None

    def test_missing_browser_server_returns_none(self):
        cfg = _FakeConfig('other', ('--chrome-arg=--remote-debugging-port=9222',))
        assert runner._resolve_cdp_port([cfg], worker_id=0) is None

    def test_bare_remote_debugging_port_ignored(self):
        """Bare --remote-debugging-port is silently dropped by chrome-devtools-
        mcp; we correctly don't trust it."""
        cfg = _FakeConfig('browser', (
            '--remote-debugging-port=9222',   # wrong form
        ))
        assert runner._resolve_cdp_port([cfg], worker_id=0) is None


def test_custom_mcp_without_resolvable_port_records_extension_failure(patched_runner):
    """When pre_engine_hook is set but cdp_port can't be resolved, the hook
    must NOT run and extensions_failed must clearly describe why."""
    # Substitute the patched runner's fake MCP factory with one whose
    # configs have no port.
    server = patched_runner

    def _fake_manager_factory(_configs):
        class _FakeMCP:
            def __init__(self):
                self._servers = {'browser': server}

            def start_and_collect_tools(self):
                return []

            def shutdown_all(self):
                pass

        return _FakeMCP()

    from webqa_agent.executor.flash import runner as _runner
    orig_mgr = _runner.MCPManager
    _runner.MCPManager = _fake_manager_factory
    try:
        port_inside_hook: list[int | None] = []

        def hook(mcp, port):
            port_inside_hook.append(port)

        custom_mcp = [_FakeConfig('browser', ('--headless',))]
        # MCPServerConfig is a dataclass; substitute with shape-compatible.
        result = _runner.run_cc_mini(
            'https://example.com', 'task',
            mcp_servers=custom_mcp,      # type: ignore[arg-type]
            pre_engine_hook=hook,
            api_key='fake-key',
        )
    finally:
        _runner.MCPManager = orig_mgr

    assert port_inside_hook == [], 'hook must not have been invoked'
    assert result.extensions_failed
    assert any('CDP port could not be resolved' in line
               for line in result.extensions_failed)


def test_bind_mcp_exception_recorded_but_tool_still_added(patched_runner):
    class _BoundBreaksTool(_RecorderTool):
        def bind_mcp(self, mcp_server, port):
            raise RuntimeError('bind failed')

    tool = _BoundBreaksTool('breaking_tool')
    result = runner.run_cc_mini(
        'https://example.com', 'task',
        extra_tools=[tool],
        api_key='fake-key',
    )

    assert any('bind_mcp breaking_tool' in line and 'bind failed' in line
               for line in result.extensions_failed)

    engine = _FakeEngine.last_instance
    assert engine is not None
    tool_names = [t.name for t in engine.tools]
    assert 'breaking_tool' in tool_names

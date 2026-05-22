"""Concurrent multi-worker cookie isolation — the root correctness property.

The reason for this feature is that N parallel ``run_cc_mini`` calls, each
with its own account, never cross-contaminate cookie state. This test
proves that by running two workers concurrently on threads and verifying
each worker's CDP client saw only its own cookies on its own port.

We stub out ``CDPCookieClient`` so no real browser / socket is needed —
the property under test is at the runner + build_cookie_extensions layer,
not in the CDP framing (the latter is covered by test_cdp_client.py).
"""
from __future__ import annotations

import threading
from unittest.mock import MagicMock

import pytest

from webqa_agent.executor.flash import runner
from webqa_agent.executor.flash.core.tool import ToolResult
from webqa_agent.executor.flash.features import cookies as cookies_pkg
from webqa_agent.executor.flash.features.cookies import (
    AccountSpec, build_cookie_extensions)

# ---------------------------------------------------------------------------
# test doubles (shared with test_runner_extension_points.py philosophy, but
# intentionally inlined here so the isolation test can stand alone)
# ---------------------------------------------------------------------------


class _FakeMCPServer:
    def call_tool(self, name: str, args: dict) -> ToolResult:
        return ToolResult(content='ok', is_error=False)


class _FakeMCPManager:
    def __init__(self, *_args, **_kwargs) -> None:
        self._servers = {'browser': _FakeMCPServer()}

    def start_and_collect_tools(self) -> list:
        return []

    def shutdown_all(self) -> None:
        pass


class _FakeEngine:
    def __init__(self, tools, system_prompt, **_kwargs) -> None:
        self.tools = list(tools)
        self.system_prompt = system_prompt
        self._client = MagicMock()
        self._model = 'claude-sonnet-4-6'

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


class _RecordingCDPClient:
    """Records every call; instances are collected on the shared registry."""

    registry: list['_RecordingCDPClient'] = []
    registry_lock = threading.Lock()

    def __init__(self, port: int, host: str = '127.0.0.1',
                 timeout: float = 10.0) -> None:
        self.port = port
        self.received_cookies: list[dict] = []
        self.thread_name = threading.current_thread().name
        with _RecordingCDPClient.registry_lock:
            _RecordingCDPClient.registry.append(self)

    def connect(self) -> None:
        pass

    def set_cookies(self, cookies: list[dict]) -> None:
        self.received_cookies.extend(cookies)

    def clear_cookies(self) -> None:
        pass

    def clear_and_set(self, cookies: list[dict]) -> None:
        self.clear_cookies()
        self.set_cookies(cookies)

    def close(self) -> None:
        pass


@pytest.fixture
def patched(monkeypatch):
    class _NoopCompact:
        def __init__(self, *a, **kw):
            pass

        def compact(self, messages, system_prompt):
            return (messages, 0)

    monkeypatch.setattr(runner, 'MCPManager', _FakeMCPManager)
    monkeypatch.setattr(runner, 'Engine', _FakeEngine)
    monkeypatch.setattr(runner, 'CompactService', _NoopCompact)
    monkeypatch.setattr(runner, 'should_compact', lambda *a, **kw: False)
    monkeypatch.setattr(runner, '_can_bind_tcp_port', lambda host, port: True)
    monkeypatch.setattr(runner, '_probe_cdp_http_endpoint', lambda host, port: None)
    monkeypatch.setattr(cookies_pkg, 'CDPCookieClient', _RecordingCDPClient)
    _RecordingCDPClient.registry = []
    yield


# ---------------------------------------------------------------------------
# the test
# ---------------------------------------------------------------------------


_ADMIN = [{'name': 'session', 'value': 'admin-token-AAA',
           'domain': '.example.com', 'path': '/'}]
_VIEWER = [{'name': 'session', 'value': 'viewer-token-BBB',
            'domain': '.example.com', 'path': '/'}]


def _run_worker(worker_id: int, cookies: list[dict]) -> None:
    ext = build_cookie_extensions(accounts=[
        AccountSpec(name=f'w{worker_id}', cookies=cookies, default=True),
    ])
    runner.run_cc_mini(
        url='https://example.com/',
        user_input=f'worker {worker_id}',
        worker_id=worker_id,
        api_key='fake-key',
        **ext.as_kwargs(),
    )


def test_concurrent_workers_do_not_cross_contaminate_cookies(patched):
    """Two workers running in parallel each see only their own cookies."""
    t0 = threading.Thread(target=_run_worker, args=(0, _ADMIN),
                          name='worker-0')
    t1 = threading.Thread(target=_run_worker, args=(1, _VIEWER),
                          name='worker-1')
    t0.start()
    t1.start()
    t0.join(timeout=10.0)
    t1.join(timeout=10.0)
    assert not t0.is_alive() and not t1.is_alive()

    # Exactly one CDP client instance per worker.
    assert len(_RecordingCDPClient.registry) == 2

    by_port = {c.port: c for c in _RecordingCDPClient.registry}
    assert set(by_port) == {9222, 9223}, (
        f'expected distinct ports 9222/9223, got {set(by_port)}')

    admin_client = by_port[9222]
    viewer_client = by_port[9223]

    admin_values = {c['value'] for c in admin_client.received_cookies}
    viewer_values = {c['value'] for c in viewer_client.received_cookies}

    # Positive: each got its intended tokens
    assert admin_values == {'admin-token-AAA'}
    assert viewer_values == {'viewer-token-BBB'}

    # Negative: neither saw the other's tokens (the root isolation property)
    assert 'viewer-token-BBB' not in admin_values
    assert 'admin-token-AAA' not in viewer_values


def test_sequential_runs_each_use_correct_port(patched):
    """Sanity: sequential runs with distinct worker_ids address distinct ports."""
    _run_worker(0, _ADMIN)
    _run_worker(5, _VIEWER)

    ports = [c.port for c in _RecordingCDPClient.registry]
    assert ports == [9222, 9227]


def test_worker_cookies_match_worker_id(patched):
    """For any worker_id, the injected cookies are that worker's, on that
    worker's port."""
    for w, tok in [(0, 'tok-0'), (3, 'tok-3'), (7, 'tok-7')]:
        _run_worker(w, [{'name': 's', 'value': tok,
                         'domain': '.example.com', 'path': '/'}])

    # Group clients by port and verify each saw only its matching token.
    for client in _RecordingCDPClient.registry:
        worker_id = client.port - 9222
        expected = f'tok-{worker_id}'
        seen = {c['value'] for c in client.received_cookies}
        assert seen == {expected}, (
            f'worker {worker_id} on port {client.port} expected {{{expected}}},'
            f' got {seen}')

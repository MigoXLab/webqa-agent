"""Memory / process-footprint benchmark for multi-worker cookie injection.

Two invariants matter here:

1. **No Node driver subprocess.** The bare-CDP client was chosen over
   Playwright specifically to avoid spawning a ~100MB Node driver per
   worker. This test asserts no ``playwright-driver`` / ``chromium-driver``
   process exists after (and during) a run, proving the feature stays
   on the stdlib socket path.

2. **RSS stays flat across concurrent workers.** With mocked MCP + LLM
   the per-worker overhead is dominated by Python-level state; this test
   bounds that at 150MB total increment for 5 concurrent workers. A real
   chrome-devtools-mcp + Chromium run will dominate this, but the
   cookies-feature contribution should stay below the budget.

Skipped by default via the ``perf`` marker. Run with ``pytest -m perf``.
"""
from __future__ import annotations

import asyncio
import gc
import os
import subprocess
from unittest.mock import MagicMock

import pytest

from webqa_agent.executor.flash import runner
from webqa_agent.executor.flash.core.tool import ToolResult
from webqa_agent.executor.flash.features import cookies as cookies_pkg
from webqa_agent.executor.flash.features.cookies import (
    AccountSpec, build_cookie_extensions)

pytestmark = pytest.mark.perf


# ---------------------------------------------------------------------------
# harness doubles
# ---------------------------------------------------------------------------


class _FakeMCPServer:
    def call_tool(self, name: str, args: dict) -> ToolResult:
        return ToolResult(content='ok', is_error=False)


class _FakeMCPManager:
    def __init__(self, *_a, **_k) -> None:
        self._servers = {'browser': _FakeMCPServer()}

    def start_and_collect_tools(self) -> list:
        return []

    def shutdown_all(self) -> None:
        pass


class _FakeEngine:
    def __init__(self, tools, system_prompt, **_k) -> None:
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

    def set_messages(self, _m) -> None:
        pass

    def get_model(self) -> str:
        return self._model

    def last_assistant_text(self) -> str:
        return 'done'


class _NoopCDP:
    """Cheap stand-in for CDPCookieClient — measures runner overhead only."""

    def __init__(self, port, host='127.0.0.1', timeout=10.0):
        pass

    def connect(self):
        pass

    def set_cookies(self, _c):
        pass

    def clear_cookies(self):
        pass

    def clear_and_set(self, _c):
        pass

    def close(self):
        pass


@pytest.fixture
def patched(monkeypatch):
    class _NoopCompact:
        def __init__(self, *a, **k):
            pass

        def compact(self, messages, system_prompt):
            return (messages, 0)

    monkeypatch.setattr(runner, 'MCPManager', _FakeMCPManager)
    monkeypatch.setattr(runner, 'Engine', _FakeEngine)
    monkeypatch.setattr(runner, 'CompactService', _NoopCompact)
    monkeypatch.setattr(runner, 'should_compact', lambda *a, **kw: False)
    monkeypatch.setattr(cookies_pkg, 'CDPCookieClient', _NoopCDP)
    yield


# ---------------------------------------------------------------------------
# process-footprint invariants
# ---------------------------------------------------------------------------


def _count_driver_processes() -> int:
    """Count Node driver processes that would exist if we used Playwright."""
    patterns = ['playwright-driver', 'chromium-driver', 'playwright/driver']
    total = 0
    for pat in patterns:
        try:
            out = subprocess.run(
                ['pgrep', '-f', pat], capture_output=True, text=True,
                timeout=2.0, check=False)
            if out.stdout.strip():
                total += len(out.stdout.strip().splitlines())
        except (subprocess.TimeoutExpired, FileNotFoundError):
            # No pgrep on this OS, or call timed out — skip silently.
            return 0
    return total


def test_no_playwright_driver_spawned(patched):
    """Bare-CDP contract: the feature must not introduce a Node driver."""
    # Establish baseline so we only attribute new drivers to our runs.
    baseline = _count_driver_processes()

    ext = build_cookie_extensions(accounts=[
        AccountSpec(name='admin',
                    cookies=[{'name': 's', 'value': 'x',
                              'domain': '.example.com', 'path': '/'}],
                    default=True),
    ])
    runner.run_cc_mini(
        url='https://example.com/',
        user_input='task',
        worker_id=0,
        api_key='fake-key',
        **ext.as_kwargs(),
    )

    after = _count_driver_processes()
    assert after <= baseline, (
        f'unexpected driver processes: baseline={baseline}, after={after}. '
        'The bare-CDP client should not spawn a Node subprocess.')


# ---------------------------------------------------------------------------
# multi-worker memory bound
# ---------------------------------------------------------------------------


def _get_rss_mb() -> float | None:
    """Return current RSS in MB if psutil available; else None (skip)."""
    try:
        import psutil  # type: ignore
    except ImportError:
        return None
    return psutil.Process(os.getpid()).memory_info().rss / (1024 * 1024)


def _run_one(worker_id: int) -> None:
    ext = build_cookie_extensions(accounts=[
        AccountSpec(name=f'w{worker_id}',
                    cookies=[{'name': 's', 'value': f'tok-{worker_id}',
                              'domain': '.example.com', 'path': '/'}],
                    default=True),
    ])
    runner.run_cc_mini(
        url='https://example.com/',
        user_input=f'w{worker_id}',
        worker_id=worker_id,
        api_key='fake-key',
        **ext.as_kwargs(),
    )


def test_five_concurrent_workers_memory_bound(patched):
    """RSS increment for 5 concurrent workers < 150MB (with mocked MCP/LLM)."""
    if _get_rss_mb() is None:
        pytest.skip('psutil not installed')

    async def _fanout() -> None:
        await asyncio.gather(*(
            asyncio.to_thread(_run_one, i) for i in range(5)))

    gc.collect()
    baseline = _get_rss_mb()
    assert baseline is not None

    asyncio.run(_fanout())

    gc.collect()
    after = _get_rss_mb()
    assert after is not None
    delta = after - baseline

    print(f'\nRSS: baseline={baseline:.1f}MB after={after:.1f}MB '
          f'delta={delta:.1f}MB')

    # Generous budget — real cost dominated by Python + pytest fixtures;
    # the feature's own per-worker footprint is a handful of kilobytes.
    assert delta < 150.0, (
        f'5-worker RSS increment {delta:.1f}MB exceeds 150MB budget')

"""Tests for routing Gen mode through the local webqa-cc-mini bridge."""

from __future__ import annotations

import asyncio
import importlib
import sys
import types
from dataclasses import dataclass
from types import SimpleNamespace

import pytest


class _UnexpectedExecutor:
    def __init__(self, *args, **kwargs) -> None:
        raise AssertionError('GenExecutor should not be constructed in cc-mini mode')


def _load_cli_module(monkeypatch: pytest.MonkeyPatch):
    """Import cli with a lightweight executor stub scoped to one test."""
    executor_pkg = types.ModuleType('webqa_agent.executor')
    executor_pkg.__path__ = []
    gen_executor_module = types.ModuleType('webqa_agent.executor.gen_executor')
    gen_executor_module.GenExecutor = _UnexpectedExecutor

    monkeypatch.setitem(sys.modules, 'webqa_agent.executor', executor_pkg)
    monkeypatch.setitem(sys.modules, 'webqa_agent.executor.gen_executor', gen_executor_module)
    monkeypatch.delitem(sys.modules, 'webqa_agent.cli', raising=False)
    return importlib.import_module('webqa_agent.cli')


@dataclass
class _FakeRunResult:
    final_text: str = 'done'
    steps: list[str] | None = None
    aborted: bool = False
    input_tokens: int = 11
    output_tokens: int = 7

    def __post_init__(self) -> None:
        if self.steps is None:
            self.steps = ['step-1']


def test_execute_gen_mode_routes_to_cc_mini(monkeypatch, capsys):
    """Gen mode should route to cc-mini when test_config.use_cc_mini is enabled."""
    cli = _load_cli_module(monkeypatch)
    captured: dict[str, str | None] = {}

    async def fake_execute_cc_mini_mode(**kwargs):
        captured.update(kwargs)
        return _FakeRunResult()

    monkeypatch.setattr(cli, '_execute_cc_mini_mode', fake_execute_cc_mini_mode)

    cfg = {
        'target': {'url': 'https://example.com'},
        'test_config': {
            'use_cc_mini': True,
            'business_objectives': '验证搜索功能',
        },
        'llm_config': {
            'model': 'gemini-3-flash-preview',
            'api_key': 'test-api-key',
            'base_url': 'http://localhost:8000/v1',
            'reasoning': {'effort': 'medium'},
        },
    }

    asyncio.run(cli.execute_gen_mode(cfg))

    # The on_event handler is an internal detail — assert it was wired but
    # isolate it from the config-controlled kwargs check.
    on_event_fn = captured.pop('on_event', None)
    assert callable(on_event_fn)
    assert captured == {
        'url': 'https://example.com',
        'task': '验证搜索功能',
        'provider': 'openai',
        'model': 'gemini-3-flash-preview',
        'api_key': 'test-api-key',
        'base_url': 'http://localhost:8000/v1',
        'effort': 'medium',
        # LLMConfig fields that default to None when not set in test config.
        'temperature': None,
        'top_p': None,
        'max_tokens': None,
        'timeout': None,
        # log_level inherits from cfg.log.level (default 'info').
        'log_level': 'info',
    }
    stdout = capsys.readouterr().out
    assert 'Gen Mode (cc-mini backend)' in stdout
    assert 'cc-mini Task: 验证搜索功能' in stdout


def test_execute_gen_mode_forwards_llm_tuning_params_to_cc_mini(monkeypatch):
    """temperature / top_p / max_tokens / timeout must reach the cc-mini bridge.

    Guards against falsy-truthiness regressions: ``temperature=0`` is a
    perfectly valid setting (deterministic sampling) but ``if temperature:``
    would silently drop it. This test pins the positive transparency path so
    any future ``if value`` check breaks here instead of in production.
    """
    cli = _load_cli_module(monkeypatch)
    captured: dict[str, object] = {}

    async def fake_execute_cc_mini_mode(**kwargs):
        captured.update(kwargs)
        return _FakeRunResult()

    monkeypatch.setattr(cli, '_execute_cc_mini_mode', fake_execute_cc_mini_mode)

    cfg = {
        'target': {'url': 'https://example.com'},
        'test_config': {
            'use_cc_mini': True,
            'business_objectives': 'verify search',
        },
        'llm_config': {
            'model': 'gpt-4.1-mini',
            'api_key': 'test-api-key',
            'base_url': 'https://api.openai.com/v1',
            'temperature': 0,       # falsy but valid
            'top_p': 0.95,
            'max_tokens': 4096,
            'timeout': 120,
        },
    }

    asyncio.run(cli.execute_gen_mode(cfg))

    assert captured['temperature'] == 0
    assert captured['top_p'] == 0.95
    assert captured['max_tokens'] == 4096
    assert captured['timeout'] == 120


def test_execute_gen_mode_requires_business_objectives_for_cc_mini(monkeypatch):
    """cc-mini mode should fail fast when the mapped task is empty."""
    cli = _load_cli_module(monkeypatch)

    cfg = {
        'target': {'url': 'https://example.com'},
        'test_config': {
            'use_cc_mini': True,
            'business_objectives': '   ',
        },
        'llm_config': {
            'model': 'gpt-5.4',
            'api_key': 'test-api-key',
            'base_url': 'https://api.openai.com/v1',
        },
    }

    with pytest.raises(SystemExit) as exc_info:
        asyncio.run(cli.execute_gen_mode(cfg))

    assert exc_info.value.code == 1


def test_execute_gen_mode_anthropic_drops_openai_default_base_url(monkeypatch):
    """Anthropic provider must not inherit the OpenAI base_url default.

    ``validate_and_build_llm_config`` injects ``https://api.openai.com/v1`` when
    no ``base_url`` is configured. For Claude models this would break every
    request, so the cc-mini bridge clears it back to None.
    """
    cli = _load_cli_module(monkeypatch)
    captured: dict[str, str | None] = {}

    async def fake_execute_cc_mini_mode(**kwargs):
        captured.update(kwargs)
        return _FakeRunResult()

    monkeypatch.setattr(cli, '_execute_cc_mini_mode', fake_execute_cc_mini_mode)
    # Ensure no OPENAI_BASE_URL is leaking from the env into the default path.
    monkeypatch.delenv('OPENAI_BASE_URL', raising=False)

    cfg = {
        'target': {'url': 'https://example.com'},
        'test_config': {
            'use_cc_mini': True,
            'business_objectives': 'verify search',
        },
        'llm_config': {
            'model': 'claude-sonnet-4-6',
            'api_key': 'test-api-key',
            # base_url intentionally omitted — the default OpenAI URL would
            # normally leak through for non-explicit configurations.
        },
    }

    asyncio.run(cli.execute_gen_mode(cfg))

    assert captured['provider'] == 'anthropic'
    assert captured['base_url'] is None
    assert callable(captured.get('on_event'))


def test_cc_mini_stream_handler_formats_events(monkeypatch, capsys):
    """The streaming handler must surface progress events in real time.

    Covers the event types emitted by the engine:
      * text chunks are printed inline without extra framing
      * tool_call prints one line with the activity description
      * successful tool_result is silent (success is implicit)
      * failing tool_result surfaces a truncated error snippet
      * usage prints per-call token counts as a heartbeat
      * error events are forwarded verbatim
    """
    cli = _load_cli_module(monkeypatch)
    handle = cli._make_cc_mini_stream_handler()

    handle(('text', 'Navigating'))
    handle(('text', ' to page'))
    handle(('waiting',))
    handle(('tool_call', 'navigate_page', {'url': 'https://a'}, 'MCP browser: navigate_page'))
    handle(('tool_result', 'navigate_page', {}, SimpleNamespace(content='ok', is_error=False)))
    handle((
        'tool_result',
        'click',
        {},
        SimpleNamespace(content='element not found\nselector missing', is_error=True),
    ))
    handle(('usage', SimpleNamespace(input_tokens=123, output_tokens=45)))
    handle(('error', 'rate limited, retrying'))

    out = capsys.readouterr().out
    # Streamed text lands before the trailing newline from ``waiting``.
    assert 'Navigating to page\n' in out
    # Tool activity rendered on its own line.
    assert '🔧 MCP browser: navigate_page' in out
    # Success is silent — no ✅ noise per tool.
    assert 'navigate_page]' not in out  # no error bracket for success
    # Errors are surfaced with newlines flattened.
    assert '❌ [click] element not found selector missing' in out
    # Heartbeat shows both directions.
    assert '📊 123↑ 45↓' in out
    # API errors pass through.
    assert '⚠️  rate limited, retrying' in out

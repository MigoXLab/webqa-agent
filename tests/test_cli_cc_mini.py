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
    # Pre-import real sub-modules that _render_cc_mini_report and the CLI's
    # cc-mini batch path use lazily, BEFORE overwriting the executor package
    # with a stub.
    _real_submodules = {}
    for mod_name in (
        'webqa_agent.executor.cc_mini_report_adapter',
        'webqa_agent.executor.cc_mini_executor',
        'webqa_agent.executor.result_aggregator',
    ):
        if mod_name not in sys.modules:
            importlib.import_module(mod_name)
        _real_submodules[mod_name] = sys.modules[mod_name]

    cc_mini_executor_module = _real_submodules[
        'webqa_agent.executor.cc_mini_executor'
    ]
    import webqa_agent.executor as _real_executor_pkg
    executor_pkg = types.ModuleType('webqa_agent.executor')
    executor_pkg.__path__ = list(_real_executor_pkg.__path__)
    # Re-export the real CcMiniExecutor on the stubbed package so the CLI's
    # `from webqa_agent.executor import CcMiniExecutor` keeps working without
    # pulling in GenExecutor (which is what the stub is trying to avoid).
    executor_pkg.CcMiniExecutor = cc_mini_executor_module.CcMiniExecutor
    executor_pkg.CcMiniBatchResult = cc_mini_executor_module.CcMiniBatchResult
    gen_executor_module = types.ModuleType('webqa_agent.executor.gen_executor')
    gen_executor_module.GenExecutor = _UnexpectedExecutor

    monkeypatch.setitem(sys.modules, 'webqa_agent.executor', executor_pkg)
    monkeypatch.setitem(sys.modules, 'webqa_agent.executor.gen_executor', gen_executor_module)
    for mod_name, mod in _real_submodules.items():
        monkeypatch.setitem(sys.modules, mod_name, mod)
    monkeypatch.delitem(sys.modules, 'webqa_agent.cli', raising=False)
    return importlib.import_module('webqa_agent.cli')


@dataclass
class _FakeStep:
    tool: str = 'navigate'
    input: dict | None = None
    result: str = 'ok'
    is_error: bool = False

    def __post_init__(self) -> None:
        if self.input is None:
            self.input = {}


@dataclass
class _FakeRunResult:
    final_text: str = 'done'
    steps: list | None = None
    aborted: bool = False
    input_tokens: int = 11
    output_tokens: int = 7

    def __post_init__(self) -> None:
        if self.steps is None:
            self.steps = [_FakeStep()]


def test_execute_gen_mode_routes_to_cc_mini(monkeypatch, tmp_path, capsys):
    """Gen mode should route to cc-mini when test_config.use_cc_mini is
    enabled."""
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
        # Pin report_dir under tmp_path so the test does not pollute the
        # real ./reports/ tree with a fresh test_<timestamp>/ each run.
        'report': {'report_dir': str(tmp_path / 'cc-mini-out')},
    }

    asyncio.run(cli.execute_gen_mode(cfg))

    # The on_event and data_flow_sink handlers are internal details — assert
    # they were wired but isolate them from the config-controlled kwargs check.
    on_event_fn = captured.pop('on_event', None)
    assert callable(on_event_fn)
    data_flow_sink = captured.pop('data_flow_sink', None)
    assert callable(data_flow_sink)
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
        # Skills discovery is opt-in; cc_mini_skills_dir unset -> None.
        'skills_dir': None,
        # browser_config missing -> default headless True (aligns with GenExecutor).
        'browser_headless': True,
        'browser_viewport': None,
        # Screenshot persistence defaults.
        'save_screenshots': False,
        'screenshot_dir': None,
        # cc-mini runtime plumbing defaults.
        'worker_id': 0,
        'extensions': None,
        'filter_model': 'gemini-3-flash-preview',
        # No test_files_dir -> no file catalog.
        'file_catalog': None,
        # log_level inherits from cfg.log.level (default 'info').
        'log_level': 'info',
    }
    stdout = capsys.readouterr().out
    assert 'Gen Mode (cc-mini backend)' in stdout
    # The CLI now prints a numbered task list instead of the singular
    # "cc-mini Task: …" line, since business_objectives can be a batch.
    assert 'cc-mini Tasks: 1' in stdout
    assert '1. 验证搜索功能' in stdout
    assert 'cc-mini browser headless: True' in stdout


def test_execute_gen_mode_forwards_llm_tuning_params_to_cc_mini(
    monkeypatch, tmp_path,
):
    """Temperature / top_p / max_tokens / timeout must reach the cc-mini
    bridge.

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
        'report': {'report_dir': str(tmp_path / 'cc-mini-out')},
    }

    asyncio.run(cli.execute_gen_mode(cfg))

    assert captured['temperature'] == 0
    assert captured['top_p'] == 0.95
    assert captured['max_tokens'] == 4096
    assert captured['timeout'] == 120


def test_execute_gen_mode_requires_business_objectives_for_cc_mini(monkeypatch):
    """Cc-mini mode should fail fast when the mapped task is empty."""
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


def test_execute_gen_mode_exits_nonzero_when_case_failed(
    monkeypatch, tmp_path, capsys,
):
    """Failed overall batch exits with code 1 so CI can gate on webqa-agent."""
    cli = _load_cli_module(monkeypatch)

    async def fake_execute_cc_mini_mode(**kwargs):
        return _FakeRunResult(
            final_text='Error: CDP port 127.0.0.1:9222 is already in use',
            steps=[],
            aborted=True,
        )

    monkeypatch.setattr(cli, '_execute_cc_mini_mode', fake_execute_cc_mini_mode)
    cfg = {
        'target': {'url': 'https://example.com'},
        'test_config': {'use_cc_mini': True, 'business_objectives': 'smoke'},
        'llm_config': {
            'model': 'gpt-4o', 'api_key': 'k',
            'base_url': 'https://api.openai.com/v1',
        },
        'report': {'report_dir': str(tmp_path / 'fatal-report')},
    }

    with pytest.raises(SystemExit) as exc_info:
        asyncio.run(cli.execute_gen_mode(cfg))
    assert exc_info.value.code == 1

    stdout = capsys.readouterr().out
    assert 'Some cases failed' in stdout
    assert '0/1 passed' in stdout
    assert 'case-1 ❌ failed' in stdout


def test_execute_gen_mode_anthropic_drops_openai_default_base_url(
    monkeypatch, tmp_path,
):
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
        'report': {'report_dir': str(tmp_path / 'cc-mini-out')},
    }

    asyncio.run(cli.execute_gen_mode(cfg))

    assert captured['provider'] == 'anthropic'
    assert captured['base_url'] is None
    assert callable(captured.get('on_event'))


def test_execute_gen_mode_forwards_skills_dir_to_cc_mini(monkeypatch, tmp_path):
    """cc_mini_skills_dir in test_config must reach _execute_cc_mini_mode."""
    cli = _load_cli_module(monkeypatch)
    captured: dict[str, object] = {}

    async def fake_execute_cc_mini_mode(**kwargs):
        captured.update(kwargs)
        return _FakeRunResult()

    monkeypatch.setattr(cli, '_execute_cc_mini_mode', fake_execute_cc_mini_mode)

    skills_path = tmp_path / 'my-skills'
    skills_path.mkdir()

    cfg = {
        'target': {'url': 'https://example.com'},
        'test_config': {
            'use_cc_mini': True,
            'business_objectives': 'task',
            'cc_mini_skills_dir': str(skills_path),
        },
        'llm_config': {
            'model': 'gpt-4o', 'api_key': 'k',
            'base_url': 'https://api.openai.com/v1',
        },
        'report': {'report_dir': str(tmp_path / 'cc-mini-out')},
    }

    asyncio.run(cli.execute_gen_mode(cfg))
    assert captured['skills_dir'] == str(skills_path)


def test_execute_gen_mode_cc_mini_generates_html_report(
    monkeypatch, tmp_path, capsys,
):
    """Cc-mini mode must write an HTML report under the configured report_dir.

    Uses the gen-mode renderer by default (``test_report.html``), falling
    back to the standalone utility (``report.html``) only if the gen-mode
    path raises. Accept either filename to keep the test focused on the
    user-visible contract: "there is an HTML report and the CLI printed it".
    """
    cli = _load_cli_module(monkeypatch)

    async def fake_execute_cc_mini_mode(**kwargs):
        return _FakeRunResult(
            final_text='All good.',
            steps=[_FakeStep(tool='navigate', result='done')],
        )

    monkeypatch.setattr(cli, '_execute_cc_mini_mode', fake_execute_cc_mini_mode)

    report_dir = tmp_path / 'report-out'
    cfg = {
        'target': {'url': 'https://example.com'},
        'test_config': {'use_cc_mini': True, 'business_objectives': 'smoke'},
        'llm_config': {
            'model': 'gpt-4o', 'api_key': 'k',
            'base_url': 'https://api.openai.com/v1',
        },
        'report': {'report_dir': str(report_dir)},
    }

    asyncio.run(cli.execute_gen_mode(cfg))

    # The report may land in a timestamp subdirectory (platform convention)
    # or directly under report_dir. Search both levels.
    found = list(report_dir.rglob('test_report.html')) + list(report_dir.rglob('report.html'))
    assert found, 'no HTML report was written'
    content = found[0].read_text(encoding='utf-8')
    assert 'All good.' in content
    assert 'navigate' in content
    stdout = capsys.readouterr().out
    assert '📄 Report:' in stdout


def test_cc_mini_report_uses_gen_mode_frontend(monkeypatch, tmp_path):
    """End-to-end: cc-mini report must reuse the gen-mode React frontend.

    Confirms the adapter + ResultAggregator path is taken by default. Guards
    against silent regressions back to the standalone ``features/report.py``
    template (which has its own distinct look).
    """
    cli = _load_cli_module(monkeypatch)

    async def fake_execute_cc_mini_mode(**kwargs):
        return _FakeRunResult(
            final_text='done',
            steps=[_FakeStep(tool='navigate_page', result='ok')],
        )

    monkeypatch.setattr(cli, '_execute_cc_mini_mode', fake_execute_cc_mini_mode)

    report_dir = tmp_path / 'out'
    cfg = {
        'target': {'url': 'https://example.com'},
        'test_config': {'use_cc_mini': True, 'business_objectives': 'smoke'},
        'llm_config': {
            'model': 'gpt-4o', 'api_key': 'k',
            'base_url': 'https://api.openai.com/v1',
        },
        'report': {'report_dir': str(report_dir)},
    }

    asyncio.run(cli.execute_gen_mode(cfg))

    found = list(report_dir.rglob('test_report.html'))
    assert found, (
        'expected gen-mode report at test_report.html; fell back to the '
        'standalone renderer instead.'
    )
    content = found[0].read_text(encoding='utf-8')
    assert '<div id="root"></div>' in content
    assert 'window.testResultData' in content
    assert '"gen":' in content
    assert '"case_1_smoke"' in content
    assert '"index":' in content


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

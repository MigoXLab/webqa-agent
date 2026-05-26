"""Web agent library entry point.

Usage::

    from runner import run_cc_mini, RunResult

    result = run_cc_mini(
        url="https://example.com",
        user_input="Find the H1 heading and report it",
    )
    print(result.final_text)

    # Render an HTML report for the run (optional, standalone utility):
    from features.report import render_html_report
    render_html_report(result, "run_report.html",
                       title="Smoke test", url="https://example.com",
                       task="Find the H1 heading")

Supports Anthropic (default) and OpenAI-compatible providers::

    # OpenAI GPT-4o
    result = run_cc_mini("https://example.com", "test login",
                         provider="openai", model="gpt-4o")

    # Local Ollama
    result = run_cc_mini("https://example.com", "test login",
                         provider="openai", model="llama3.1:70b",
                         base_url="http://localhost:11434/v1",
                         api_key="ollama")

Skills (optional Progressive Disclosure)::

    result = run_cc_mini(url, task, skills_dir="./skills")

    # Discovers skills/<name>/SKILL.md subdirs at startup, injects each
    # name + description into the system prompt (~100 tokens/skill), and
    # adds a load_skill tool so the LLM can fetch full instructions on
    # demand. See webqa-cc-mini/skills/README.md for the SKILL.md format.
"""
from __future__ import annotations

import atexit
import base64
import errno
import http.client
import json
import logging
import os
import shutil
import signal
import socket
import sys
import tempfile
import time
from collections import deque
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

EventCallback = Callable[[tuple[Any, ...]], None]
DataFlowSink = Callable[[dict[str, Any]], None]

from .core.config import DEFAULT_MODEL, DEFAULT_PROVIDER, MCPServerConfig
from .core.context import build_web_agent_system_prompt
from .core.engine import AbortedError, Engine
from .core.llm import LLMClient, infer_provider_from_model
from .core.mcp_client import MCPManager
from .core.outcome_status import derive_status, extract_final_outcome
from .core.permissions import PermissionChecker
from .core.skill_registry import SkillRegistry
from .core.tool import Tool
from .features.compact import CompactService, should_compact
from .tools import (CDPUploadTool, DownloadCheckTool, LoadSkillTool,
                    NucleiScanTool, VerifyTool, WaitForDomStableTool)

log = logging.getLogger('cc_mini.runner')

try:
    from webqa_agent.utils.get_log import GetLog
    from webqa_agent.utils.task_display_util import Display
    _DISPLAY_AVAILABLE = True
except Exception:
    GetLog = None  # type: ignore[assignment]
    Display = None  # type: ignore[assignment]
    _DISPLAY_AVAILABLE = False


_TOOL_INPUT_LOG_LIMIT = 200


def _summarize_tool_input(tool_input: Any) -> str:
    """Compact one-line rendering of tool arguments for the tool_call log.

    Truncates at _TOOL_INPUT_LOG_LIMIT so a take_snapshot dump or a long fill
    text doesn't drown the line, but keeps enough to reveal things like
    timeout=0 or empty selectors during diagnosis.
    """
    if not tool_input:
        return '{}'
    try:
        rendered = json.dumps(tool_input, ensure_ascii=False, sort_keys=True)
    except (TypeError, ValueError):
        rendered = repr(tool_input)
    if len(rendered) > _TOOL_INPUT_LOG_LIMIT:
        rendered = rendered[:_TOOL_INPUT_LOG_LIMIT] + '…'
    return rendered


class _DisplayProgressBridge:
    """Maps engine events to logs and Display task rows."""

    @staticmethod
    def _log_tool_result(tool_name: str, result: Any) -> None:
        content = (str(getattr(result, 'content', '') or ''))[:300].replace('\n', ' ')
        if getattr(result, 'is_error', False):
            log.error('❌ %s: %s', tool_name, content)
        else:
            log.info('✅ %s', tool_name)

    def __init__(
        self,
        *,
        enabled: bool,
        language: str,
        no_terminal_ui: bool,
        log_level: str,
    ) -> None:
        self.enabled = bool(enabled and _DISPLAY_AVAILABLE)
        self._case_name = 'cc-mini case'
        self._case_tracker: Any | None = None
        self._case_finished = False
        self._started = False
        if not self.enabled:
            return

        try:
            if GetLog is not None:
                GetLog.get_log(log_level=log_level, stdout=no_terminal_ui)
            Display.init(language=language, no_terminal_ui=no_terminal_ui)
            try:
                Display.display.start()
                self._started = True
            except RuntimeError:
                Display.display._bind_stream_handler()
            self._case_tracker = Display.display(self._case_name)  # pylint: disable=not-callable
            self._case_tracker.__enter__()
        except Exception as exc:
            log.warning('Display progress init failed, fallback to no-display mode: %s', exc)
            self.enabled = False

    def on_event(self, evt: tuple) -> None:
        if not self.enabled or not evt:
            return
        kind = evt[0]
        if kind == 'tool_call':
            name = str(evt[3] if len(evt) > 3 and evt[3] else evt[1] if len(evt) > 1 else 'tool')
            log.info('🔧 %s', name)
        elif kind == 'tool_result':
            tool_name = str(evt[1] if len(evt) > 1 else 'tool')
            result = evt[3] if len(evt) > 3 else None
            self._log_tool_result(tool_name, result)
        elif kind == 'usage':
            usage = evt[1] if len(evt) > 1 else None
            log.info(
                '📊 usage input=%s output=%s',
                int(getattr(usage, 'input_tokens', 0) or 0),
                int(getattr(usage, 'output_tokens', 0) or 0),
            )
        elif kind == 'error':
            msg = str(evt[1] if len(evt) > 1 else '')
            log.error('⚠️ %s', msg)

    def finish(
        self, *, aborted: bool = False, steps: list | None = None,
        final_text: str = '',
    ) -> None:
        if not self.enabled or self._case_finished or self._case_tracker is None:
            return
        failed = sum(1 for s in (steps or []) if getattr(s, 'is_error', False))
        outcome = extract_final_outcome(final_text)
        status_name, _ = derive_status(
            aborted=aborted, failed_count=failed, outcome=outcome,
        )
        self._case_tracker.result = status_name if status_name in ('passed', 'warning', 'failed') else 'failed'
        if aborted:
            self._case_tracker.__exit__(
                Exception, Exception('cc-mini execution failed'), None,
            )
        else:
            self._case_tracker.__exit__(None, None, None)
        self._case_finished = True

    def close(self) -> None:
        if not self.enabled:
            return
        if not self._case_finished:
            self.finish(aborted=True)
        if self._started:
            try:
                import asyncio
                try:
                    loop = asyncio.get_running_loop()
                except RuntimeError:
                    loop = None
                if loop is not None and loop.is_running():
                    loop.create_task(Display.display.stop())
                else:
                    asyncio.run(Display.display.stop())
            except Exception:
                pass


@dataclass
class ToolCall:
    tool: str
    input: dict
    result: str
    is_error: bool
    start_ts: float = 0.0
    end_ts: float = 0.0


@dataclass
class Step:
    description: str                                   # agent's natural-language narration
    tool_calls: list[ToolCall] = field(default_factory=list)
    screenshots: list[dict[str, str]] = field(default_factory=list)
    timestamp: float = field(default_factory=time.time)
    end_ts: float = 0.0
    input_tokens: int = 0
    output_tokens: int = 0

    # Convenience properties so adapter / report code can still read these
    @property
    def tool(self) -> str:
        return self.tool_calls[0].tool if self.tool_calls else ''

    @property
    def input(self) -> dict:
        return self.tool_calls[0].input if self.tool_calls else {}

    @property
    def result(self) -> str:
        return self.tool_calls[0].result if self.tool_calls else ''

    @property
    def is_error(self) -> bool:
        return any(tc.is_error for tc in self.tool_calls)


@dataclass
class RunResult:
    final_text: str
    steps: list[Step] = field(default_factory=list)
    aborted: bool = False
    input_tokens: int = 0
    output_tokens: int = 0
    extensions_failed: list[str] = field(default_factory=list)
    data_flow_events: list[dict[str, Any]] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Event-loop state and pure dispatchers
# ---------------------------------------------------------------------------

@dataclass
class _EventLoopState:
    """Mutable state owned by the engine-events consumer loop."""
    steps: list[Step] = field(default_factory=list)
    pending: deque[dict[str, Any]] = field(default_factory=deque)
    pending_turn_metrics: deque[dict[str, int]] = field(default_factory=deque)
    agent_text_buf: list[str] = field(default_factory=list)
    cur_step: Step | None = None
    total_tokens: dict[str, int] = field(default_factory=lambda: {'input': 0, 'output': 0})
    last_input_tokens: int = 0
    seen_usage: bool = False
    data_flow_events: list[dict] = field(default_factory=list)


def _attach_pending_metrics_to(step: Step, pending_turn_metrics: deque[dict[str, int]]) -> None:
    if pending_turn_metrics and step.input_tokens == 0 and step.output_tokens == 0:
        m = pending_turn_metrics.popleft()
        step.input_tokens = int(m.get('input_tokens', 0))
        step.output_tokens = int(m.get('output_tokens', 0))


def _handle_event(
    evt: tuple,
    state: _EventLoopState,
    *,
    screenshot_root: Path | None = None,
    data_flow_sink: DataFlowSink | None = None,
) -> None:
    """Apply one engine event to *state*.

    Pure dispatcher: does not perform abort / time / iteration checks (those
    stay in the outer ``run_cc_mini`` loop). Logging and screenshot
    persistence still happen here.
    """
    kind = evt[0]
    if kind == 'tool_call':
        state.pending.append({'tool': evt[1], 'input': evt[2], 'ts': time.time()})
        log.info('tool_call: %s %s', evt[1], _summarize_tool_input(evt[2]))

    elif kind == 'data_flow_event':
        event = evt[1] if len(evt) > 1 and isinstance(evt[1], dict) else {}
        if event:
            state.data_flow_events.append(event)
            if data_flow_sink is not None:
                try:
                    data_flow_sink(event)
                except Exception as sink_exc:
                    log.warning('data_flow_sink raised: %s', sink_exc)

    elif kind == 'tool_result':
        tool_result = evt[3]
        if state.pending:
            p = state.pending.popleft()
            ended_at = time.time()
            step_index = len(state.steps) + 1
            if state.cur_step is None:
                state.cur_step = Step(description='', timestamp=p.get('ts', time.time()))
                _attach_pending_metrics_to(state.cur_step, state.pending_turn_metrics)
            screenshots = _persist_step_screenshots(
                tool_result=tool_result,
                step_index=step_index,
                screenshot_root=screenshot_root,
                image_index_start=len(state.cur_step.screenshots),
            )
            tc = ToolCall(
                tool=p['tool'],
                input=p['input'],
                result=tool_result.content,
                is_error=tool_result.is_error,
                start_ts=p.get('ts', ended_at),
                end_ts=ended_at,
            )
            state.cur_step.tool_calls.append(tc)
            state.cur_step.screenshots.extend(screenshots)
            state.cur_step.end_ts = max(state.cur_step.end_ts, ended_at)

        if tool_result.is_error:
            snippet = (tool_result.content or '')[:200]
            log.warning('tool_error [%s]: %s', evt[1], snippet)
        else:
            snippet = (tool_result.content or '')[:300].replace('\n', ' ')
            log.info('tool_result [%s]: %s', evt[1], snippet)

    elif kind == 'error':
        log.error('engine error: %s', evt[1] if len(evt) > 1 else '?')

    elif kind == 'text':
        chunk = str(evt[1] if len(evt) > 1 else '')
        if chunk:
            state.agent_text_buf.append(chunk)

    elif kind == 'waiting':
        # POST-FIX (Bug 1): do NOT backfill description on the step we are
        # flushing — that text belongs to the UPCOMING step's tool calls.
        description = ''.join(state.agent_text_buf).strip()
        state.agent_text_buf.clear()
        if description:
            log.info('agent: %s', description)
        if state.cur_step is not None:
            state.cur_step.end_ts = state.cur_step.end_ts or time.time()
            state.steps.append(state.cur_step)
            state.cur_step = None
        state.cur_step = Step(description=description)
        _attach_pending_metrics_to(state.cur_step, state.pending_turn_metrics)

    elif kind == 'usage':
        u = evt[1]
        state.seen_usage = True
        input_tokens = int(getattr(u, 'input_tokens', 0) or 0)
        output_tokens = int(getattr(u, 'output_tokens', 0) or 0)
        state.last_input_tokens = input_tokens
        state.total_tokens['input'] += input_tokens
        state.total_tokens['output'] += output_tokens
        metrics = {'input_tokens': input_tokens, 'output_tokens': output_tokens}
        if (
            state.cur_step is not None
            and state.cur_step.input_tokens == 0
            and state.cur_step.output_tokens == 0
        ):
            state.cur_step.input_tokens = input_tokens
            state.cur_step.output_tokens = output_tokens
        else:
            state.pending_turn_metrics.append(metrics)


def _finalize_steps(state: _EventLoopState) -> None:
    """Flush the in-progress step when the engine loop ends.

    Drops trailing pure-text turns (no tool_calls). The final summary
    text reaches the report via ``RunResult.final_text`` → the case-level
    ``final_summary`` field that the frontend renders as the Summary card
    at the top, so including it again as a Step would be redundant.
    """
    if state.cur_step is not None and state.cur_step.tool_calls:
        state.cur_step.end_ts = state.cur_step.end_ts or time.time()
        state.steps.append(state.cur_step)
        state.cur_step = None


def run_cc_mini(
    url: str,
    user_input: str,
    *,
    worker_id: int = 0,
    provider: str | None = None,
    model: str | None = None,
    api_key: str | None = None,
    base_url: str | None = None,
    effort: str | None = None,
    temperature: float | None = None,
    top_p: float | None = None,
    max_tokens: int | None = None,
    timeout: float | None = None,
    mcp_servers: list[MCPServerConfig] | None = None,
    skills_dir: str | Path | None = None,
    file_catalog: str | None = None,
    max_iterations: int = 50,
    max_time_seconds: float | None = None,
    save_screenshots: bool = False,
    screenshot_dir: str | Path | None = None,
    browser_headless: bool = False,
    browser_viewport: tuple[int, int] | None = None,
    enable_display_progress: bool = False,
    progress_language: str = 'zh-CN',
    progress_no_terminal_ui: bool = True,
    progress_log_level: str = 'info',
    on_event: EventCallback | None = None,
    data_flow_sink: DataFlowSink | None = None,
    extra_tools: list[Tool] | None = None,
    pre_engine_hook: Callable[['MCPManager', int], None] | None = None,
    extra_section: str | None = None,
    filter_model: str | None = None,
) -> RunResult:
    """Run the web agent on *url* with *user_input* and return a RunResult.

    Parameters
    ----------
    url:
        Target URL to navigate to.
    user_input:
        Task description for the agent.
    worker_id:
        Unique integer identifier for this worker — used to assign an
        isolated Chromium profile directory and remote debugging port so
        multiple concurrent calls don't conflict.
    provider:
        LLM provider: ``"anthropic"`` (default) or ``"openai"``.
    model:
        Model ID or alias (e.g. ``"sonnet"``, ``"gpt-4o"``).
    api_key:
        API key. If None, read from ``ANTHROPIC_API_KEY`` / ``OPENAI_API_KEY``.
    base_url:
        Custom API base URL for OpenAI-compatible backends (Ollama, vLLM, etc.).
    effort:
        Reasoning effort: ``"low"``, ``"medium"``, or ``"high"``.
        Maps to Anthropic thinking budget / OpenAI reasoning_effort.
    temperature:
        Sampling temperature passed to the LLM API. Provider default used when None.
    top_p:
        Top-p nucleus sampling parameter passed to the LLM API. Provider default used when None.
    max_tokens:
        Maximum number of output tokens per API call. Derived from model when None.
    timeout:
        HTTP request timeout in seconds for LLM API calls. Provider default (600 s) when None.
    mcp_servers:
        List of ``MCPServerConfig`` instances. Defaults to a chrome-devtools-mcp
        instance with an isolated profile and port derived from *worker_id*.
    skills_dir:
        Optional directory containing skill subdirectories (each with a
        ``SKILL.md`` frontmatter file). When provided, skills are discovered,
        their names + descriptions are injected into the system prompt, and a
        ``load_skill`` tool is added so the LLM can fetch the full body on
        demand (Progressive Disclosure).
    file_catalog:
        Optional LLM-readable catalog of test files available for upload
        testing. When provided, it is appended to the system prompt along
        with instructions telling the agent to use the browser MCP server's
        ``upload_file`` tool (``mcp__browser__upload_file`` with the default
        server name) whenever it encounters a file-upload control. The
        caller is expected to produce the catalog string (e.g. via
        ``webqa_agent.utils.test_file_library.TestFileLibrary``) — cc-mini
        itself does not scan the filesystem, so the absolute paths in the
        catalog must already match what the browser can read.
    max_iterations:
        Hard limit on the number of tool steps before aborting.
    max_time_seconds:
        Wall-clock time limit in seconds. When exceeded the run is
        aborted gracefully. ``None`` (default) means no time limit.
    on_event:
        Optional callback ``fn(event_tuple)`` called for every engine event.
        Exceptions in the callback are caught and logged; they never propagate.
    extra_tools:
        Additional native ``Tool`` instances appended to the engine's tool
        list. Generic extension point — caller owns the Tool implementation.
        Tools may optionally implement ``bind_mcp(server, port)`` to receive
        the MCP server reference and CDP port after the MCP subprocess is up
        but before the engine loop starts. See ``features.cookies`` for a
        concrete example (``SwitchAccountTool``).
    pre_engine_hook:
        Optional callback ``fn(mcp_manager, cdp_port)`` invoked after the MCP
        server is up and a ``new_page`` call has forced Chromium to start,
        but before the engine loop begins. Generic extension point — caller
        owns the hook implementation. Exceptions are caught and recorded in
        ``RunResult.extensions_failed``; the run continues without the
        hook's effects.
    extra_section:
        Optional string appended verbatim to the end of the system prompt
        (after skills / file-upload sections). Generic extension point for
        caller-provided prompt augmentation.
    filter_model:
        Model ID for the independent verification tool (``verify``). Uses a
        separate, cheaper LLM call to judge assertions against page evidence,
        countering self-verification bias. When ``None`` (default), inherits
        the main ``model``. The provider is auto-detected from the model name
        (``claude-*`` → Anthropic, everything else → OpenAI-compatible).

    Known failure modes
    -------------------
    * Port collision (port ``9222 + worker_id`` already bound by another
      Chromium instance) → MCP server fails to start with ``Critical MCP
      server 'browser' failed to start``. Check ``lsof -iTCP:9222`` or
      increment ``worker_id``.
    * ``worker_id`` outside ``[0, 56313]`` raises ``ValueError`` immediately —
      the sum ``9222 + worker_id`` must stay within the 1024–65535 port range.
    """
    if not (0 <= worker_id <= 56313):
        raise ValueError(
            f'worker_id={worker_id} produces port outside 1024-65535 valid range '
            '(must be in [0, 56313])'
        )

    aborted = False

    provider = provider or DEFAULT_PROVIDER
    model = model or DEFAULT_MODEL

    profile = tempfile.mkdtemp(prefix=f'cc-mini-w{worker_id}-')
    download_dir = os.path.join(profile, 'downloads')
    os.makedirs(download_dir, exist_ok=True)
    # Set Chrome download directory via Preferences file.
    # The --download-default-directory CLI flag is unreliable with CDP;
    # Chrome reads download.default_directory from the profile prefs.
    _write_chrome_download_prefs(profile, download_dir)
    if mcp_servers is None:
        mcp_servers = _default_browser_mcp(
            profile, worker_id, headless=browser_headless,
            viewport=browser_viewport,
        )
    cdp_required = (
        pre_engine_hook is not None
        or any(hasattr(t, 'bind_mcp') for t in (extra_tools or []))
    )

    mcp = MCPManager(mcp_servers)
    screenshot_root = _prepare_screenshot_dir(
        save_screenshots=save_screenshots,
        screenshot_dir=screenshot_dir,
    )

    def _emergency_cleanup() -> None:
        try:
            mcp.shutdown_all()
        except Exception:
            pass
        try:
            shutil.rmtree(profile, ignore_errors=True)
        except Exception:
            pass

    atexit.register(_emergency_cleanup)

    _prev_sigterm: Any = None
    _prev_sighup: Any = None
    _signals_installed = False
    try:
        _prev_sigterm = signal.getsignal(signal.SIGTERM)
        _prev_sighup = signal.getsignal(signal.SIGHUP)

        def _signal_handler(signum: int, frame: Any) -> None:
            sys.exit(128 + signum)

        signal.signal(signal.SIGTERM, _signal_handler)
        signal.signal(signal.SIGHUP, _signal_handler)
        _signals_installed = True
    except ValueError:
        pass

    engine: Engine | None = None
    state = _EventLoopState()
    display_bridge = _DisplayProgressBridge(
        enabled=enable_display_progress,
        language=progress_language,
        no_terminal_ui=progress_no_terminal_ui,
        log_level=progress_log_level,
    )
    _run_result: RunResult | None = None
    cdp_port = _resolve_cdp_port(mcp_servers, worker_id)
    extensions_failed: list[str] = []

    try:
        _ensure_cdp_port_available_for_extensions(
            mcp_servers, cdp_required=cdp_required)
        tools = mcp.start_and_collect_tools()

        # Replace chrome-devtools-mcp's upload_file with our CDPUploadTool.
        # The MCP version routes through the native file-chooser intercept,
        # which depends on the trigger element being click-reachable from
        # the a11y tree — fragile on pages with hidden inputs or icon-only
        # paperclip triggers (the agent loops trying to click and never
        # finds the chooser). Filtering removes that failure mode entirely
        # so the agent has only one upload path: cdp_upload_file.
        _filtered_upload = [
            t for t in tools if t.name == 'mcp__browser__upload_file'
        ]
        if _filtered_upload:
            tools = [
                t for t in tools if t.name != 'mcp__browser__upload_file'
            ]
            log.info(
                'Filtered out MCP upload_file (%d tool); use cdp_upload_file '
                'instead.', len(_filtered_upload),
            )

        skill_metadata = []
        if skills_dir is not None:
            skill_registry = SkillRegistry(Path(skills_dir))
            skill_registry.discover()
            skill_metadata = skill_registry.list_metadata()
            if skill_metadata:
                tools = list(tools) + [LoadSkillTool(skill_registry)]
                names = ', '.join(m.name for m in skill_metadata)
                log.info('Skills discovered (%d): %s', len(skill_metadata), names)
            else:
                log.info('Skills dir %s exists but no valid skills found', skills_dir)

        browser_server = mcp._servers.get('browser')
        # chrome-devtools-mcp launches Chromium lazily; list_pages (read-only)
        # forces managed Chrome up so the CDP port binds before any extension
        # tries to connect to it directly.
        if cdp_required:
            if browser_server is None:
                extensions_failed.append(
                    'CDP extensions require the browser MCP server, but it '
                    'was not started.')
            else:
                try:
                    _ensure_tool_result_ok(
                        browser_server.call_tool('list_pages', {}),
                        context='browser list_pages',
                    )
                    _ensure_managed_cdp_endpoint_ready(
                        mcp_servers,
                        profile=Path(profile),
                        cdp_required=True,
                    )
                except Exception as exc:
                    extensions_failed.append(f'browser force-start: {exc}')

        if pre_engine_hook is not None:
            if cdp_port is None:
                msg = (
                    'pre_engine_hook: CDP port could not be resolved from '
                    'mcp_servers. Pass --browser-url, --ws-endpoint, or '
                    '--chrome-arg=--remote-debugging-port=N in your custom '
                    'MCP config to enable cookie-style extensions.'
                )
                extensions_failed.append(msg)
            else:
                try:
                    pre_engine_hook(mcp, cdp_port)
                except Exception as exc:
                    extensions_failed.append(
                        f'pre_engine_hook failed: {exc}',
                    )

        if extra_tools:
            for t in extra_tools:
                if browser_server is not None and hasattr(t, 'bind_mcp'):
                    tool_name = getattr(t, 'name', type(t).__name__)
                    if cdp_port is None:
                        msg = (
                            f'bind_mcp {tool_name}: CDP port unresolved; '
                            'tool will refuse CDP-dependent calls. '
                            'Provide --browser-url / --ws-endpoint / '
                            '--chrome-arg=--remote-debugging-port=N.'
                        )
                        extensions_failed.append(msg)
                    try:
                        if cdp_port is not None:
                            t.bind_mcp(browser_server, cdp_port)
                    except Exception as exc:
                        extensions_failed.append(
                            f'bind_mcp {tool_name} failed: {exc}',
                        )
            tools = list(tools) + list(extra_tools)
        else:
            tools = list(tools)

        # Always add download verification tool
        tools.append(DownloadCheckTool(download_dir))

        # Always add NucleiScanTool for security checks
        tools.append(NucleiScanTool())

        # Direct-CDP file upload fallback. Binds to the CDP port when the
        # default browser MCP config is in use; for custom MCP configs that
        # don't expose a TCP debug port, the tool stays registered but fails
        # fast with a clear infrastructure error on invocation.
        upload_tool = CDPUploadTool()
        if browser_server is not None and cdp_port is not None:
            try:
                upload_tool.bind_mcp(browser_server, cdp_port)
            except Exception as exc:
                log.warning('cdp_upload_file: bind_mcp failed: %s', exc)
        tools.append(upload_tool)

        # Add DOM stability tool (for streaming output, async loads)
        if browser_server is not None:
            tools.append(WaitForDomStableTool(browser_server))

        # Add independent verification tool (always registered)
        if browser_server is not None:
            _filter_model = filter_model.strip() if filter_model else model
            _filter_provider = infer_provider_from_model(_filter_model)
            _filter_base_url = base_url if _filter_provider == provider else None
            filter_client = LLMClient(
                provider=_filter_provider,
                api_key=api_key,
                base_url=_filter_base_url,
                timeout=timeout,
            )
            tools.append(
                VerifyTool(browser_server, filter_client, _filter_model),
            )
            if _filter_model == model:
                log.warning(
                    'Verify tool: filter_model equals main model (%s); '
                    'set a different filter_model for better bias reduction.',
                    model,
                )
            log.info('Verify tool registered with model=%s (provider=%s)',
                     _filter_model, _filter_provider)

        system = build_web_agent_system_prompt(
            target_url=url,
            task=user_input,
            skills=skill_metadata or None,
            file_catalog=(file_catalog.strip() if isinstance(file_catalog, str) and file_catalog.strip() else None),
            extra_section=extra_section,
            has_verify_tool=browser_server is not None,
        )
        engine = Engine(
            tools=tools,
            system_prompt=system,
            permission_checker=PermissionChecker(),
            provider=provider,
            model=model,
            api_key=api_key,
            base_url=base_url,
            effort=effort,
            temperature=temperature,
            top_p=top_p,
            max_tokens=max_tokens,
            timeout=timeout,
        )
        compact = CompactService(
            client=engine._client,
            model=engine.get_model(),
            effort=effort,
        )

        def _maybe_compact(last_input: int | None) -> None:
            messages = engine.get_messages()
            if should_compact(messages, engine.get_model(), last_input):
                new_msgs, _ = compact.compact(messages, engine.system_prompt)
                engine.set_messages(new_msgs)
                state.last_input_tokens = 0  # reset so compaction doesn't re-fire

        def _on_context_overflow(messages: list[dict]) -> list[dict] | None:
            """Force-compact when the LLM rejects the request as too long.

            Engine calls this *during* its retry loop on
            ``context_length_exceeded``. We run the same summarisation as
            the soft auto-compact path; if it actually shrinks the
            history, the engine retries with the smaller payload. If it
            can't shrink, we return ``None`` so the engine falls back to
            its legacy ``max_tokens`` halving.
            """
            try:
                new_msgs, _ = compact.compact(messages, engine.system_prompt)
            except Exception as exc:
                log.warning('Force-compact during overflow failed: %s', exc)
                return None
            if not new_msgs or len(new_msgs) >= len(messages):
                return None
            state.last_input_tokens = 0  # next usage event won't immediately re-fire
            return new_msgs

        engine.set_context_overflow_handler(_on_context_overflow)

        seed = (
            f'Target URL: {url}\n\n'
            f'Task: {user_input}\n\n'
            'Begin by navigating to the URL.'
        )

        run_start_time = time.monotonic()

        for evt in engine.submit(seed):
            if max_time_seconds is not None:
                elapsed = time.monotonic() - run_start_time
                if elapsed >= max_time_seconds:
                    log.warning(
                        'Time limit reached (%.0fs >= %.0fs), aborting.',
                        elapsed, max_time_seconds,
                    )
                    engine.abort()
                    aborted = True
                    break

            display_bridge.on_event(evt)
            if on_event is not None:
                try:
                    on_event(evt)
                except Exception as cb_exc:
                    log.warning('on_event callback raised: %s', cb_exc)

            _handle_event(
                evt, state,
                screenshot_root=screenshot_root,
                data_flow_sink=data_flow_sink,
            )

            # Compaction triggers stay outside _handle_event (needs engine closure)
            if evt[0] == 'tool_result' and not state.seen_usage:
                _maybe_compact(None)
            elif evt[0] == 'usage':
                _maybe_compact(state.last_input_tokens)

            if len(state.steps) >= max_iterations:
                engine.abort()
                aborted = True
                break

        _finalize_steps(state)

        failed = sum(1 for s in state.steps if s.is_error)
        log.info(
            'Run complete: %d steps (%d failed), %d↑ %d↓ tokens, aborted=%s',
            len(state.steps), failed,
            state.total_tokens['input'], state.total_tokens['output'],
            aborted,
        )
        _run_result = RunResult(
            final_text=engine.last_assistant_text(),
            steps=state.steps,
            aborted=aborted,
            input_tokens=state.total_tokens['input'],
            output_tokens=state.total_tokens['output'],
            extensions_failed=extensions_failed,
            data_flow_events=state.data_flow_events,
        )
        return _run_result

    except AbortedError:
        aborted = True
        _finalize_steps(state)
        _run_result = RunResult(
            final_text=engine.last_assistant_text() if engine is not None else '',
            steps=state.steps,
            aborted=True,
            input_tokens=state.total_tokens['input'],
            output_tokens=state.total_tokens['output'],
            extensions_failed=extensions_failed,
            data_flow_events=state.data_flow_events,
        )
        return _run_result

    except Exception as exc:
        aborted = True
        _finalize_steps(state)
        log.error('cc-mini aborted due to exception: %s', exc, exc_info=True)
        _run_result = RunResult(
            final_text=f'Error: {exc}',
            steps=state.steps,
            aborted=True,
            input_tokens=state.total_tokens['input'],
            output_tokens=state.total_tokens['output'],
            extensions_failed=extensions_failed,
            data_flow_events=state.data_flow_events,
        )
        return _run_result

    finally:
        _ft = ''
        if _run_result is not None:
            _ft = _run_result.final_text or ''
        elif engine is not None:
            try:
                _ft = engine.last_assistant_text() or ''
            except Exception:
                _ft = ''
        display_bridge.finish(
            aborted=aborted, steps=state.steps, final_text=_ft,
        )
        display_bridge.close()
        try:
            mcp.shutdown_all()
        except Exception as exc:
            log.warning('MCP shutdown error: %s', exc)
        try:
            shutil.rmtree(profile, ignore_errors=True)
        except Exception:
            pass
        atexit.unregister(_emergency_cleanup)
        if _signals_installed:
            signal.signal(signal.SIGTERM, _prev_sigterm)
            signal.signal(signal.SIGHUP, _prev_sighup)


def _resolve_cdp_port(
    mcp_servers: list[MCPServerConfig],
    worker_id: int,
) -> int | None:
    """Best-effort derivation of the CDP port from MCP server config.

    Extension points that need the CDP port (e.g. the cookies feature)
    connect to it directly; the port must match whatever Chromium is
    actually listening on. When the caller provides a custom ``mcp_servers``
    we can't assume ``9222 + worker_id`` — we parse the args instead.

    Priority (first match wins):

    1. ``--browser-url=ws://HOST:PORT/...`` or ``--browserUrl=…`` — explicit
       CDP WebSocket endpoint.
    2. ``--ws-endpoint=ws://HOST:PORT/...`` or ``--wsEndpoint=…`` — alternate
       spelling accepted by chrome-devtools-mcp.
    3. ``--chrome-arg=--remote-debugging-port=N`` — the wrapped form that
       actually reaches Chromium (unwrapped ``--remote-debugging-port`` is
       silently dropped by yargs; see ``_default_browser_mcp`` note).
    4. Default ``9222 + worker_id`` — returned only when the only MCP
       server is our own default (name == 'browser').

    Returns ``None`` when no port can be derived and the config is custom;
    callers should record this in ``extensions_failed`` rather than guess.
    """
    browser_cfg = next(
        (s for s in mcp_servers if getattr(s, 'name', None) == 'browser'),
        None,
    )
    if browser_cfg is None:
        return None
    args = tuple(browser_cfg.args or ())

    def _port_from_url(raw: str) -> int | None:
        # Accepts ws://host:port/path or http://host:port/... — only the
        # authority is parsed, we don't care about scheme or path here.
        rest = raw.split('://', 1)[-1]
        authority = rest.split('/', 1)[0]
        _, _, port_part = authority.partition(':')
        try:
            return int(port_part) if port_part else None
        except ValueError:
            return None

    url = _flag_value(args, ('--browser-url', '--browserUrl'))
    if url:
        p = _port_from_url(url)
        if p is not None:
            return p

    ws = _flag_value(args, ('--ws-endpoint', '--wsEndpoint'))
    if ws:
        p = _port_from_url(ws)
        if p is not None:
            return p

    for arg in args:
        if arg.startswith('--chrome-arg=--remote-debugging-port='):
            try:
                return int(arg.rsplit('=', 1)[1])
            except ValueError:
                continue

    # Custom callers must pass an explicit endpoint or forgo the cookies feature.
    return None


def _ensure_cdp_port_available_for_extensions(
    mcp_servers: list[MCPServerConfig],
    *,
    cdp_required: bool,
) -> None:
    """Fail fast if CDP extensions would connect to an old browser instance.

    chrome-devtools-mcp can control its managed browser over its own transport
    even when the extra TCP CDP port cannot bind. Cookie extensions, however,
    connect directly to that TCP port. If the port is already owned by another
    Chrome process, cookies are injected into the wrong browser.
    """
    if not cdp_required:
        return

    endpoint = _managed_cdp_endpoint(mcp_servers)
    if endpoint is None:
        return

    host, port = endpoint
    if _can_bind_tcp_port(host, port):
        return

    raise RuntimeError(
        f'CDP port {host}:{port} is already in use before cc-mini starts '
        'its managed Chrome. Cookie/account extensions would connect to that '
        'existing browser instead of the test browser. Stop the existing '
        f'process (for example: ss -ltnp | grep ":{port}") or choose a '
        'different worker_id/custom --chrome-arg=--remote-debugging-port=N. '
        'If you intentionally want to attach to an existing browser, configure '
        '--browser-url or --ws-endpoint so MCP and cookie injection target the '
        'same instance.'
    )


def _ensure_tool_result_ok(result: Any, *, context: str) -> None:
    if getattr(result, 'is_error', False):
        content = str(getattr(result, 'content', '') or '').strip()
        detail = f': {content}' if content else ''
        raise RuntimeError(f'{context} failed{detail}')


def _ensure_managed_cdp_endpoint_ready(
    mcp_servers: list[MCPServerConfig],
    *,
    profile: Path,
    cdp_required: bool,
) -> None:
    """Verify managed Chrome exposed the expected fixed CDP endpoint."""
    if not cdp_required:
        return

    endpoint = _managed_cdp_endpoint(mcp_servers)
    if endpoint is None:
        return

    host, expected_port = endpoint
    _probe_cdp_http_endpoint(host, expected_port)

    active_port = _read_devtools_active_port(profile, expected_port)
    if active_port is not None and active_port != expected_port:
        raise RuntimeError(
            f'DevToolsActivePort in {profile} reported port {active_port}, '
            f'expected {expected_port}. Cookie/account extensions would not '
            'target the same browser controlled by MCP.'
        )


def _read_devtools_active_port(profile: Path, expected_port: int) -> int | None:
    port_file = profile / 'DevToolsActivePort'
    if not port_file.exists():
        return None

    try:
        first_line = port_file.read_text(encoding='utf-8').splitlines()[0]
        return int(first_line.strip())
    except (IndexError, ValueError) as exc:
        raise RuntimeError(
            f'DevToolsActivePort in {profile} is malformed; cannot verify '
            'the CDP endpoint for cookie/account extensions.'
        ) from exc


def _probe_cdp_http_endpoint(host: str, port: int) -> None:
    conn = http.client.HTTPConnection(host, port, timeout=3.0)
    try:
        conn.request('GET', '/json/version')
        resp = conn.getresponse()
        if resp.status != 200:
            raise RuntimeError(
                f'CDP endpoint {host}:{port} returned HTTP {resp.status} '
                'for /json/version.'
            )
        body = resp.read()
    except OSError as exc:
        raise RuntimeError(
            f'CDP endpoint {host}:{port} is not reachable after Chrome launch.'
        ) from exc
    finally:
        conn.close()

    try:
        ws_url = json.loads(body).get('webSocketDebuggerUrl', '')
    except ValueError as exc:
        raise RuntimeError(
            f'CDP endpoint {host}:{port} returned invalid /json/version JSON.'
        ) from exc
    if f':{port}/' not in ws_url:
        raise RuntimeError(
            f'CDP endpoint {host}:{port} returned unexpected WebSocket URL.'
        )


def _managed_cdp_endpoint(
    mcp_servers: list[MCPServerConfig],
) -> tuple[str, int] | None:
    """Return the TCP CDP endpoint only when MCP is launching Chrome itself."""
    browser_cfg = next(
        (s for s in mcp_servers if getattr(s, 'name', None) == 'browser'),
        None,
    )
    if browser_cfg is None:
        return None

    args = tuple(browser_cfg.args or ())
    if _flag_value(args, ('--browser-url', '--browserUrl')):
        return None
    if _flag_value(args, ('--ws-endpoint', '--wsEndpoint')):
        return None

    port: int | None = None
    for arg in args:
        if not arg.startswith('--chrome-arg=--remote-debugging-port='):
            continue
        try:
            port = int(arg.rsplit('=', 1)[1])
        except ValueError:
            return None
        break
    if port is None:
        return None

    host = '127.0.0.1'
    address = _chrome_arg_value(args, '--remote-debugging-address')
    if address:
        host = address
    return host, port


def _flag_value(args: tuple[str, ...], flag_names: tuple[str, ...]) -> str | None:
    for arg in args:
        for name in flag_names:
            if arg.startswith(f'{name}='):
                return arg.split('=', 1)[1]
            if arg == name:
                return None
    return None


def _chrome_arg_value(args: tuple[str, ...], chrome_flag_name: str) -> str | None:
    prefix = f'--chrome-arg={chrome_flag_name}='
    for arg in args:
        if arg.startswith(prefix):
            return arg.split('=', 2)[2]
    return None


def _can_bind_tcp_port(host: str, port: int) -> bool:
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        sock.bind((host, port))
    except OSError as exc:
        if exc.errno == errno.EADDRINUSE:
            return False
        raise RuntimeError(
            f'Failed to verify CDP port availability for {host}:{port}: {exc}'
        ) from exc
    finally:
        sock.close()
    return True


def _default_browser_mcp(
    profile: str, worker_id: int, *, headless: bool = False,
    viewport: tuple[int, int] | None = None,
) -> list[MCPServerConfig]:
    """Default MCP config: chrome-devtools-mcp with isolated profile and port.

    Prefers the globally-installed ``chrome-devtools-mcp`` binary (typical in
    Docker images built with ``npm install -g chrome-devtools-mcp``).  Falls
    back to ``npx chrome-devtools-mcp`` (without ``@latest``) to avoid forcing
    a network fetch in constrained environments.

    Security hardening:
      * ``--chrome-arg=--remote-debugging-address=127.0.0.1`` keeps the CDP
        port bound to loopback. CDP has no authentication — exposing the port
        externally lets any network peer read cookies and run arbitrary JS.
      * ``--no-usage-statistics`` disables chrome-devtools-mcp telemetry to
        Google Clearcut (on by default).

    Note on ``--remote-debugging-port``: chrome-devtools-mcp does NOT recognize
    this as a top-level CLI option — yargs silently drops unknown flags. The
    port must be wrapped as ``--chrome-arg=--remote-debugging-port=N`` so it
    reaches Chromium via the ``chromeArgs`` array (chrome-devtools-mcp uses
    Puppeteer ``pipe: true`` by default, so without this wrapper Chromium
    never exposes a TCP CDP port for the cookie injection client to connect).
    """
    mcp_args = [
        f'--user-data-dir={profile}',
        '--chrome-arg=--no-sandbox',
        '--chrome-arg=--disable-dev-shm-usage',
        '--chrome-arg=--remote-debugging-address=127.0.0.1',
        f'--chrome-arg=--remote-debugging-port={9222 + worker_id}',
        '--no-usage-statistics',
        '--experimentalVision',
    ]
    exe_path = os.getenv('PUPPETEER_EXECUTABLE_PATH')
    if exe_path:
        mcp_args.append(f'--executablePath={exe_path}')
    if headless:
        mcp_args.append('--headless')
    if viewport is not None:
        mcp_args.append(f'--viewport={viewport[0]}x{viewport[1]}')

    if shutil.which('chrome-devtools-mcp'):
        command = 'chrome-devtools-mcp'
        args = tuple(mcp_args)
    else:
        command = 'npx'
        args = ('-y', 'chrome-devtools-mcp', *mcp_args)

    return [
        MCPServerConfig(
            name='browser',
            command=command,
            args=args,
        )
    ]


def _prepare_screenshot_dir(
    *,
    save_screenshots: bool,
    screenshot_dir: str | Path | None,
) -> Path | None:
    if not save_screenshots or screenshot_dir is None:
        return None
    root = Path(screenshot_dir).resolve()
    root.mkdir(parents=True, exist_ok=True)
    return root


def _persist_step_screenshots(
    *,
    tool_result: Any,
    step_index: int,
    screenshot_root: Path | None,
    image_index_start: int = 0,
) -> list[dict[str, str]]:
    """Persist images from a tool result and return step-screenshot dicts.

    The URL embedded in each dict's ``data`` field is derived from
    ``screenshot_root``:

    * If ``screenshot_root`` is nested directly under a ``screenshots``
      directory (e.g. ``<report_dir>/screenshots/case_2``), the prefix is
      ``screenshots/<leaf>`` so multi-case batches end up with paths the
      report frontend accepts (it requires URLs starting with
      ``screenshots/``).
    * Otherwise the prefix is just the leaf name (the legacy single-case
      shape ``<report_dir>/screenshots`` → ``screenshots/<file>``).

    Callers don't have to pass any extra parameters: the directory layout
    they create on disk fully determines the URL.

    ``image_index_start`` is the number of screenshots already persisted for
    the current step.  Newly-written images are numbered starting *after* this
    offset, so passing ``image_index_start=2`` means the first new file will
    be ``step_NNN_03``.  The default of ``0`` preserves the original
    single-call behaviour (numbering from ``01``).
    """
    if screenshot_root is None:
        return []
    blocks = getattr(tool_result, 'content_blocks', None) or []
    if not isinstance(blocks, list):
        return []
    leaf = screenshot_root.name or 'screenshots'
    if screenshot_root.parent.name == 'screenshots':
        prefix_path = Path('screenshots') / leaf
    else:
        prefix_path = Path(leaf)
    screenshots: list[dict[str, str]] = []
    image_idx = image_index_start
    for block in blocks:
        if not isinstance(block, dict) or block.get('type') != 'image':
            continue
        data = block.get('data')
        if not isinstance(data, str) or not data:
            continue
        image_idx += 1
        mime = str(block.get('mimeType') or 'image/png')
        ext = _image_extension_from_mime(mime)
        file_name = f'step_{step_index:03d}_{image_idx:02d}.{ext}'
        file_path = screenshot_root / file_name
        try:
            file_path.write_bytes(base64.b64decode(data))
        except (ValueError, OSError):
            continue
        screenshots.append({
            'type': 'path',
            'data': str(prefix_path / file_name),
            'label': f'Step {step_index} screenshot {image_idx}',
        })
    return screenshots


def _image_extension_from_mime(mime: str) -> str:
    m = mime.lower()
    if 'jpeg' in m or 'jpg' in m:
        return 'jpg'
    if 'webp' in m:
        return 'webp'
    if 'gif' in m:
        return 'gif'
    return 'png'


def _write_chrome_download_prefs(profile_dir: str, download_dir: str) -> None:
    """Write Chrome Preferences to set the default download directory.

    Chrome reads ``download.default_directory`` from the profile's
    ``Default/Preferences`` JSON file. This is more reliable than the
    ``--download-default-directory`` CLI flag, which CDP-based tools
    (like chrome-devtools-mcp) may not respect.
    """
    default_dir = os.path.join(profile_dir, 'Default')
    os.makedirs(default_dir, exist_ok=True)
    prefs_path = os.path.join(default_dir, 'Preferences')

    prefs: dict = {}
    if os.path.exists(prefs_path):
        try:
            with open(prefs_path, 'r') as f:
                prefs = json.loads(f.read())
        except (json.JSONDecodeError, OSError):
            prefs = {}

    prefs.setdefault('download', {})
    prefs['download']['default_directory'] = download_dir
    prefs['download']['prompt_for_download'] = False

    with open(prefs_path, 'w') as f:
        f.write(json.dumps(prefs, indent=2))

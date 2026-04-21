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

import base64
import logging
import os
import shutil
import tempfile
import time
from collections import deque
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

# Event callback type for on_event parameter.
# Events are tuples where the first element is the event kind:
#   ("text", chunk_str)
#   ("waiting",)
#   ("tool_call", name, input_dict, activity_description)
#   ("tool_result", name, input_dict, ToolResult)
#   ("usage", usage_object)  — usage_object has input_tokens/output_tokens attrs
#   ("error", message_str)
EventCallback = Callable[[tuple[str, ...]], None]

from core.config import DEFAULT_MODEL, DEFAULT_PROVIDER, MCPServerConfig
from core.context import build_web_agent_system_prompt
from core.engine import AbortedError, Engine
from core.load_skill_tool import LoadSkillTool
from core.mcp_client import MCPManager
from core.permissions import PermissionChecker
from core.skill_registry import SkillRegistry
from features.compact import CompactService, should_compact

log = logging.getLogger('cc_mini.runner')

try:
    from webqa_agent.utils.get_log import GetLog
    from webqa_agent.utils.task_display_util import Display
    _DISPLAY_AVAILABLE = True
except Exception:
    GetLog = None  # type: ignore[assignment]
    Display = None  # type: ignore[assignment]
    _DISPLAY_AVAILABLE = False


class _DisplayProgressBridge:
    """Bridge cc-mini event stream to webqa Display progress model.

    """

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
        self._has_error = False
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
            self._case_tracker = Display.display(self._case_name)
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
            is_error = bool(getattr(result, 'is_error', False))
            content = str(getattr(result, 'content', '') or '')
            if is_error:
                self._has_error = True
                log.error('❌ %s: %s', tool_name, content[:300].replace('\n', ' '))
            else:
                log.info('✅ %s', tool_name)
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

    def finish(self, *, aborted: bool = False) -> None:
        if not self.enabled or self._case_finished or self._case_tracker is None:
            return
        self._case_tracker.result = 'failed' if (aborted or self._has_error) else 'passed'
        if aborted or self._has_error:
            self._case_tracker.__exit__(Exception, Exception('cc-mini execution failed'), None)
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
class Step:
    tool: str
    input: dict
    result: str
    is_error: bool
    screenshots: list[dict[str, str]] = field(default_factory=list)
    timestamp: float = field(default_factory=time.time)


@dataclass
class RunResult:
    final_text: str
    steps: list[Step] = field(default_factory=list)
    aborted: bool = False
    input_tokens: int = 0
    output_tokens: int = 0


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
    max_iterations: int = 50,
    max_time_seconds: float | None = None,
    save_screenshots: bool = False,
    screenshot_dir: str | Path | None = None,
    browser_headless: bool = False,
    enable_display_progress: bool = False,
    progress_language: str = 'zh-CN',
    progress_no_terminal_ui: bool = True,
    progress_log_level: str = 'info',
    on_event: EventCallback | None = None,
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
    max_iterations:
        Hard limit on the number of tool steps before aborting.
    max_time_seconds:
        Wall-clock time limit in seconds. When exceeded the run is
        aborted gracefully. ``None`` (default) means no time limit.
    on_event:
        Optional callback ``fn(event_tuple)`` called for every engine event.
        Exceptions in the callback are caught and logged; they never propagate.
    """
    aborted = False  # initialised before try so it's always defined

    # Resolve provider/model: explicit arg > built-in default.
    provider = provider or DEFAULT_PROVIDER
    model = model or DEFAULT_MODEL

    profile = tempfile.mkdtemp(prefix=f'cc-mini-w{worker_id}-')
    if mcp_servers is None:
        mcp_servers = _default_browser_mcp(
            profile, worker_id, headless=browser_headless,
        )

    mcp = MCPManager(mcp_servers)
    screenshot_root = _prepare_screenshot_dir(
        save_screenshots=save_screenshots,
        screenshot_dir=screenshot_dir,
    )

    engine: Engine | None = None
    steps: list[Step] = []
    # Cumulative totals — reported back in RunResult.
    total_tokens = {'input': 0, 'output': 0}
    # Last API call's input_tokens — drives compact decisions.
    # Must track the *latest* call (replace semantics), NOT a running sum;
    # should_compact() compares this to _auto_compact_threshold(model) and
    # accumulation would incorrectly re-trigger compaction every turn.
    last_input_tokens = 0
    # Flag: did we ever receive a "usage" event? If not (e.g. an OpenAI-compatible
    # backend that ignores stream_options={"include_usage": True}), we fall back
    # to estimate_tokens on "tool_result" events so compact still fires.
    seen_usage = False
    display_bridge = _DisplayProgressBridge(
        enabled=enable_display_progress,
        language=progress_language,
        no_terminal_ui=progress_no_terminal_ui,
        log_level=progress_log_level,
    )

    try:
        tools = mcp.start_and_collect_tools()

        # Optional skill discovery. Kept out of the MCP tool path: skills are
        # pure markdown instructions, not browser capabilities. Only the
        # load_skill surface is exposed to the LLM.
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

        system = build_web_agent_system_prompt(
            target_url=url,
            task=user_input,
            skills=skill_metadata or None,
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
            """Check & run compaction.

            Safe to call from any event handler:
            engine.submit() is yielded at this point, so set_messages() will
            be visible to the generator when it resumes.
            """
            nonlocal last_input_tokens
            messages = engine.get_messages()
            if should_compact(messages, engine.get_model(), last_input):
                new_msgs, _ = compact.compact(messages, engine.system_prompt)
                engine.set_messages(new_msgs)
                # Reset after compaction so we don't re-fire until the next
                # real API call reports a fresh input_tokens count.
                last_input_tokens = 0

        # FIFO queue for pairing parallel tool_call → tool_result events.
        # engine.py Phase 3 emits tool_result tuples in the same order as the
        # original batch, so a strict FIFO deque is always correct.
        pending: deque[dict] = deque()

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

            kind = evt[0]

            if kind == 'tool_call':
                # evt = ("tool_call", name, input_dict, activity)
                pending.append({'tool': evt[1], 'input': evt[2], 'ts': time.time()})
                log.debug('tool_call: %s', evt[1])

            elif kind == 'tool_result':
                # evt = ("tool_result", name, input_dict, ToolResult)
                tool_result = evt[3]
                if pending:
                    p = pending.popleft()
                    step_index = len(steps) + 1
                    screenshots = _persist_step_screenshots(
                        tool_result=evt[3],
                        step_index=step_index,
                        screenshot_root=screenshot_root,
                    )
                    steps.append(Step(
                        tool=p['tool'],
                        input=p['input'],
                        result=tool_result.content,
                        is_error=tool_result.is_error,
                        screenshots=screenshots,
                        timestamp=p.get('ts', time.time()),
                    ))
                if tool_result.is_error:
                    snippet = (tool_result.content or '')[:200]
                    log.warning('tool_error [%s]: %s', evt[1], snippet)

                # Fallback compact trigger: only runs when the provider never
                # emits "usage" (e.g. OpenAI-compatible backends that ignore
                # stream_options). Uses estimate_tokens (char-based) via
                # should_compact's fallback path (last_input=None).
                if not seen_usage:
                    _maybe_compact(None)

            elif kind == 'error':
                log.error('engine error: %s', evt[1] if len(evt) > 1 else '?')

            elif kind == 'usage':
                u = evt[1]
                seen_usage = True
                # last_input_tokens = this call only (replace semantics, used
                # to decide whether to compact — see comment where it's declared).
                # total_tokens["input"]  = sum of per-call input_tokens. Each
                # call re-sends the full history, so this matches what the
                # provider actually billed across the run.
                last_input_tokens = getattr(u, 'input_tokens', 0) or 0
                total_tokens['input'] += last_input_tokens
                total_tokens['output'] += getattr(u, 'output_tokens', 0) or 0

                # Primary compact trigger: fires exactly once per API call,
                # right after we get the authoritative input_tokens back from
                # the server. The engine is paused here between the response
                # and the assistant-message append, so set_messages() lands on
                # a stable boundary.
                _maybe_compact(last_input_tokens)

            if len(steps) >= max_iterations:
                engine.abort()
                aborted = True
                break

        failed = sum(1 for s in steps if s.is_error)
        log.info(
            'Run complete: %d steps (%d failed), %d↑ %d↓ tokens, aborted=%s',
            len(steps), failed,
            total_tokens['input'], total_tokens['output'],
            aborted,
        )
        return RunResult(
            final_text=engine.last_assistant_text(),
            steps=steps,
            aborted=aborted,
            input_tokens=total_tokens['input'],
            output_tokens=total_tokens['output'],
        )

    except AbortedError:
        aborted = True
        return RunResult(
            final_text=engine.last_assistant_text() if engine is not None else '',
            steps=steps,
            aborted=True,
            input_tokens=total_tokens['input'],
            output_tokens=total_tokens['output'],
        )

    except Exception as exc:
        aborted = True
        log.error('cc-mini aborted due to exception: %s', exc, exc_info=True)
        return RunResult(
            final_text=f"Error: {exc}",
            steps=steps,
            aborted=True,
            input_tokens=total_tokens['input'],
            output_tokens=total_tokens['output'],
        )

    finally:
        display_bridge.finish(aborted=aborted)
        display_bridge.close()
        try:
            mcp.shutdown_all()
        except Exception as exc:
            log.warning('MCP shutdown error: %s', exc)
        try:
            shutil.rmtree(profile, ignore_errors=True)
        except Exception:
            pass


def _default_browser_mcp(
    profile: str, worker_id: int, *, headless: bool = False,
) -> list[MCPServerConfig]:
    """Default MCP config: chrome-devtools-mcp with isolated profile and port.

    Prefers the globally-installed ``chrome-devtools-mcp`` binary (typical in
    Docker images built with ``npm install -g chrome-devtools-mcp``).  Falls
    back to ``npx chrome-devtools-mcp`` (without ``@latest``) to avoid forcing
    a network fetch in constrained environments.
    """
    mcp_args = [
        f'--user-data-dir={profile}',
        f'--remote-debugging-port={9222 + worker_id}',
        "--chrome-arg=--no-sandbox",
        "--chrome-arg=--disable-dev-shm-usage",
    ]
    exe_path = os.getenv('PUPPETEER_EXECUTABLE_PATH')
    if exe_path:
        mcp_args.append(f'--executablePath={exe_path}')
    if headless:
        mcp_args.append('--headless')

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
) -> list[dict[str, str]]:
    if screenshot_root is None:
        return []
    blocks = getattr(tool_result, 'content_blocks', None) or []
    if not isinstance(blocks, list):
        return []
    screenshots: list[dict[str, str]] = []
    image_idx = 0
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
            'data': str(Path('screenshots') / file_name),
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

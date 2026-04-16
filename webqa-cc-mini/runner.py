"""Web agent library entry point.

Usage::

    from runner import run_cc_mini, RunResult

    result = run_cc_mini(
        url="https://example.com",
        user_input="Find the H1 heading and report it",
    )
    print(result.final_text)

Supports Anthropic (default) and OpenAI-compatible providers::

    # OpenAI GPT-4o
    result = run_cc_mini("https://example.com", "test login",
                         provider="openai", model="gpt-4o")

    # Local Ollama
    result = run_cc_mini("https://example.com", "test login",
                         provider="openai", model="llama3.1:70b",
                         base_url="http://localhost:11434/v1",
                         api_key="ollama")
"""
from __future__ import annotations

import logging
import shutil
import tempfile
from collections import deque
from dataclasses import dataclass, field

from core.config import DEFAULT_MODEL, DEFAULT_PROVIDER, MCPServerConfig
from core.context import build_web_agent_system_prompt
from core.engine import Engine, AbortedError
from core.mcp_client import MCPManager
from core.permissions import PermissionChecker
from features.compact import CompactService, should_compact

log = logging.getLogger("cc_mini.runner")


@dataclass
class Step:
    tool: str
    input: dict
    result: str
    is_error: bool


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
    max_iterations: int = 50,
    on_event=None,
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
    max_iterations:
        Hard limit on the number of tool steps before aborting.
    on_event:
        Optional callback ``fn(event_tuple)`` called for every engine event.
        Exceptions in the callback are caught and logged; they never propagate.
    """
    aborted = False  # initialised before try so it's always defined

    # Resolve provider/model: explicit arg > built-in default.
    provider = provider or DEFAULT_PROVIDER
    model = model or DEFAULT_MODEL

    profile = tempfile.mkdtemp(prefix=f"cc-mini-w{worker_id}-")
    if mcp_servers is None:
        mcp_servers = _default_browser_mcp(profile, worker_id)

    mcp = MCPManager(mcp_servers)

    engine: Engine | None = None
    steps: list[Step] = []
    # Cumulative totals — reported back in RunResult.
    total_tokens = {"input": 0, "output": 0}
    # Last API call's input_tokens — drives compact decisions.
    # Must track the *latest* call (replace semantics), NOT a running sum;
    # should_compact() compares this to _auto_compact_threshold(model) and
    # accumulation would incorrectly re-trigger compaction every turn.
    last_input_tokens = 0
    # Flag: did we ever receive a "usage" event? If not (e.g. an OpenAI-compatible
    # backend that ignores stream_options={"include_usage": True}), we fall back
    # to estimate_tokens on "tool_result" events so compact still fires.
    seen_usage = False

    try:
        tools = mcp.start_and_collect_tools()

        system = build_web_agent_system_prompt(target_url=url, task=user_input)
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
            """Check & run compaction. Safe to call from any event handler:
            engine.submit() is yielded at this point, so set_messages() will
            be visible to the generator when it resumes."""
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
            f"Target URL: {url}\n\n"
            f"Task: {user_input}\n\n"
            "Begin by navigating to the URL."
        )

        for evt in engine.submit(seed):
            # Forward event to caller before any internal processing.
            if on_event is not None:
                try:
                    on_event(evt)
                except Exception as cb_exc:
                    log.warning("on_event callback raised: %s", cb_exc)

            kind = evt[0]

            if kind == "tool_call":
                # evt = ("tool_call", name, input_dict, activity)
                pending.append({"tool": evt[1], "input": evt[2]})

            elif kind == "tool_result":
                # evt = ("tool_result", name, input_dict, ToolResult)
                if pending:
                    p = pending.popleft()
                    steps.append(Step(
                        tool=p["tool"],
                        input=p["input"],
                        result=evt[3].content,
                        is_error=evt[3].is_error,
                    ))

                # Fallback compact trigger: only runs when the provider never
                # emits "usage" (e.g. OpenAI-compatible backends that ignore
                # stream_options). Uses estimate_tokens (char-based) via
                # should_compact's fallback path (last_input=None).
                if not seen_usage:
                    _maybe_compact(None)

            elif kind == "usage":
                u = evt[1]
                seen_usage = True
                # last_input_tokens = this call only (replace semantics, used
                # to decide whether to compact — see comment where it's declared).
                # total_tokens["input"]  = sum of per-call input_tokens. Each
                # call re-sends the full history, so this matches what the
                # provider actually billed across the run.
                last_input_tokens = getattr(u, "input_tokens", 0) or 0
                total_tokens["input"] += last_input_tokens
                total_tokens["output"] += getattr(u, "output_tokens", 0) or 0

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

        return RunResult(
            final_text=engine.last_assistant_text(),
            steps=steps,
            aborted=aborted,
            input_tokens=total_tokens["input"],
            output_tokens=total_tokens["output"],
        )

    except AbortedError:
        aborted = True
        return RunResult(
            final_text=engine.last_assistant_text() if engine is not None else "",
            steps=steps,
            aborted=True,
            input_tokens=total_tokens["input"],
            output_tokens=total_tokens["output"],
        )

    finally:
        try:
            mcp.shutdown_all()
        except Exception as exc:
            log.warning("MCP shutdown error: %s", exc)
        try:
            shutil.rmtree(profile, ignore_errors=True)
        except Exception:
            pass


def _default_browser_mcp(profile: str, worker_id: int) -> list[MCPServerConfig]:
    """Default MCP config: chrome-devtools-mcp with isolated profile and port."""
    return [
        MCPServerConfig(
            name="browser",
            command="npx",
            args=(
                "-y",
                "chrome-devtools-mcp@latest",
                f"--user-data-dir={profile}",
                f"--remote-debugging-port={9222 + worker_id}",
            ),
        )
    ]

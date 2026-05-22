# SPDX-License-Identifier: Apache-2.0
# Portions adapted from cc-mini (https://github.com/e10nMa2k/cc-mini)
# Original author: e10nMa2k. Modifications © 2026 WebQA Agent contributors.
from __future__ import annotations

import hashlib
import random
import re
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any, Callable, Iterator

ContextOverflowHandler = Callable[[list[dict]], list[dict] | None]

from ..utils.data_flow import (build_llm_error_payload, build_llm_ok_payload,
                               build_tool_event_payload, iso_now, safe_copy)
from .config import DEFAULT_MODEL, default_max_tokens_for_model, resolve_model
from .llm import LLMClient
from .permissions import PermissionChecker
from .text import sanitize_unicode
from .tool import Tool, ToolResult

_MAX_RETRIES = 10

# Tools whose text results are large and only the latest is useful.
# Older results are replaced with a short placeholder before each LLM call
# (see ``_strip_old_snapshots``). Add only tools whose stale outputs are
# safe to drop — i.e. the agent rarely needs to refer back to old runs.
_LARGE_TEXT_TOOLS = frozenset({
    'mcp__browser__take_snapshot',
    'mcp__browser__list_network_requests',
    'mcp__browser__list_console_messages',
    'mcp__browser__evaluate_script',
})

# Browser tools that mutate page state — if any of these are called
# without a take_screenshot in the same turn, the engine auto-injects one.
_MUTATING_TOOLS = frozenset({
    'mcp__browser__click',
    'mcp__browser__click_at',
    'mcp__browser__fill',
    'mcp__browser__navigate_page',
    'mcp__browser__press_key',
    'mcp__browser__hover',
    'mcp__browser__hover_at',
    'mcp__browser__drag',
    'mcp__browser__upload_file',
    'mcp__browser__select_option',
    'mcp__browser__type_text',
    'cdp_upload_file',
})

# Bounds (ms) for mcp__browser__wait_for.  setdefault was insufficient
# because the model sometimes passes timeout=0 (chrome-devtools-mcp treats
# 0 as "use server default") — we clamp instead so 0/missing/<0 fall back
# to the short default and overlong values are capped 30s below the outer
# _DEFAULT_CALL_TIMEOUT (60s).  The 30s cap is a defensive ceiling: cdm's
# wait_for is a literal Puppeteer text/aria locator (case-sensitive, must
# be visible, no shadow-DOM piercing, text/ doesn't match aria-label), so
# icon buttons, shadow-DOM components, and dynamic labels all wait the
# full timeout for nothing.  Bounding the cap at 30s limits wasted time
# when the model picks a phrase that will never match.
_WAIT_FOR_DEFAULT_TIMEOUT_MS = 8000
_WAIT_FOR_MAX_TIMEOUT_MS = 30000
_BASE_DELAY = 0.5
_MAX_DELAY = 32.0
_JITTER_FACTOR = 0.25

# Maximum number of concurrent tool calls within one read-only batch.
# chrome-devtools-mcp serialises tool invocations on the renderer's main
# thread, so wider parallelism delivers no real speedup but does cause every
# waiter to share one 60s clock.  3 covers the common "console + network +
# get_*" trio without inviting batch-wide synchronous timeouts.
_MAX_CONCURRENT_TOOLS = 3


def _screenshot_content_hash(result: ToolResult) -> str | None:
    """MD5 of the first image block's base64 data, or None."""
    for blk in result.content_blocks or []:
        if isinstance(blk, dict) and blk.get('type') == 'image':
            data = blk.get('data', '')
            if data:
                return hashlib.md5(data.encode('ascii')).hexdigest()
    return None


def _compute_retry_delay(attempt: int, retry_after: float | None = None) -> float:
    """Exponential backoff with jitter, respecting Retry-After if present."""
    if retry_after is not None and retry_after > 0:
        return retry_after
    delay = min(_BASE_DELAY * (2 ** attempt), _MAX_DELAY)
    jitter = delay * random.uniform(0, _JITTER_FACTOR)
    return delay + jitter


def _parse_retry_after(exc: Exception) -> float | None:
    """Extract Retry-After value from API error headers, if available."""
    headers = getattr(getattr(exc, 'response', None), 'headers', None)
    if headers is None:
        return None
    raw = headers.get('retry-after') or headers.get('Retry-After')
    if raw is None:
        return None
    try:
        return float(raw)
    except (ValueError, TypeError):
        return None


_CONTEXT_OVERFLOW_RE = re.compile(
    r'prompt is too long|max_tokens.*exceeds.*context|input.*too large'
    r'|input tokens exceed|context_length_exceeded',
    re.IGNORECASE,
)


class AbortedError(Exception):
    """Raised when the current turn is aborted."""


class Engine:
    def __init__(self, tools: list[Tool], system_prompt: str,
                 permission_checker: PermissionChecker,
                 provider: str = 'anthropic',
                 model: str = DEFAULT_MODEL,
                 max_tokens: int | None = None,
                 api_key: str | None = None,
                 base_url: str | None = None,
                 effort: str | None = None,
                 temperature: float | None = None,
                 top_p: float | None = None,
                 timeout: float | None = None):
        self._provider = provider
        self._model = resolve_model(model, provider=provider)
        self._max_tokens = max_tokens or default_max_tokens_for_model(
            self._model,
            provider=provider,
        )
        # Optional callback invoked when the LLM rejects the request with a
        # context-overflow error. Receives the current message list and is
        # expected to return a shorter (e.g. summarised) message list, or
        # None if it could not shrink the conversation. Set lazily via
        # ``set_context_overflow_handler`` so the runner can construct the
        # CompactService after the engine.
        self._on_context_overflow: ContextOverflowHandler | None = None
        # Collect optional per-call LLM kwargs into one dict so submit()
        # can spread them without enumerating each field individually.
        self._llm_kwargs: dict[str, Any] = {
            k: v for k, v in {
                'effort': effort,
                'temperature': temperature,
                'top_p': top_p,
            }.items() if v is not None
        }
        self._client = LLMClient(
            provider=provider,
            api_key=api_key,
            base_url=base_url,
            timeout=timeout,
        )
        self._tools = {t.name: t for t in tools}
        self._system_prompt = system_prompt
        self._permissions = permission_checker
        self._messages: list[dict] = []
        self._aborted = False
        self._turn_start_len: int | None = None
        self._active_stream = None  # reference to current HTTP stream
        self._turn_id = 0
        self._data_flow_sequence = 0
        self._prev_screenshot_hash: str | None = None
        self._consecutive_failures: int = 0
        self._turn_visual_state: str = 'unknown'

    # -- message accessors (for compact / resume) ---------------------------

    def get_messages(self) -> list[dict]:
        return list(self._messages)

    def set_messages(self, messages: list[dict]) -> None:
        # Preserve None/list/str content types — callers may pass messages
        # with structured content (tool_use / tool_result blocks). Only the
        # truly-missing case falls back to an empty string.
        sanitized: list[dict] = []
        for message in messages:
            content = message.get('content')
            if content is None:
                content = ''
            sanitized.append({
                'role': message['role'],
                'content': sanitize_unicode(content),
            })
        self._messages = sanitized

    def get_model(self) -> str:
        return self._model

    def set_context_overflow_handler(
        self,
        handler: ContextOverflowHandler | None,
    ) -> None:
        """Register a callback to handle ``context_length_exceeded``.

        The handler receives the current ``self._messages`` and should
        return a shorter list (typically the result of summarising the
        history). Returning ``None`` — or a list that isn't strictly
        shorter — tells the engine to fall back to its legacy behaviour
        of halving ``max_tokens`` and retrying.
        """
        self._on_context_overflow = handler

    @property
    def system_prompt(self) -> str:
        return self._system_prompt

    def last_assistant_text(self) -> str:
        """Extract text from the last assistant message."""
        if not self._messages:
            return ''
        last = self._messages[-1]
        if last.get('role') != 'assistant':
            return ''
        content = last.get('content', '')
        if isinstance(content, str):
            return content
        if isinstance(content, list):
            parts = []
            for block in content:
                if hasattr(block, 'text'):
                    parts.append(block.text)
                elif isinstance(block, dict) and block.get('type') == 'text':
                    parts.append(block.get('text', ''))
            return ''.join(parts)
        return ''

    def _next_sequence(self) -> int:
        self._data_flow_sequence += 1
        return self._data_flow_sequence

    def _data_flow_event(
        self,
        *,
        event_type: str,
        payload: dict[str, Any],
        timestamp: str | None = None,
    ) -> tuple[str, dict[str, Any]]:
        return (
            'data_flow_event',
            {
                'timestamp': timestamp or iso_now(),
                'stage': 'cc-mini',
                'event_type': event_type,
                'payload': {
                    'sequence': self._next_sequence(),
                    **payload,
                },
            },
        )

    def _annotate_screenshot_state(
        self, result: ToolResult, *, after_mutation: bool,
    ) -> None:
        """Append a visual-signal note and update the screenshot hash.

        ``after_mutation`` should be True only for screenshots captured
        *after* a mutating tool executed in this turn.  Pre-action
        screenshots still update ``_prev_screenshot_hash`` (so the next
        comparison has a fresh baseline) but receive no annotation.
        """
        current_hash = _screenshot_content_hash(result)
        if not current_hash:
            return
        if after_mutation and self._prev_screenshot_hash:
            if current_hash == self._prev_screenshot_hash:
                result.content += (
                    '\n[visual signal: page appears unchanged since '
                    'previous screenshot — this is an observation, not '
                    'a conclusion; verify intended effect via snapshot]'
                )
                self._turn_visual_state = 'unchanged'
            else:
                result.content += (
                    '\n[visual signal: page changed since previous '
                    'screenshot — verify that the change matches your '
                    'intended outcome]'
                )
                self._turn_visual_state = 'changed'
        self._prev_screenshot_hash = current_hash

    _FAILURE_ESCALATION_THRESHOLD = 3

    def _update_failure_counter(
        self,
        tool_results: list[dict[str, Any]],
        turn_has_mutation: bool,
    ) -> None:
        """Track consecutive mutating turns with no visible progress."""
        if not turn_has_mutation:
            return

        has_error = any(
            isinstance(tr, dict) and tr.get('is_error')
            for tr in tool_results
        )
        no_visible_progress = (
            self._turn_visual_state == 'unchanged' and not has_error
        )

        if has_error or no_visible_progress:
            self._consecutive_failures += 1
        else:
            self._consecutive_failures = 0
            return

        if (
            self._consecutive_failures >= self._FAILURE_ESCALATION_THRESHOLD
            and tool_results
        ):
            n = self._consecutive_failures
            signal = (
                f'\n[consecutive failure #{n}: the last {n} '
                f'action turns produced errors or no visible '
                f'effect — current approach is not working, '
                f'try a fundamentally different strategy]'
            )
            last = tool_results[-1]
            existing = last.get('content', '')
            if isinstance(existing, str):
                last['content'] = existing + signal
            elif isinstance(existing, list):
                last['content'] = list(existing) + [
                    {'type': 'text', 'text': signal},
                ]

    def _tool_call_id(self, turn_id: int, tool_use: Any) -> str:
        raw_id = _block_id(tool_use)
        if raw_id:
            return f'tool-{turn_id}-{raw_id}'
        return f'tool-{turn_id}-{id(tool_use)}'

    def _execute_tool_with_metrics(
        self,
        tool_use: Any,
        *,
        skip_permission: bool = False,
    ) -> tuple[ToolResult, str, str, float]:
        started_at = iso_now()
        start_perf = time.perf_counter()
        try:
            result = self._execute_tool(tool_use, skip_permission=skip_permission)
        except Exception as exc:
            result = ToolResult(content=f'Tool execution error: {exc}', is_error=True)
        ended_at = iso_now()
        return result, started_at, ended_at, round(time.perf_counter() - start_perf, 4)

    def abort(self):
        """Abort the current turn immediately.

        Sets flag and closes the active HTTP stream so the generator unblocks
        at once.
        """
        self._aborted = True
        if self._active_stream is not None:
            try:
                self._active_stream.close()
            except Exception:
                pass

    def cancel_turn(self):
        """Roll back messages to the state before the current turn started."""
        if self._turn_start_len is not None:
            del self._messages[self._turn_start_len:]
            self._turn_start_len = None

    def submit(self, user_input: str | list) -> Iterator[tuple]:
        """Send user message; yield events until the conversation turn
        completes.

        Yields:
          ("text", str)                         — streamed text chunk
          ("tool_call", name, input, activity)  — before each tool executes
          ("tool_executing", name, input, activity) — after permission granted, tool running
          ("tool_result", name, input, result)  — after each tool executes
          ("waiting",)                          — text done, waiting for tool_use
          ("usage", usage)                      — token usage after each API call
          ("error", str)                        — non-fatal API error shown to user

        Raises:
          AbortedError — if abort() was called
        """
        self._aborted = False
        self._turn_start_len = len(self._messages)
        user_input = sanitize_unicode(user_input)
        self._messages.append({
            'role': 'user',
            'content': user_input,
        })

        try:
            while True:
                if self._aborted:
                    raise AbortedError()

                tool_uses = []

                # API call with retry
                final = None
                self._turn_id += 1
                turn_id = self._turn_id
                for attempt in range(_MAX_RETRIES):
                    call_id = f'llm-{turn_id}-{attempt + 1}'
                    llm_start_perf = time.perf_counter()
                    llm_start_ts = iso_now()
                    request_payload: dict[str, Any] = {}
                    try:
                        tools = [t.to_api_schema() for t in self._tools.values()]
                        # Drop stale large content before each LLM call.
                        _strip_old_images(self._messages, keep_recent=1)
                        _strip_old_snapshots(self._messages, keep_recent=1)
                        _strip_inline_snapshots(self._messages, keep_recent=1)
                        request_payload = {
                            'model': self._model,
                            'provider': self._provider,
                            'max_tokens': self._max_tokens,
                            'system': safe_copy(self._system_prompt),
                            'tools': safe_copy(tools),
                            'messages': safe_copy(self._messages),
                            'llm_kwargs': safe_copy(self._llm_kwargs),
                        }
                        stream_obj = self._client.stream_messages(
                            model=self._model,
                            max_tokens=self._max_tokens,
                            system=self._system_prompt,
                            tools=tools,
                            messages=self._messages,
                            **self._llm_kwargs,
                        )
                        self._active_stream = stream_obj
                        with stream_obj as stream:
                            got_text = False
                            for text in stream.text_stream:
                                if self._aborted:
                                    raise AbortedError()
                                got_text = True
                                yield ('text', text)

                            if self._aborted:
                                raise AbortedError()

                            if got_text:
                                yield ('waiting',)

                            final = stream.get_final_message()
                            if final.usage:
                                yield ('usage', final.usage)
                            for block in final.content:
                                if _block_type(block) == 'tool_use':
                                    tool_uses.append(block)
                            llm_end_ts = iso_now()
                            duration_seconds = round(time.perf_counter() - llm_start_perf, 4)
                            yield self._data_flow_event(
                                event_type='cc_mini_llm_call',
                                timestamp=llm_end_ts,
                                payload=build_llm_ok_payload(
                                    call_id=call_id,
                                    turn_id=turn_id,
                                    attempt=attempt + 1,
                                    model=self._model,
                                    provider=self._provider,
                                    started_at=llm_start_ts,
                                    ended_at=llm_end_ts,
                                    duration_seconds=duration_seconds,
                                    usage=final.usage,
                                    request=request_payload,
                                    assistant_content=final.content,
                                ),
                            )
                        break  # success, exit retry loop
                    except AbortedError:
                        raise
                    except Exception as e:
                        err_msg = self._client.error_message(e)
                        llm_end_ts = iso_now()
                        duration_seconds = round(time.perf_counter() - llm_start_perf, 4)
                        yield self._data_flow_event(
                            event_type='cc_mini_error',
                            timestamp=llm_end_ts,
                            payload=build_llm_error_payload(
                                call_id=call_id,
                                turn_id=turn_id,
                                attempt=attempt + 1,
                                model=self._model,
                                provider=self._provider,
                                started_at=llm_start_ts,
                                ended_at=llm_end_ts,
                                duration_seconds=duration_seconds,
                                error_message=err_msg,
                                request=request_payload,
                            ),
                        )
                        if self._client.is_authentication_error(e):
                            self._messages.pop()
                            yield ('error', f'Authentication failed: {self._client.error_message(e)}')
                            return
                        # Context overflow: try to compact history first;
                        # only fall back to halving max_tokens (output cap)
                        # if compaction couldn't shrink the messages — that
                        # legacy path can't help when the input alone has
                        # already exceeded the limit.
                        if self._client.is_api_error(e) and _CONTEXT_OVERFLOW_RE.search(err_msg):
                            if self._on_context_overflow is not None:
                                before = len(self._messages)
                                try:
                                    new_messages = self._on_context_overflow(
                                        self._messages,
                                    )
                                except Exception as compact_exc:
                                    new_messages = None
                                    yield (
                                        'error',
                                        f'Context overflow compact handler raised: {compact_exc}',
                                    )
                                if (
                                    new_messages is not None
                                    and len(new_messages) < before
                                ):
                                    self._messages = new_messages
                                    self._turn_start_len = len(new_messages)
                                    yield (
                                        'error',
                                        'Context overflow, compacted history '
                                        f'({before} -> {len(new_messages)} messages) and retrying...',
                                    )
                                    continue
                            reduced = self._max_tokens // 2
                            if reduced >= 1024:
                                self._max_tokens = reduced
                                yield ('error', f'Context overflow, reducing max_tokens to {reduced} and retrying...')
                                continue
                            else:
                                self._messages.pop()
                                yield ('error', f'Context overflow and cannot reduce further: {err_msg}')
                                return
                        if self._client.is_retryable_error(e):
                            if attempt < _MAX_RETRIES - 1:
                                retry_after = _parse_retry_after(e)
                                wait = _compute_retry_delay(attempt, retry_after)
                                yield ('error', f'API error, retrying in {wait:.1f}s... ({err_msg})')
                                time.sleep(wait)
                            else:
                                self._messages.pop()
                                yield ('error', f'API error after {_MAX_RETRIES} retries: {err_msg}')
                                return
                            continue
                        if self._client.is_api_error(e):
                            self._messages.pop()
                            yield ('error', f'API error: {err_msg}')
                            return
                        if self._aborted:
                            raise AbortedError()
                        raise
                    finally:
                        self._active_stream = None

                if final is None:
                    self._messages.pop()
                    return

                self._messages.append({
                    'role': 'assistant',
                    'content': final.content,
                })

                if not tool_uses:
                    break

                turn_tool_names = {_block_name(tu) for tu in tool_uses}
                turn_has_mutation = bool(turn_tool_names & _MUTATING_TOOLS)
                self._turn_visual_state = 'unknown'
                mutation_executed = False

                tool_results = []

                # Partition into batches: consecutive read-only AND
                # concurrent-safe tools run in parallel; everything else runs
                # alone.  Both gates matter: `is_read_only()` excludes mutating
                # tools (Nuclei scan, switch_account, etc.), `concurrent_safe`
                # is the stricter follow-up that excludes read-only-but-
                # serialised cases (heavy MCP reads, stateful native tools,
                # tools that fan out to MCP themselves like VerifyTool).
                batches: list[list] = []
                for tu in tool_uses:
                    t = self._tools.get(_block_name(tu))
                    is_concurrent = (
                        t is not None
                        and t.is_read_only()
                        and getattr(t, 'concurrent_safe', True)
                    )
                    if batches and batches[-1][0] == is_concurrent and is_concurrent:
                        batches[-1][1].append(tu)
                    else:
                        batches.append((is_concurrent, [tu]))

                for is_concurrent, batch in batches:
                    if self._aborted:
                        raise AbortedError()

                    if is_concurrent and len(batch) > 1:
                        # --- parallel execution for read-only tools ---
                        # Phase 1: emit tool_call events + check permissions
                        approved: list[tuple] = []  # (tool_use, tool, activity)
                        denied_results: dict[str, tuple[ToolResult, str, str, float]] = {}  # by tool_use_id
                        for tu in batch:
                            tn = _block_name(tu)
                            ti = _block_input(tu)
                            tool = self._tools.get(tn)
                            act = tool.get_activity_description(**ti) if tool else None
                            tool_call_id = self._tool_call_id(turn_id, tu)
                            call_ts = iso_now()
                            yield ('tool_call', tn, ti, act)
                            yield self._data_flow_event(
                                event_type='cc_mini_tool_call',
                                timestamp=call_ts,
                                payload=build_tool_event_payload(
                                    tool_name=tn,
                                    tool_input=ti,
                                    call_id=tool_call_id,
                                    turn_id=turn_id,
                                    tool_use_id=_block_id(tu),
                                    activity=act,
                                    status='scheduled',
                                ),
                            )
                            if tool and self._permissions.check(tool, ti) == 'deny':
                                denied_at = iso_now()
                                denied_results[_block_id(tu)] = (
                                    ToolResult(content='Permission denied.', is_error=True),
                                    call_ts,
                                    denied_at,
                                    0.0,
                                )
                            else:
                                approved.append((tu, tool, act))

                        # Phase 2: emit tool_executing for approved, then run in parallel
                        executed_results: dict[str, tuple[ToolResult, str, str, float]] = {}
                        if approved:
                            for tu, tool, act in approved:
                                tn = _block_name(tu)
                                ti = _block_input(tu)
                                yield ('tool_executing', tn, ti, act)

                            with ThreadPoolExecutor(
                                max_workers=min(len(approved), _MAX_CONCURRENT_TOOLS),
                            ) as pool:
                                futures = {}
                                for tu, tool, act in approved:
                                    f = pool.submit(
                                        self._execute_tool_with_metrics,
                                        tu,
                                        skip_permission=True,
                                    )
                                    futures[f] = tu
                                for f in as_completed(futures):
                                    tu = futures[f]
                                    executed_results[_block_id(tu)] = f.result()

                        # Phase 3: emit results in original batch order
                        for tu in batch:
                            tid = _block_id(tu)
                            tn = _block_name(tu)
                            ti = _block_input(tu)
                            measured = denied_results.get(tid) or executed_results.get(tid)
                            if measured is None:
                                now = iso_now()
                                measured = (
                                    ToolResult(content='No result', is_error=True),
                                    now,
                                    now,
                                    0.0,
                                )
                            result, started_at, ended_at, duration_seconds = measured
                            if tn == 'mcp__browser__take_screenshot':
                                self._annotate_screenshot_state(
                                    result, after_mutation=mutation_executed,
                                )
                            yield ('tool_result', tn, ti, result)
                            yield self._data_flow_event(
                                event_type='cc_mini_tool_result',
                                timestamp=ended_at,
                                payload=build_tool_event_payload(
                                    tool_name=tn,
                                    tool_input=ti,
                                    call_id=self._tool_call_id(turn_id, tu),
                                    turn_id=turn_id,
                                    tool_use_id=tid,
                                    activity=None,
                                    status='done',
                                    result=result,
                                    started_at=started_at,
                                    ended_at=ended_at,
                                    duration_seconds=duration_seconds,
                                ),
                            )
                            tool_results.append(
                                _build_tool_result_block(tid, result)
                            )
                    else:
                        # --- sequential execution (single tool or non-read-only) ---
                        for tu in batch:
                            if self._aborted:
                                raise AbortedError()
                            tn = _block_name(tu)
                            ti = _block_input(tu)
                            tool = self._tools.get(tn)
                            act = tool.get_activity_description(**ti) if tool else None
                            tool_call_id = self._tool_call_id(turn_id, tu)
                            call_ts = iso_now()
                            yield ('tool_call', tn, ti, act)
                            yield self._data_flow_event(
                                event_type='cc_mini_tool_call',
                                timestamp=call_ts,
                                payload=build_tool_event_payload(
                                    tool_name=tn,
                                    tool_input=ti,
                                    call_id=tool_call_id,
                                    turn_id=turn_id,
                                    tool_use_id=_block_id(tu),
                                    activity=act,
                                    status='scheduled',
                                ),
                            )

                            if tool and self._permissions.check(tool, ti) == 'deny':
                                result = ToolResult(content='Permission denied.', is_error=True)
                                started_at = call_ts
                                ended_at = iso_now()
                                duration_seconds = 0.0
                            else:
                                yield ('tool_executing', tn, ti, act)
                                result, started_at, ended_at, duration_seconds = (
                                    self._execute_tool_with_metrics(
                                        tu,
                                        skip_permission=True,
                                    )
                                )

                            if tn in _MUTATING_TOOLS:
                                mutation_executed = True
                            if tn == 'mcp__browser__take_screenshot':
                                self._annotate_screenshot_state(
                                    result, after_mutation=mutation_executed,
                                )
                            yield ('tool_result', tn, ti, result)
                            yield self._data_flow_event(
                                event_type='cc_mini_tool_result',
                                timestamp=ended_at,
                                payload=build_tool_event_payload(
                                    tool_name=tn,
                                    tool_input=ti,
                                    call_id=tool_call_id,
                                    turn_id=turn_id,
                                    tool_use_id=_block_id(tu),
                                    activity=act,
                                    status='done',
                                    result=result,
                                    started_at=started_at,
                                    ended_at=ended_at,
                                    duration_seconds=duration_seconds,
                                ),
                            )
                            tool_results.append(
                                _build_tool_result_block(_block_id(tu), result)
                            )

                # Auto-inject screenshot if a mutating action was executed
                # but the model didn't include take_screenshot.
                tool_names = turn_tool_names
                has_mutation = turn_has_mutation
                has_screenshot = 'mcp__browser__take_screenshot' in tool_names
                if has_mutation and not has_screenshot:
                    ss_tool = self._tools.get('mcp__browser__take_screenshot')
                    if ss_tool is not None:
                        ss_input = {'format': 'jpeg', 'quality': 55}
                        ss_act = ss_tool.get_activity_description(**ss_input)
                        synthetic_id = f'auto_screenshot_{time.time_ns()}'
                        ss_call_id = f'tool-{turn_id}-{synthetic_id}'
                        ss_call_ts = iso_now()
                        yield ('tool_call', 'mcp__browser__take_screenshot', ss_input, ss_act)
                        yield self._data_flow_event(
                            event_type='cc_mini_tool_call',
                            timestamp=ss_call_ts,
                            payload=build_tool_event_payload(
                                tool_name='mcp__browser__take_screenshot',
                                tool_input=ss_input,
                                call_id=ss_call_id,
                                turn_id=turn_id,
                                tool_use_id=synthetic_id,
                                activity=ss_act,
                                status='scheduled',
                                synthetic=True,
                            ),
                        )
                        ss_start = iso_now()
                        ss_perf = time.perf_counter()
                        ss_result = ss_tool.execute(**ss_input)
                        ss_end = iso_now()
                        ss_duration = round(time.perf_counter() - ss_perf, 4)
                        self._annotate_screenshot_state(ss_result, after_mutation=True)
                        yield ('tool_result', 'mcp__browser__take_screenshot',
                               ss_input, ss_result)
                        yield self._data_flow_event(
                            event_type='cc_mini_tool_result',
                            timestamp=ss_end,
                            payload=build_tool_event_payload(
                                tool_name='mcp__browser__take_screenshot',
                                tool_input=ss_input,
                                call_id=ss_call_id,
                                turn_id=turn_id,
                                tool_use_id=synthetic_id,
                                activity=ss_act,
                                status='done',
                                result=ss_result,
                                started_at=ss_start,
                                ended_at=ss_end,
                                duration_seconds=ss_duration,
                                synthetic=True,
                            ),
                        )
                        # Build a synthetic tool_use_id for the injected screenshot.
                        # Inject a matching tool_use into the assistant message
                        # so OpenAI sees a valid tool_call ↔ tool pairing.
                        assistant_content = self._messages[-1].get('content')
                        if isinstance(assistant_content, list):
                            self._messages[-1]['content'] = list(assistant_content) + [{
                                'type': 'tool_use',
                                'id': synthetic_id,
                                'name': 'mcp__browser__take_screenshot',
                                'input': ss_input,
                            }]
                        tool_results.append(
                            _build_tool_result_block(synthetic_id, ss_result)
                        )

                self._update_failure_counter(tool_results, turn_has_mutation)

                self._messages.append({
                    'role': 'user',
                    'content': tool_results,
                })
        except AbortedError:
            self.cancel_turn()
            raise

    def _execute_tool(self, tool_use, skip_permission: bool = False) -> ToolResult:
        tool_name = _block_name(tool_use)
        tool_input = _block_input(tool_use)
        tool = self._tools.get(tool_name)
        resolved_name = tool_name
        if tool is None and '__' in tool_name:
            bare = tool_name.split('__')[-1]
            tool = self._tools.get(bare)
            if tool is not None:
                resolved_name = bare
        if tool is None:
            return ToolResult(content=f'Unknown tool: {tool_name}', is_error=True)

        if not skip_permission and self._permissions.check(tool, tool_input) == 'deny':
            return ToolResult(content='Permission denied.', is_error=True)

        # Auto-inject low-quality JPEG for screenshots to reduce token cost.
        if tool_name == 'mcp__browser__take_screenshot':
            tool_input.setdefault('format', 'jpeg')
            tool_input.setdefault('quality', 55)

        # Clamp wait_for timeout — see _WAIT_FOR_DEFAULT/MAX_TIMEOUT_MS for rationale.
        if tool_name == 'mcp__browser__wait_for':
            requested = tool_input.get('timeout')
            if not isinstance(requested, (int, float)) or requested <= 0:
                tool_input['timeout'] = _WAIT_FOR_DEFAULT_TIMEOUT_MS
            elif requested > _WAIT_FOR_MAX_TIMEOUT_MS:
                tool_input['timeout'] = _WAIT_FOR_MAX_TIMEOUT_MS

        try:
            result = tool.execute(**tool_input)
        except Exception as e:
            return ToolResult(content=f'Tool error: {e}', is_error=True)
        if resolved_name != tool_name:
            result.content = (
                f'[resolved {tool_name!r} → {resolved_name!r}; '
                f'use {resolved_name!r} directly next time]\n'
                + (result.content or '')
            )
        return result


def _block_type(block: Any) -> str | None:
    if isinstance(block, dict):
        return block.get('type')
    return getattr(block, 'type', None)


def _block_name(block: Any) -> str:
    if isinstance(block, dict):
        return str(block.get('name', ''))
    return str(getattr(block, 'name', ''))


def _block_id(block: Any) -> str:
    if isinstance(block, dict):
        return str(block.get('id', ''))
    return str(getattr(block, 'id', ''))


def _block_input(block: Any) -> dict[str, Any]:
    if isinstance(block, dict):
        value = block.get('input', {})
    else:
        value = getattr(block, 'input', {})
    return value if isinstance(value, dict) else {}


def _build_tool_result_block(tool_use_id: str, result: ToolResult) -> dict[str, Any]:
    """Build a tool_result message block, embedding images when available.

    When the ToolResult carries image content_blocks (e.g. from
    take_screenshot), they are included as multimodal content so the LLM
    can actually *see* the screenshot. Without this, the model only
    receives a text placeholder like "Took a screenshot..." and has no
    visual information to guide its actions.
    """
    images: list[dict[str, Any]] = []
    for blk in getattr(result, 'content_blocks', None) or []:
        if not isinstance(blk, dict) or blk.get('type') != 'image':
            continue
        data = blk.get('data')
        if not isinstance(data, str) or not data:
            continue
        mime = str(blk.get('mimeType') or 'image/png')
        images.append({
            'type': 'image',
            'source': {
                'type': 'base64',
                'media_type': mime,
                'data': data,
            },
        })

    if not images:
        # No images — plain text result (most tool calls).
        return {
            'type': 'tool_result',
            'tool_use_id': tool_use_id,
            'content': result.content,
            'is_error': result.is_error,
        }

    # Multimodal: text description + image(s).
    content_parts: list[dict[str, Any]] = [
        {'type': 'text', 'text': result.content},
    ]
    content_parts.extend(images)
    return {
        'type': 'tool_result',
        'tool_use_id': tool_use_id,
        'content': content_parts,
        'is_error': result.is_error,
    }


def _strip_old_images(messages: list[dict], *, keep_recent: int = 2) -> None:
    """Remove image blocks from all but the most recent *keep_recent*
    tool_result messages.

    Screenshots accumulate fast (~100-150K base64 chars each) and bloat the
    context. Only the latest screenshots are useful for decision-making; older
    ones are replaced with a short text placeholder.
    """
    # Collect indices of tool_result blocks that contain images.
    image_positions: list[tuple[int, int]] = []  # (msg_idx, block_idx)
    for mi, msg in enumerate(messages):
        if msg.get('role') != 'user':
            continue
        content = msg.get('content')
        if not isinstance(content, list):
            continue
        for bi, block in enumerate(content):
            if not isinstance(block, dict) or block.get('type') != 'tool_result':
                continue
            inner = block.get('content')
            if isinstance(inner, list) and any(
                isinstance(p, dict) and p.get('type') == 'image' for p in inner
            ):
                image_positions.append((mi, bi))

    # Keep the most recent ones, strip the rest.
    to_strip = image_positions[:-keep_recent] if len(image_positions) > keep_recent else []
    for mi, bi in to_strip:
        block = messages[mi]['content'][bi]
        inner = block['content']
        image_parts = [
            p for p in inner
            if isinstance(p, dict) and p.get('type') == 'image'
        ]
        # Keep only text parts, drop images. Add a stable marker so the
        # conversation still records that a screenshot was consumed here.
        text_parts = [
            p for p in inner
            if isinstance(p, dict) and p.get('type') == 'text'
        ]
        text_parts.append({
            'type': 'text',
            'text': _image_removal_marker(block, image_parts),
        })
        block['content'] = text_parts


def _strip_old_snapshots(messages: list[dict], *, keep_recent: int = 1) -> None:
    """Remove content of old large-text tool results (e.g. take_snapshot),
    keeping only the most recent *keep_recent*.

    Accessibility-tree snapshots can be 10K–100K chars each and accumulate
    fast.  Only the latest snapshot is useful for decision-making; older ones
    are replaced with a one-line placeholder.
    """
    # Build tool_use_id → tool_name from assistant messages.
    id_to_tool: dict[str, str] = {}
    for msg in messages:
        if msg.get('role') != 'assistant':
            continue
        content = msg.get('content', '')
        if not isinstance(content, list):
            continue
        for block in content:
            if isinstance(block, dict) and block.get('type') == 'tool_use':
                tid = str(block.get('id', ''))
                tname = str(block.get('name', ''))
                if tid:
                    id_to_tool[tid] = tname

    # Collect positions of tool_result blocks that belong to large-text tools.
    positions: list[tuple[int, int]] = []
    for mi, msg in enumerate(messages):
        if msg.get('role') != 'user':
            continue
        content = msg.get('content')
        if not isinstance(content, list):
            continue
        for bi, block in enumerate(content):
            if not isinstance(block, dict) or block.get('type') != 'tool_result':
                continue
            tid = str(block.get('tool_use_id', ''))
            if id_to_tool.get(tid) in _LARGE_TEXT_TOOLS:
                positions.append((mi, bi))

    # Strip all but the most recent keep_recent.
    to_strip = positions[:-keep_recent] if len(positions) > keep_recent else []
    for mi, bi in to_strip:
        block = messages[mi]['content'][bi]
        old = block.get('content', '')
        old_len = len(old) if isinstance(old, str) else sum(
            len(p.get('text', '')) for p in old if isinstance(p, dict)
        )
        block['content'] = f'[snapshot removed to save context, was ~{old_len} chars]'


# Regex matching the inline snapshot block that chrome-devtools-mcp appends
# when a tool is called with ``includeSnapshot: true``. The block starts with
# a markdown heading ("## Latest page snapshot" or similar) followed by the
# accessibility tree dump ("uid=..." lines). We strip it from old tool
# results to avoid duplicating what ``take_snapshot`` already captures.
_INLINE_SNAPSHOT_RE = re.compile(
    r'(?:\n|^)##\s*Latest page snapshot\n.*',
    re.DOTALL,
)


def _strip_inline_snapshots(
    messages: list[dict],
    *,
    keep_recent: int = 1,
) -> None:
    """Remove embedded page snapshots from old tool_result text.

    Many chrome-devtools-mcp tools (click, fill, hover, …) accept an
    ``includeSnapshot`` flag that appends the full accessibility tree to
    the result text. These inline snapshots are valuable for the *current*
    decision but redundant once the agent has moved on — and they can be
    10–30K chars each. This function strips them from all but the most
    recent *keep_recent* tool_result blocks that contain the pattern,
    leaving just the first line (e.g. "Successfully clicked on the
    element").
    """
    # Collect positions of tool_result blocks that contain inline snapshots.
    positions: list[tuple[int, int]] = []
    for mi, msg in enumerate(messages):
        if msg.get('role') != 'user':
            continue
        content = msg.get('content')
        if not isinstance(content, list):
            continue
        for bi, block in enumerate(content):
            if not isinstance(block, dict) or block.get('type') != 'tool_result':
                continue
            raw = block.get('content', '')
            if isinstance(raw, str) and _INLINE_SNAPSHOT_RE.search(raw):
                positions.append((mi, bi))
            elif isinstance(raw, list):
                for part in raw:
                    if (
                        isinstance(part, dict)
                        and part.get('type') == 'text'
                        and _INLINE_SNAPSHOT_RE.search(part.get('text', ''))
                    ):
                        positions.append((mi, bi))
                        break

    to_strip = (
        positions[:-keep_recent] if len(positions) > keep_recent else []
    )
    for mi, bi in to_strip:
        block = messages[mi]['content'][bi]
        raw = block.get('content', '')
        if isinstance(raw, str):
            block['content'] = _INLINE_SNAPSHOT_RE.sub(
                '\n[inline snapshot removed to save context]', raw,
            )
        elif isinstance(raw, list):
            for part in raw:
                if isinstance(part, dict) and part.get('type') == 'text':
                    text = part.get('text', '')
                    if _INLINE_SNAPSHOT_RE.search(text):
                        part['text'] = _INLINE_SNAPSHOT_RE.sub(
                            '\n[inline snapshot removed to save context]',
                            text,
                        )


def _image_removal_marker(
    tool_result_block: dict[str, Any],
    image_parts: list[dict[str, Any]],
) -> str:
    """Return a compact, stable marker for stripped screenshot images."""
    result_tool_use_id = str(tool_result_block.get('tool_use_id', ''))
    marker_parts: list[str] = [
        'screenshot image removed after consumption',
        f'tool_use_id={result_tool_use_id}',
    ]
    for image_index, image_part in enumerate(image_parts, start=1):
        image_source = (
            image_part.get('source')
            if isinstance(image_part.get('source'), dict)
            else {}
        )
        media_type = str(image_source.get('media_type') or 'image/png')
        base64_data = image_source.get('data') or ''
        base64_length = len(base64_data) if isinstance(base64_data, str) else 0
        marker_parts.append(
            f'image_{image_index}_media_type={media_type} '
            f'image_{image_index}_base64_chars={base64_length}'
        )
    return '[' + ', '.join(marker_parts) + ']'

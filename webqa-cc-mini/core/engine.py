from __future__ import annotations

import random
import re
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any, Iterator

from .config import DEFAULT_MODEL, default_max_tokens_for_model, resolve_model
from .llm import LLMClient
from .permissions import PermissionChecker
from .text import sanitize_unicode
from .tool import Tool, ToolResult

_MAX_RETRIES = 10

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
    'mcp__browser__wait_for',
})
_BASE_DELAY = 0.5
_MAX_DELAY = 32.0
_JITTER_FACTOR = 0.25


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
    r'prompt is too long|max_tokens.*exceeds.*context|input.*too large',
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
        # Drop images from older messages to keep context lean.
        # Only the most recent screenshot matters for decision-making.
        _strip_old_images(self._messages, keep_recent=2)
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
                for attempt in range(_MAX_RETRIES):
                    try:
                        tools = [t.to_api_schema() for t in self._tools.values()]
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
                        break  # success, exit retry loop
                    except AbortedError:
                        raise
                    except Exception as e:
                        if self._client.is_authentication_error(e):
                            self._messages.pop()
                            yield ('error', f'Authentication failed: {self._client.error_message(e)}')
                            return
                        # Context overflow: reduce max_tokens and retry
                        err_msg = self._client.error_message(e)
                        if self._client.is_api_error(e) and _CONTEXT_OVERFLOW_RE.search(err_msg):
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

                tool_results = []

                # Partition into batches: consecutive read-only tools run in
                # parallel; a non-read-only tool runs alone.
                batches: list[list] = []
                for tu in tool_uses:
                    t = self._tools.get(_block_name(tu))
                    is_concurrent = t is not None and t.is_read_only()
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
                        denied_results: dict[str, ToolResult] = {}  # by tool_use_id
                        for tu in batch:
                            tn = _block_name(tu)
                            ti = _block_input(tu)
                            tool = self._tools.get(tn)
                            act = tool.get_activity_description(**ti) if tool else None
                            yield ('tool_call', tn, ti, act)
                            if tool and self._permissions.check(tool, ti) == 'deny':
                                denied_results[_block_id(tu)] = ToolResult(
                                    content='Permission denied.', is_error=True)
                            else:
                                approved.append((tu, tool, act))

                        # Phase 2: emit tool_executing for approved, then run in parallel
                        executed_results: dict[str, ToolResult] = {}
                        if approved:
                            for tu, tool, act in approved:
                                tn = _block_name(tu)
                                ti = _block_input(tu)
                                yield ('tool_executing', tn, ti, act)

                            with ThreadPoolExecutor(max_workers=min(len(approved), 10)) as pool:
                                futures = {}
                                for tu, tool, act in approved:
                                    f = pool.submit(self._execute_tool, tu, skip_permission=True)
                                    futures[f] = tu
                                for f in as_completed(futures):
                                    tu = futures[f]
                                    try:
                                        executed_results[_block_id(tu)] = f.result()
                                    except Exception as exc:
                                        executed_results[_block_id(tu)] = ToolResult(
                                            content=f'Tool execution error: {exc}', is_error=True)

                        # Phase 3: emit results in original batch order
                        for tu in batch:
                            tid = _block_id(tu)
                            tn = _block_name(tu)
                            ti = _block_input(tu)
                            result = denied_results.get(tid) or executed_results.get(tid)
                            if result is None:
                                result = ToolResult(content='No result', is_error=True)
                            yield ('tool_result', tn, ti, result)
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
                            yield ('tool_call', tn, ti, act)

                            if tool and self._permissions.check(tool, ti) == 'deny':
                                result = ToolResult(content='Permission denied.', is_error=True)
                            else:
                                yield ('tool_executing', tn, ti, act)
                                result = self._execute_tool(tu, skip_permission=True)

                            yield ('tool_result', tn, ti, result)
                            tool_results.append(
                                _build_tool_result_block(_block_id(tu), result)
                            )

                # Auto-inject screenshot if a mutating action was executed
                # but the model didn't include take_screenshot.
                tool_names = {_block_name(tu) for tu in tool_uses}
                has_mutation = bool(tool_names & _MUTATING_TOOLS)
                has_screenshot = 'mcp__browser__take_screenshot' in tool_names
                if has_mutation and not has_screenshot:
                    ss_tool = self._tools.get('mcp__browser__take_screenshot')
                    if ss_tool is not None:
                        ss_input = {'format': 'jpeg', 'quality': 55}
                        ss_result = ss_tool.execute(**ss_input)
                        yield ('tool_result', 'mcp__browser__take_screenshot',
                               ss_input, ss_result)
                        # Build a synthetic tool_use_id for the injected screenshot.
                        synthetic_id = f'auto_screenshot_{id(ss_result)}'
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
        if tool is None:
            return ToolResult(content=f'Unknown tool: {tool_name}', is_error=True)

        if not skip_permission and self._permissions.check(tool, tool_input) == 'deny':
            return ToolResult(content='Permission denied.', is_error=True)

        # Auto-inject low-quality JPEG for screenshots to reduce token cost.
        if tool_name == 'mcp__browser__take_screenshot':
            tool_input.setdefault('format', 'jpeg')
            tool_input.setdefault('quality', 55)

        try:
            return tool.execute(**tool_input)
        except Exception as e:
            return ToolResult(content=f'Tool error: {e}', is_error=True)


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
        # Keep only text parts, drop images.
        text_parts = [p for p in inner if isinstance(p, dict) and p.get('type') == 'text']
        if not text_parts:
            text_parts = [{'type': 'text', 'text': '[screenshot removed to save context]'}]
        block['content'] = text_parts

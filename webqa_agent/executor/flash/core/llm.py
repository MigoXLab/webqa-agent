# SPDX-License-Identifier: Apache-2.0
# Portions adapted from cc-mini (https://github.com/e10nMa2k/cc-mini)
# Original author: e10nMa2k. Modifications © 2026 WebQA Agent contributors.
from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Iterator

import anthropic
import httpx

from .text import sanitize_unicode

_OPENAI_IMPORT_ERROR: Exception | None = None

try:
    import openai
    from openai import OpenAI
except Exception as exc:  # pragma: no cover - exercised in tests via stubs
    OpenAI = None  # type: ignore[assignment]
    openai = None  # type: ignore[assignment]
    _OPENAI_IMPORT_ERROR = exc


ProviderName = str

_ANTHROPIC_PROVIDER = 'anthropic'
_OPENAI_PROVIDER = 'openai'
_VALID_PROVIDERS = {_ANTHROPIC_PROVIDER, _OPENAI_PROVIDER}

MODEL_CONTEXT_WINDOW_DEFAULT = 200_000

# Maximum *input* tokens per model. First substring match wins — list
# more-specific entries before less-specific ones (e.g. "gpt-5.4-mini"
# before "gpt-5.4") since matching uses ``prefix in model_name``.
# Values should reflect the **real API input limit**, not the advertised
# "context window". compact.py uses these to decide when to trigger
# auto-compaction.
_MODEL_CONTEXT_WINDOWS: tuple[tuple[str, int], ...] = (
    # --- Anthropic Claude ---
    ('claude-opus-4', 200_000),
    ('claude-sonnet-4', 200_000),
    ('claude-haiku-4', 200_000),
    # --- OpenAI GPT / o-series ---
    # gpt-5.4-mini: advertised 400K, but API enforces 272K input limit
    ('gpt-5.4-mini', 272_000),
    ('gpt-5.4-nano', 272_000),
    ('gpt-5.4', 272_000),
    # gpt-4.1: 1M context, max output 128K → ~1M max input
    ('gpt-4.1-mini', 1_000_000),
    ('gpt-4.1-nano', 1_000_000),
    ('gpt-4.1', 1_000_000),
    ('o4-mini', 200_000),
    ('o3-mini', 200_000),
    ('o3', 200_000),
    # --- Google Gemini ---
    ('gemini-3', 1_048_576),
    ('gemini-2.5', 1_048_576),
    ('gemini-2', 1_048_576),
    # --- DeepSeek ---
    ('deepseek-v4', 1_000_000),
    ('deepseek-v3', 128_000),
    ('deepseek-r1', 128_000),
    ('deepseek', 128_000),
    # --- Qwen ---
    ('qwen3', 128_000),
    ('qwen', 128_000),
)


def get_context_window_for_model(model: str) -> int:
    """Return the context window size for a given model."""
    lowered = model.lower()
    # Explicit 1M-context marker overrides the table (e.g. "claude-opus-4-6[1m]").
    if '[1m]' in lowered or '1m' in lowered.split('-'):
        return 1_000_000
    for prefix, window in _MODEL_CONTEXT_WINDOWS:
        if prefix in lowered:
            return window
    return MODEL_CONTEXT_WINDOW_DEFAULT


@dataclass
class LLMUsage:
    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_input_tokens: int = 0
    cache_creation_input_tokens: int = 0


@dataclass
class LLMMessage:
    content: list[dict[str, Any]]
    usage: LLMUsage | None = None


def validate_provider(provider: str | None) -> ProviderName:
    normalized = (provider or _ANTHROPIC_PROVIDER).strip().lower()
    if normalized not in _VALID_PROVIDERS:
        raise ValueError(f'Unsupported provider: {provider}')
    return normalized


def default_model_for_provider(provider: str) -> str:
    provider = validate_provider(provider)
    if provider == _OPENAI_PROVIDER:
        return 'gpt-5.1-codex'
    return 'claude-sonnet-4-6'


def default_max_tokens_for_provider(provider: str) -> int:
    provider = validate_provider(provider)
    if provider == _OPENAI_PROVIDER:
        return 8192
    return 32000


def infer_provider_from_model(model: str) -> ProviderName:
    """Best-effort provider inference from a model ID string.

    Falls back to ``'openai'`` for unknown prefixes because OpenAI-compatible
    endpoints (Gemini proxies, DeepSeek, Ollama) all speak the OpenAI protocol.
    """
    lowered = model.lower()
    if lowered.startswith(('claude-', 'claude ')):
        return _ANTHROPIC_PROVIDER
    return _OPENAI_PROVIDER


def supports_reasoning_effort(provider: str, model: str) -> bool:
    provider = validate_provider(provider)
    if provider != _OPENAI_PROVIDER:
        return False
    lowered = model.lower()
    return lowered.startswith(('gpt-5', 'o1', 'o3', 'o4'))


class LLMClient:
    def __init__(
        self,
        provider: str = _ANTHROPIC_PROVIDER,
        api_key: str | None = None,
        base_url: str | None = None,
        timeout: float | None = None,
    ):
        self.provider = validate_provider(provider)
        self._api_key = api_key
        self._base_url = base_url
        if self.provider == _OPENAI_PROVIDER:
            if OpenAI is None:
                message = 'OpenAI support requires the `openai` package to be installed.'
                if _OPENAI_IMPORT_ERROR is not None:
                    message += f' Import failed: {_OPENAI_IMPORT_ERROR}'
                raise ValueError(message)
            self._client = OpenAI(
                api_key=api_key,
                base_url=base_url,
                **({'timeout': timeout} if timeout is not None else {}),
            )
        else:
            anthropic_timeout = (
                httpx.Timeout(timeout, connect=30.0)
                if timeout is not None
                else httpx.Timeout(600.0, connect=30.0)
            )
            self._client = anthropic.Anthropic(
                api_key=api_key,
                base_url=base_url,
                timeout=anthropic_timeout,
            )

    def create_message(
        self,
        *,
        model: str,
        max_tokens: int,
        messages: list[dict[str, Any]],
        system: str | None = None,
        tools: list[dict[str, Any]] | None = None,
        effort: str | None = None,
        temperature: float | None = None,
        top_p: float | None = None,
    ) -> LLMMessage:
        if self.provider == _OPENAI_PROVIDER:
            return self._openai_create_message(
                model=model,
                max_tokens=max_tokens,
                messages=messages,
                system=system,
                tools=tools,
                effort=effort,
                temperature=temperature,
                top_p=top_p,
            )
        return self._anthropic_create_message(
            model=model,
            max_tokens=max_tokens,
            messages=messages,
            system=system,
            tools=tools,
            temperature=temperature,
            top_p=top_p,
        )

    def stream_messages(
        self,
        *,
        model: str,
        max_tokens: int,
        messages: list[dict[str, Any]],
        system: str | None = None,
        tools: list[dict[str, Any]] | None = None,
        effort: str | None = None,
        temperature: float | None = None,
        top_p: float | None = None,
    ):
        if self.provider == _OPENAI_PROVIDER:
            return _OpenAIStream(
                client=self._client,
                model=model,
                max_tokens=max_tokens,
                messages=messages,
                system=system,
                tools=tools or [],
                effort=effort,
                temperature=temperature,
                top_p=top_p,
            )
        return _AnthropicStream(
            client=self._client,
            model=model,
            max_tokens=max_tokens,
            messages=messages,
            system=system,
            tools=tools or [],
            temperature=temperature,
            top_p=top_p,
        )

    def is_authentication_error(self, exc: Exception) -> bool:
        if self.provider == _OPENAI_PROVIDER:
            return openai is not None and isinstance(exc, openai.AuthenticationError)
        return isinstance(exc, anthropic.AuthenticationError)

    def is_retryable_error(self, exc: Exception) -> bool:
        if isinstance(exc, (httpx.RemoteProtocolError, httpx.ReadError, httpx.ConnectError)):
            return True
        if self.provider == _OPENAI_PROVIDER:
            return openai is not None and isinstance(
                exc,
                (
                    openai.RateLimitError,
                    openai.APIConnectionError,
                    openai.InternalServerError,
                ),
            )
        return isinstance(
            exc,
            (
                anthropic.RateLimitError,
                anthropic.APIConnectionError,
                anthropic.InternalServerError,
            ),
        )

    def is_api_error(self, exc: Exception) -> bool:
        if self.provider == _OPENAI_PROVIDER:
            return openai is not None and isinstance(exc, openai.APIError)
        return isinstance(exc, anthropic.APIError)

    @staticmethod
    def error_message(exc: Exception) -> str:
        return str(getattr(exc, 'message', None) or exc)

    def _anthropic_create_message(
        self,
        *,
        model: str,
        max_tokens: int,
        messages: list[dict[str, Any]],
        system: str | None,
        tools: list[dict[str, Any]] | None,
        temperature: float | None = None,
        top_p: float | None = None,
    ) -> LLMMessage:
        kwargs: dict[str, Any] = dict(
            model=model,
            max_tokens=max_tokens,
            messages=messages,
        )
        if system:
            kwargs['system'] = system
        if tools:
            kwargs['tools'] = tools
        if temperature is not None:
            kwargs['temperature'] = temperature
        if top_p is not None:
            kwargs['top_p'] = top_p
        response = self._client.messages.create(**kwargs)
        usage = _usage_from_anthropic(getattr(response, 'usage', None))
        return LLMMessage(
            content=_normalize_anthropic_content(getattr(response, 'content', [])),
            usage=usage,
        )

    def _openai_create_message(
        self,
        *,
        model: str,
        max_tokens: int,
        messages: list[dict[str, Any]],
        system: str | None,
        tools: list[dict[str, Any]] | None,
        effort: str | None,
        temperature: float | None = None,
        top_p: float | None = None,
    ) -> LLMMessage:
        params = _build_openai_request(
            model=model,
            max_tokens=max_tokens,
            system=system,
            messages=messages,
            tools=tools or [],
            effort=effort,
            stream=False,
            temperature=temperature,
            top_p=top_p,
        )
        response = self._client.chat.completions.create(**params)
        choice = response.choices[0].message if response.choices else None
        usage = _usage_from_openai(getattr(response, 'usage', None))
        return LLMMessage(
            content=_normalize_openai_message(choice),
            usage=usage,
        )


class _AnthropicStream:
    def __init__(
        self,
        *,
        client: Any,
        model: str,
        max_tokens: int,
        messages: list[dict[str, Any]],
        system: str | None,
        tools: list[dict[str, Any]],
        temperature: float | None = None,
        top_p: float | None = None,
    ):
        optional = {k: v for k, v in {'temperature': temperature, 'top_p': top_p}.items() if v is not None}
        self._raw = client.messages.stream(
            model=model,
            max_tokens=max_tokens,
            system=system,
            tools=tools,
            messages=messages,
            **optional,
        )
        self._ctx = None
        self.text_stream: Iterator[str] = iter(())

    def __enter__(self):
        self._ctx = self._raw.__enter__()
        self.text_stream = self._ctx.text_stream
        return self

    def __exit__(self, exc_type, exc, tb):
        return self._raw.__exit__(exc_type, exc, tb)

    def close(self) -> None:
        """Signal cancellation — best-effort close of the underlying stream."""
        try:
            self._raw.close()
        except Exception:
            pass

    def get_final_message(self) -> LLMMessage:
        final = self._ctx.get_final_message()
        return LLMMessage(
            content=_normalize_anthropic_content(getattr(final, 'content', [])),
            usage=_usage_from_anthropic(getattr(final, 'usage', None)),
        )


class _OpenAIStream:
    def __init__(
        self,
        *,
        client: Any,
        model: str,
        max_tokens: int,
        messages: list[dict[str, Any]],
        system: str | None,
        tools: list[dict[str, Any]],
        effort: str | None,
        temperature: float | None = None,
        top_p: float | None = None,
    ):
        self._client = client
        self._params = _build_openai_request(
            model=model,
            max_tokens=max_tokens,
            system=system,
            messages=messages,
            tools=tools,
            effort=effort,
            stream=True,
            temperature=temperature,
            top_p=top_p,
        )
        self._stream = None
        self._text_parts: list[str] = []
        self._tool_calls: dict[int, dict[str, Any]] = {}
        self._usage: LLMUsage | None = None
        self.text_stream: Iterator[str] = iter(())

    def __enter__(self):
        self._stream = self._client.chat.completions.create(**self._params)
        self.text_stream = self._iter_text()
        return self

    def __exit__(self, exc_type, exc, tb):
        self.close()
        return False

    def close(self) -> None:
        if self._stream is not None and hasattr(self._stream, 'close'):
            self._stream.close()

    def _iter_text(self) -> Iterator[str]:
        for chunk in self._stream:
            usage = getattr(chunk, 'usage', None)
            if usage is not None:
                self._usage = _usage_from_openai(usage)
            for choice in _value(chunk, 'choices', []) or []:
                delta = _value(choice, 'delta', {}) or {}
                content = _value(delta, 'content')
                if content:
                    self._text_parts.append(content)
                    yield content
                for tool_call in _value(delta, 'tool_calls', []) or []:
                    index = int(_value(tool_call, 'index', 0) or 0)
                    entry = self._tool_calls.setdefault(index, {
                        'id': '',
                        'name': '',
                        'arguments': '',
                    })
                    tool_id = _value(tool_call, 'id')
                    if tool_id:
                        entry['id'] = tool_id
                    function = _value(tool_call, 'function', {}) or {}
                    name = _value(function, 'name')
                    if name:
                        entry['name'] = name
                    arguments = _value(function, 'arguments')
                    if arguments:
                        entry['arguments'] += arguments

    def get_final_message(self) -> LLMMessage:
        content: list[dict[str, Any]] = []
        text = ''.join(self._text_parts)
        if text:
            content.append({'type': 'text', 'text': text})
        for index in sorted(self._tool_calls):
            tool_call = self._tool_calls[index]
            raw_args = tool_call.get('arguments', '').strip()
            parsed_args: Any = {}
            if raw_args:
                try:
                    parsed_args = json.loads(raw_args)
                except json.JSONDecodeError:
                    parsed_args = {}
            content.append({
                'type': 'tool_use',
                'id': tool_call.get('id', ''),
                'name': tool_call.get('name', ''),
                'input': parsed_args if isinstance(parsed_args, dict) else {},
            })
        return LLMMessage(content=content, usage=self._usage)


def _normalize_anthropic_content(content: Any) -> list[dict[str, Any]]:
    blocks: list[dict[str, Any]] = []
    for block in content or []:
        normalized = _normalize_anthropic_block(block)
        if normalized is not None:
            blocks.append(normalized)
    return blocks


def _normalize_anthropic_block(block: Any) -> dict[str, Any] | None:
    block_type = _value(block, 'type')
    if block_type == 'text':
        return {'type': 'text', 'text': _value(block, 'text', '')}
    if block_type == 'tool_use':
        return {
            'type': 'tool_use',
            'id': _value(block, 'id', ''),
            'name': _value(block, 'name', ''),
            'input': _value(block, 'input', {}) or {},
        }
    if block_type == 'tool_result':
        normalized = {
            'type': 'tool_result',
            'tool_use_id': _value(block, 'tool_use_id', ''),
            'content': _value(block, 'content', ''),
        }
        is_error = _value(block, 'is_error')
        if is_error is not None:
            normalized['is_error'] = bool(is_error)
        return normalized
    if block_type == 'image':
        return {
            'type': 'image',
            'source': _value(block, 'source', {}),
        }
    if isinstance(block, dict):
        return dict(block)
    if hasattr(block, 'model_dump'):
        return block.model_dump()
    return None


def _normalize_openai_message(message: Any) -> list[dict[str, Any]]:
    if message is None:
        return []
    content: list[dict[str, Any]] = []
    text = _extract_openai_text(_value(message, 'content'))
    if text:
        content.append({'type': 'text', 'text': text})
    for tool_call in _value(message, 'tool_calls', []) or []:
        arguments = _value(_value(tool_call, 'function', {}) or {}, 'arguments', '') or ''
        parsed_args: Any = {}
        if arguments:
            try:
                parsed_args = json.loads(arguments)
            except json.JSONDecodeError:
                parsed_args = {}
        content.append({
            'type': 'tool_use',
            'id': _value(tool_call, 'id', ''),
            'name': _value(_value(tool_call, 'function', {}) or {}, 'name', ''),
            'input': parsed_args if isinstance(parsed_args, dict) else {},
        })
    return content


def _extract_openai_text(content: Any) -> str:
    if content is None:
        return ''
    if isinstance(content, str):
        return content
    parts: list[str] = []
    for item in content:
        item_type = _value(item, 'type')
        if item_type == 'text':
            text = _value(item, 'text')
            if isinstance(text, str):
                parts.append(text)
            elif isinstance(text, dict):
                parts.append(str(text.get('value', '')))
    return ''.join(parts)


def _usage_from_anthropic(usage: Any) -> LLMUsage | None:
    if usage is None:
        return None
    return LLMUsage(
        input_tokens=int(_value(usage, 'input_tokens', 0) or 0),
        output_tokens=int(_value(usage, 'output_tokens', 0) or 0),
        cache_read_input_tokens=int(_value(usage, 'cache_read_input_tokens', 0) or 0),
        cache_creation_input_tokens=int(_value(usage, 'cache_creation_input_tokens', 0) or 0),
    )


def _usage_from_openai(usage: Any) -> LLMUsage | None:
    if usage is None:
        return None
    return LLMUsage(
        input_tokens=int(_value(usage, 'prompt_tokens', 0) or 0),
        output_tokens=int(_value(usage, 'completion_tokens', 0) or 0),
    )


def _build_openai_request(
    *,
    model: str,
    max_tokens: int,
    system: str | None,
    messages: list[dict[str, Any]],
    tools: list[dict[str, Any]],
    effort: str | None,
    stream: bool,
    temperature: float | None = None,
    top_p: float | None = None,
) -> dict[str, Any]:
    params: dict[str, Any] = {
        'model': model,
        'messages': _to_openai_messages(system, messages),
        'max_tokens': max_tokens,
        'stream': stream,
    }
    if stream:
        # Required so streamed responses include final usage stats.
        # Without this the OpenAI streaming API omits usage entirely, which
        # would leave the engine's ("usage", ...) event un-fired and break
        # auto-compact triggering for OpenAI-compatible backends.
        params['stream_options'] = {'include_usage': True}
    if tools:
        params['tools'] = [_tool_schema_to_openai(tool) for tool in tools]
    if effort and supports_reasoning_effort(_OPENAI_PROVIDER, model):
        params['reasoning_effort'] = effort
    if temperature is not None:
        params['temperature'] = temperature
    if top_p is not None:
        params['top_p'] = top_p
    return params


def _to_openai_messages(system: str | None, messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    if system:
        out.append({'role': 'system', 'content': sanitize_unicode(system)})

    for message in messages:
        role = message.get('role')
        content = sanitize_unicode(message.get('content', ''))

        if role == 'user' and isinstance(content, list):
            tool_results = [
                block for block in content
                if isinstance(block, dict) and block.get('type') == 'tool_result'
            ]
            if tool_results and len(tool_results) == len(content):
                # OpenAI tool role only accepts string content.
                # Extract images and append them as a follow-up user message.
                pending_images: list[dict[str, Any]] = []
                for block in tool_results:
                    raw = block.get('content', '')
                    if isinstance(raw, list):
                        # Multimodal: split text vs images
                        text_parts = [
                            p.get('text', '') for p in raw
                            if isinstance(p, dict) and p.get('type') == 'text'
                        ]
                        for p in raw:
                            if isinstance(p, dict) and p.get('type') == 'image':
                                source = p.get('source', {})
                                mt = source.get('media_type', 'image/png')
                                d = source.get('data', '')
                                pending_images.append({
                                    'type': 'image_url',
                                    'image_url': {'url': f'data:{mt};base64,{d}'},
                                })
                        out.append({
                            'role': 'tool',
                            'tool_call_id': block.get('tool_use_id', ''),
                            'content': '\n'.join(text_parts) or '',
                        })
                    else:
                        out.append({
                            'role': 'tool',
                            'tool_call_id': block.get('tool_use_id', ''),
                            'content': _tool_result_to_text(raw),
                        })
                # Attach images as a user message so the model can see them.
                if pending_images:
                    out.append({
                        'role': 'user',
                        'content': [
                            {'type': 'text', 'text': 'Here is the screenshot from the previous action.'},
                        ] + pending_images,
                    })
                continue

            out.append({
                'role': 'user',
                'content': _user_content_blocks_to_openai(content),
            })
            continue

        if role == 'assistant' and isinstance(content, list):
            text_parts: list[str] = []
            tool_calls: list[dict[str, Any]] = []
            for block in content:
                if not isinstance(block, dict):
                    continue
                block_type = block.get('type')
                if block_type == 'text':
                    text_parts.append(block.get('text', ''))
                elif block_type == 'tool_use':
                    tool_calls.append({
                        'id': block.get('id', ''),
                        'type': 'function',
                        'function': {
                            'name': block.get('name', ''),
                            'arguments': json.dumps(block.get('input', {}), ensure_ascii=False),
                        },
                    })
            assistant_message: dict[str, Any] = {
                'role': 'assistant',
                'content': ''.join(text_parts) or None,
            }
            if tool_calls:
                assistant_message['tool_calls'] = tool_calls
            out.append(assistant_message)
            continue

        out.append({
            'role': role,
            'content': content,
        })

    return out


def _user_content_blocks_to_openai(content: list[Any]) -> list[dict[str, Any]]:
    parts: list[dict[str, Any]] = []
    for block in content:
        if not isinstance(block, dict):
            continue
        block_type = block.get('type')
        if block_type == 'text':
            parts.append({'type': 'text', 'text': block.get('text', '')})
        elif block_type == 'image':
            source = block.get('source', {})
            media_type = source.get('media_type', 'image/png')
            data = source.get('data', '')
            parts.append({
                'type': 'image_url',
                'image_url': {'url': f'data:{media_type};base64,{data}'},
            })
        elif block_type == 'tool_result':
            # Mixed content (tool_result blocks alongside text/image) isn't a
            # path the engine currently emits, but if it ever does, represent
            # the tool output as text so it isn't silently dropped.
            tool_id = block.get('tool_use_id', '')
            body = _tool_result_to_text(block.get('content', ''))
            parts.append({
                'type': 'text',
                'text': f'[tool_result {tool_id}]\n{body}' if tool_id else body,
            })
    if not parts:
        return [{'type': 'text', 'text': ''}]
    return parts


def _tool_schema_to_openai(tool: dict[str, Any]) -> dict[str, Any]:
    return {
        'type': 'function',
        'function': {
            'name': tool.get('name', ''),
            'description': tool.get('description', ''),
            'parameters': tool.get('input_schema', {}),
        },
    }


def _tool_result_to_text(content: Any) -> str:
    if isinstance(content, str):
        return content
    if content is None:
        return ''
    return json.dumps(content, ensure_ascii=False)


def _value(obj: Any, key: str, default: Any = None) -> Any:
    if obj is None:
        return default
    if isinstance(obj, dict):
        return obj.get(key, default)
    return getattr(obj, key, default)

"""Data flow event payload construction utilities for the cc-mini engine.

This module owns all event-structure knowledge: timestamp helpers, field
normalisation, and payload builders. The engine (core/engine.py) calls these
functions to produce ready-to-emit event dicts, keeping the business logic free
of payload assembly details.

All builders preserve the exact JSONL field order and naming that the
data_flow_reporter renderer expects.
"""

from __future__ import annotations

import copy
from datetime import datetime, timedelta
from typing import Any

from ..core.tool import ToolResult

# ---------------------------------------------------------------------------
# Timestamp helpers
# ---------------------------------------------------------------------------


def iso_now() -> str:
    """Return the current wall-clock time as an ISO-8601 millisecond string."""
    return datetime.now().isoformat(timespec='milliseconds')


def iso_from_monotonic(end_iso: str, duration_seconds: float) -> str:
    """Derive the start timestamp by subtracting *duration_seconds* from
    *end_iso*.

    Falls back to *end_iso* unchanged when the ISO string cannot be parsed.
    """
    try:
        end_dt = datetime.fromisoformat(end_iso)
        return (end_dt - timedelta(seconds=max(duration_seconds, 0.0))).isoformat(
            timespec='milliseconds',
        )
    except Exception:
        return end_iso


# ---------------------------------------------------------------------------
# Value helpers
# ---------------------------------------------------------------------------


def usage_payload(usage: Any) -> dict[str, int]:
    """Normalise an LLM usage object into a plain dict with canonical token
    fields."""
    input_tokens = int(getattr(usage, 'input_tokens', 0) or 0)
    output_tokens = int(getattr(usage, 'output_tokens', 0) or 0)
    return {
        'input_tokens': input_tokens,
        'output_tokens': output_tokens,
        'total_tokens': input_tokens + output_tokens,
        'cache_read_input_tokens': int(getattr(usage, 'cache_read_input_tokens', 0) or 0),
        'cache_creation_input_tokens': int(
            getattr(usage, 'cache_creation_input_tokens', 0) or 0,
        ),
    }


def safe_copy(value: Any) -> Any:
    """Return a deep copy of *value*, falling back to ``str(value)`` on
    error."""
    try:
        return copy.deepcopy(value)
    except Exception:
        return str(value)


# ---------------------------------------------------------------------------
# LLM event payload builders
# ---------------------------------------------------------------------------


def build_llm_ok_payload(
    *,
    call_id: str,
    turn_id: int,
    attempt: int,
    model: str,
    provider: str,
    started_at: str,
    ended_at: str,
    duration_seconds: float,
    usage: Any,
    request: dict[str, Any],
    assistant_content: Any,
) -> dict[str, Any]:
    """Build the payload dict for a successful ``cc_mini_llm_call`` event.

    The field order matches the JSONL schema consumed by data_flow_reporter.
    """
    token_usage = usage_payload(usage) if usage else {}
    return {
        'call_id': call_id,
        'correlation_id': call_id,
        'turn_id': turn_id,
        'attempt': attempt,
        'group_key': f'llm:{model}',
        'group_label': f'LLM · {model}',
        'node_kind': 'llm',
        'model': model,
        'provider': provider,
        'status': 'ok',
        'started_at': started_at,
        'ended_at': ended_at,
        'duration_seconds': duration_seconds,
        'start_ts': iso_from_monotonic(ended_at, duration_seconds),
        'token_usage': token_usage,
        'usage': token_usage,
        'request': request,
        'assistant_content': safe_copy(assistant_content),
    }


def build_llm_error_payload(
    *,
    call_id: str,
    turn_id: int,
    attempt: int,
    model: str,
    provider: str,
    started_at: str,
    ended_at: str,
    duration_seconds: float,
    error_message: str,
    request: dict[str, Any],
) -> dict[str, Any]:
    """Build the payload dict for a failed ``cc_mini_error`` (LLM) event."""
    return {
        'call_id': call_id,
        'correlation_id': call_id,
        'turn_id': turn_id,
        'attempt': attempt,
        'group_key': f'llm:{model}',
        'group_label': f'LLM · {model}',
        'node_kind': 'llm',
        'model': model,
        'provider': provider,
        'status': 'error',
        'message': error_message,
        'started_at': started_at,
        'ended_at': ended_at,
        'duration_seconds': duration_seconds,
        'request': request,
    }


# ---------------------------------------------------------------------------
# Tool event payload builder
# ---------------------------------------------------------------------------


def build_tool_event_payload(
    *,
    tool_name: str,
    tool_input: dict[str, Any],
    call_id: str,
    turn_id: int,
    activity: str | None,
    status: str,
    tool_use_id: str | None = None,
    result: ToolResult | None = None,
    started_at: str | None = None,
    ended_at: str | None = None,
    duration_seconds: float | None = None,
    synthetic: bool = False,
) -> dict[str, Any]:
    """Build the payload dict for a ``cc_mini_tool_call`` or
    ``cc_mini_tool_result`` event.

    Timing fields (started_at / ended_at / duration_seconds) are only included
    when provided — scheduled tool_call events omit them so consumers do not
    mistake placeholder values for real execution measurements.
    """
    payload: dict[str, Any] = {
        'call_id': call_id,
        'correlation_id': call_id,
        'turn_id': turn_id,
        'tool_call_id': tool_use_id or call_id,
        'tool_name': tool_name,
        'tool_input': safe_copy(tool_input),
        'activity': activity,
        'group_key': f'tool:{tool_name}',
        'group_label': tool_name,
        'node_kind': 'tool',
        'status': status,
        'synthetic': synthetic,
    }
    if started_at is not None:
        payload['started_at'] = started_at
    if ended_at is not None:
        payload['ended_at'] = ended_at
    if duration_seconds is not None:
        payload['duration_seconds'] = duration_seconds
    if result is not None:
        payload['tool_result'] = {
            'content': getattr(result, 'content', ''),
            'is_error': bool(getattr(result, 'is_error', False)),
            'content_blocks': safe_copy(getattr(result, 'content_blocks', [])),
        }
        payload['status'] = 'error' if result.is_error else status
    return payload

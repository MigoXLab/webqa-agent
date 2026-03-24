"""Context-local timing accumulators for data-flow breakdown."""

from __future__ import annotations

import contextvars
from typing import Any

_TOOL_TIMING_VAR: contextvars.ContextVar[dict[str, Any] | None] = contextvars.ContextVar(
    'webqa_tool_timing_bucket',
    default=None,
)


def reset_tool_timing_bucket() -> None:
    """Reset tool timing bucket for current async context."""
    _TOOL_TIMING_VAR.set(
        {
            'tool_execution_seconds': 0.0,
            'tool_calls': 0,
            'by_tool': {},
        }
    )


def record_tool_timing(
    tool_name: str,
    duration_seconds: float,
) -> None:
    """Record one tool invocation timing into current async context."""
    bucket = _TOOL_TIMING_VAR.get()
    if bucket is None:
        reset_tool_timing_bucket()
        bucket = _TOOL_TIMING_VAR.get()

    safe_duration = max(float(duration_seconds), 0.0)

    bucket['tool_execution_seconds'] = float(bucket.get('tool_execution_seconds', 0.0)) + safe_duration
    bucket['tool_calls'] = int(bucket.get('tool_calls', 0)) + 1

    by_tool = bucket['by_tool']
    tool_entry = by_tool.get(tool_name, {})
    tool_entry['duration_seconds'] = float(tool_entry.get('duration_seconds', 0.0)) + safe_duration
    tool_entry['calls'] = int(tool_entry.get('calls', 0)) + 1
    by_tool[tool_name] = tool_entry


def get_tool_timing_bucket() -> dict[str, Any]:
    """Get current tool timing bucket snapshot with rounded values."""
    bucket = _TOOL_TIMING_VAR.get()
    if not isinstance(bucket, dict):
        return {
            'tool_execution_seconds': 0.0,
            'tool_calls': 0,
            'by_tool': {},
        }
    # Round seconds to 2 decimal places for readability
    result = {
        'tool_execution_seconds': round(float(bucket.get('tool_execution_seconds', 0.0)), 2),
        'tool_calls': int(bucket.get('tool_calls', 0)),
        'by_tool': {},
    }
    for name, entry in dict(bucket.get('by_tool', {})).items():
        result['by_tool'][name] = {
            'duration_seconds': round(float(entry.get('duration_seconds', 0.0)), 2),
            'calls': int(entry.get('calls', 0)),
        }
    return result


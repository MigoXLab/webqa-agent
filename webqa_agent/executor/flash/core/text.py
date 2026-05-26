from __future__ import annotations

from typing import Any


def replace_invalid_unicode(text: str) -> str:
    """Replace lone surrogate code points with U+FFFD.

    Some terminals/paste paths can surface undecodable input as isolated
    surrogate code points. Those strings cannot be written as UTF-8 and will
    break history persistence and JSON request encoding.
    """
    if not text:
        return text
    if not any(0xD800 <= ord(ch) <= 0xDFFF for ch in text):
        return text
    return ''.join('\uFFFD' if 0xD800 <= ord(ch) <= 0xDFFF else ch for ch in text)


def sanitize_unicode(value: Any) -> Any:
    """Recursively sanitize strings so they can be safely UTF-8 encoded."""
    if isinstance(value, str):
        return replace_invalid_unicode(value)
    if isinstance(value, list):
        return [sanitize_unicode(item) for item in value]
    if isinstance(value, dict):
        return {key: sanitize_unicode(item) for key, item in value.items()}
    return value

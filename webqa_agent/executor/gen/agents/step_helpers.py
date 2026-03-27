"""Step-level helper functions for agent execution.

Provides failure indicator detection, i18n summary wrappers, user summary
parsing, step similarity checking, and message sanitization.
"""

__all__ = [
    'build_user_summary',
    'contains_failure_indicators',
    'i18n',
    'is_similar_step',
    'make_final_summary',
    'parse_user_summary',
    'sanitize_message_for_summary',
]

import re
from typing import Optional

from webqa_agent.executor.gen.utils.summary_utils import (i18n_select,
                                                          make_user_summary)

# ---------------------------------------------------------------------------
# Failure indicator detection
# ---------------------------------------------------------------------------


def contains_failure_indicators(text: str) -> bool:
    """Check if text contains any failure indicators.

    Args:
        text: Tool output or intermediate output to check

    Returns:
        bool: True if any failure indicator is found
    """
    if not text:
        return False

    text_lower = text.lower()
    failure_tags = ['[failure]', '[critical_error:']
    return any(tag in text_lower for tag in failure_tags)


# ---------------------------------------------------------------------------
# i18n / summary wrappers
# ---------------------------------------------------------------------------

def i18n(language: str, zh: str, en: str) -> str:
    """Select language-appropriate string (shorthand for i18n_select)."""
    return i18n_select(language, zh, en)


def make_final_summary(language: str, template_zh: str, template_en: str) -> str:
    """Select language-appropriate FINAL_SUMMARY string.

    Semantic alias kept for readability at call sites that construct
    final_summary values.
    """
    return i18n_select(language, template_zh, template_en)


def build_user_summary(
    language: str,
    status: str,
    objective: str,
    reason: str = '',
    exception: Optional[Exception] = None,
) -> str:
    """Generate user-facing summary (shorthand for make_user_summary)."""
    return make_user_summary(language, status, objective, reason, exception=exception)


# ---------------------------------------------------------------------------
# User summary parsing
# ---------------------------------------------------------------------------

_USER_SUMMARY_PATTERN = re.compile(r'USER_SUMMARY:\s*(.+)', re.IGNORECASE)


def parse_user_summary(llm_output: str) -> Optional[str]:
    """Extract USER_SUMMARY line from LLM output."""
    if not llm_output:
        return None
    match = _USER_SUMMARY_PATTERN.search(llm_output)
    return match.group(1).strip() if match else None


# ---------------------------------------------------------------------------
# Step similarity (promoted from nested function in agent_worker_node)
# ---------------------------------------------------------------------------

def is_similar_step(step1: dict, step2: dict) -> bool:
    """Check if two steps are similar to avoid duplicates."""
    if 'action' in step1 and 'action' in step2:
        return (
            step1['action'].lower().strip()
            == step2['action'].lower().strip()
        )
    if 'verify' in step1 and 'verify' in step2:
        return (
            step1['verify'].lower().strip()
            == step2['verify'].lower().strip()
        )
    return False


# ---------------------------------------------------------------------------
# Message sanitization (promoted from nested function in agent_worker_node)
# ---------------------------------------------------------------------------

_BASE64_PATTERN = re.compile(r'data:image/[^;]+;base64,[A-Za-z0-9+/=]+')
_HTML_TAG_PATTERN = re.compile(r'<[^>]+>')
_ERROR_KEYWORD_PATTERN = re.compile(
    r'\b(denied|blocked|failed|error|forbidden|hack|exploit|inject)\b',
    re.IGNORECASE,
)
_DOM_DUMP_PATTERN = re.compile(
    r'pageDescription.*?(?===|$)',
    re.DOTALL,
)


def sanitize_message_for_summary(msg: object, max_length: int = 250) -> str:
    """Clean message content to avoid Azure OpenAI content filter triggers.

    Removes:
    - Base64 image URLs (main trigger)
    - HTML tags (XSS detection)
    - Error keywords that trigger safety filters
    - DOM dumps
    """
    # Extract content
    if hasattr(msg, 'content'):
        content = str(msg.content)
    else:
        content = str(msg)

    # Remove base64 image URLs (primary trigger for content filter)
    content = _BASE64_PATTERN.sub('[IMAGE_REMOVED]', content)

    # Remove HTML tags (can trigger XSS detection)
    content = _HTML_TAG_PATTERN.sub('', content)

    # Remove error keywords that may trigger content filter
    content = _ERROR_KEYWORD_PATTERN.sub('[X]', content)

    # Remove DOM dumps (can be large and trigger filters)
    if 'pageDescription' in content or 'dom_tree' in content:
        content = _DOM_DUMP_PATTERN.sub('[DOM_SUMMARY]', content)

    # Truncate to max length
    return content[:max_length]

"""System error classifier for separating infrastructure errors from product
defects.

This module provides utilities to distinguish between:
- **System errors**: LLM timeouts, API failures, output parsing errors, SDK exceptions
  → Should be marked as 'warning' with neutral summary (not the product's fault)
- **Business errors**: Element not found, assertion failures, page crashes
  → Should be marked as 'failed' (potential product defect)

The classifier uses a three-layer detection strategy:
1. Exception type matching (asyncio.TimeoutError, OutputParserException)
2. Exception source module prefix matching (langchain, openai, anthropic, google.generativeai)
3. Error message pattern matching (covers llm_api.py wrapped ValueError messages)

Usage:
    from webqa_agent.executor.gen.utils.error_classifier import (
        get_system_error_summary, is_system_error,
    )

    try:
        result = await llm_call()
    except Exception as e:
        if is_system_error(e):
            status = 'warning'
            summary = get_system_error_summary(e, language='zh-CN')
        else:
            status = 'failed'
"""

import asyncio
import re
from typing import Tuple

# LangChain OutputParserException — optional import
try:
    from langchain_core.exceptions import OutputParserException

    _LANGCHAIN_PARSER_EXCEPTION: Tuple[type, ...] = (OutputParserException,)
except ImportError:
    _LANGCHAIN_PARSER_EXCEPTION = ()

# Layer 1: Exception types that are always system errors
_SYSTEM_ERROR_EXCEPTION_TYPES: Tuple[type, ...] = (
    asyncio.TimeoutError,
    *_LANGCHAIN_PARSER_EXCEPTION,
)

# Layer 2: Exception source module prefixes (LangChain/SDK framework exceptions)
# Uses prefix matching to avoid false positives (e.g. 'google' matching 'google.protobuf')
_SYSTEM_ERROR_MODULE_PREFIXES = (
    'langchain',
    'openai',
    'anthropic',
    'google.generativeai',
    'google.ai',
)

# Layer 3: Error message patterns
# Covers two paths:
#   a) llm_api.py wrapped ValueError messages (direct LLM calls)
#   b) OpenAI SDK exception __str__ format (via agent_executor.ainvoke())
# NOTE: Patterns are matched against str(exception).lower(). Must be specific
# enough to avoid matching business-level errors (e.g. a website returning 401).
_SYSTEM_ERROR_PATTERNS = (
    # OpenAI SDK standard exception format: "Error code: XXX - {JSON}"
    # Covers all HTTP errors (400/401/403/429/500/502/503/504) from any provider
    # using the OpenAI SDK (OpenAI, Gemini via compatible API, Azure OpenAI).
    # This is the primary catch-all for agent_executor.ainvoke() exceptions that
    # bypass llm_api.py's error wrapping.
    'error code:',
    # llm_api.py wrapped error patterns (direct LLM call path)
    'api connection',
    'connection failed',
    'rate limit',
    'status 429',
    'api error',
    'status 500',
    'status 502',
    'status 503',
    'status 504',
    'request failed',
    'chat completions api',
    'messages api request failed',       # Anthropic
    'responses api request failed',      # OpenAI Responses API
    'invalid response format',
    'relay service',
    'api key',                           # API key authentication errors (narrowed)
    'api authentication',                # API authentication errors (narrowed)
    'quota exceeded',
    'overloaded',
    'bad gateway',
    'service unavailable',
    'gateway timeout',
)

# Deprecated: use get_system_error_summary() for categorized summaries.
# Kept for backward compatibility with external consumers.
SYSTEM_ERROR_SUMMARY_ZH = 'FINAL_SUMMARY: 系统报错，请重新执行'
SYSTEM_ERROR_SUMMARY_EN = 'FINAL_SUMMARY: System error occurred, please retry the test'


def is_system_error(exception: Exception) -> bool:
    """Determine if an exception is a system-level error (LLM/agent framework).

    System errors are infrastructure problems (LLM timeout, API rate limit,
    SDK errors) that should NOT be attributed to the product under test.

    Three-layer detection:
    1. Exception type direct match (asyncio.TimeoutError, OutputParserException)
    2. Exception source module prefix match (langchain, openai, anthropic, google.generativeai)
    3. Error message pattern match (covers llm_api.py wrapped ValueError
       and OpenAI SDK standard exception format "Error code: XXX")

    Args:
        exception: The caught exception to classify

    Returns:
        True if the exception is a system-level error, False otherwise
    """
    # Layer 1: Exception type direct match
    if isinstance(exception, _SYSTEM_ERROR_EXCEPTION_TYPES):
        return True

    # Layer 2: Exception source module (prefix match)
    module = type(exception).__module__ or ''
    if any(module.startswith(prefix) for prefix in _SYSTEM_ERROR_MODULE_PREFIXES):
        return True

    # Layer 3: Error message pattern match (covers llm_api.py wrapped ValueError)
    msg = str(exception).lower()
    if any(pattern in msg for pattern in _SYSTEM_ERROR_PATTERNS):
        return True

    return False


# ============================================================================
# System error summary classification (5 categories by user action)
# ============================================================================

# Regex for extracting HTTP status code from "Error code: XXX" or "error code: XXX"
_ERROR_CODE_RE = re.compile(r'error code:\s*(\d{3})', re.IGNORECASE)

# Category 1: Authentication/configuration errors (not retryable without fix)
_AUTH_CONFIG_PATTERNS = ('api key', 'api authentication')
_AUTH_CONFIG_STATUS_CODES = frozenset({401, 403})

# Category 2: Rate limiting (retryable after delay)
_RATE_LIMIT_PATTERNS = ('rate limit', 'quota exceeded', 'overloaded')
_RATE_LIMIT_STATUS_CODES = frozenset({429})

# Category 3: Service unavailable (retryable later)
_SERVICE_UNAVAILABLE_PATTERNS = (
    'api connection', 'connection failed', 'bad gateway',
    'service unavailable', 'gateway timeout', 'relay service',
    'request failed', 'chat completions api',
    'messages api request failed', 'responses api request failed',
    'api error',
)
_SERVICE_UNAVAILABLE_STATUS_CODES = frozenset({500, 502, 503, 504})

# Category summaries: (zh, en) tuples
_SUMMARY_AUTH_CONFIG = (
    'FINAL_SUMMARY: API 密钥或认证配置有误，请检查后重新执行',
    'FINAL_SUMMARY: API key or authentication misconfigured, please verify settings and retry',
)
_SUMMARY_RATE_LIMIT = (
    'FINAL_SUMMARY: API 调用频率超限或额度不足，请稍后重新执行',
    'FINAL_SUMMARY: API rate limit or quota exceeded, please wait and retry',
)
_SUMMARY_SERVICE_UNAVAILABLE = (
    'FINAL_SUMMARY: AI 服务暂时不可用，请稍后重新执行',
    'FINAL_SUMMARY: AI service temporarily unavailable, please retry later',
)
_SUMMARY_AI_RESPONSE = (
    'FINAL_SUMMARY: AI 响应异常，请重新执行',
    'FINAL_SUMMARY: AI response error, please retry the test',
)
_SUMMARY_SYSTEM_ERROR = (
    'FINAL_SUMMARY: 系统报错，请重新执行',
    'FINAL_SUMMARY: System error occurred, please retry the test',
)


def get_system_error_summary(exception: Exception, language: str) -> str:
    """Classify a system error and return an actionable summary message.

    Uses priority-ordered matching (first match wins) across 5 categories:
    1. Auth/config errors (401/403, API key) — fix config, not retryable
    2. Rate limiting (429, quota) — wait then retry
    3. Service unavailable (5xx, connection) — retry later
    4. AI response error (OutputParserException, invalid format) — model issue
    5. System error (catch-all: timeout, unknown) — infrastructure issue

    Args:
        exception: The system-level exception to classify
        language: Language code (e.g. 'zh-CN', 'en-US')

    Returns:
        Localized FINAL_SUMMARY string for the error category
    """
    use_zh = (language or '').startswith('zh')
    msg = str(exception).lower()

    # Extract HTTP status code if present (e.g. "Error code: 429")
    code_match = _ERROR_CODE_RE.search(msg)
    status_code = int(code_match.group(1)) if code_match else None

    # Priority 1: Authentication / configuration errors
    if status_code in _AUTH_CONFIG_STATUS_CODES or any(
        p in msg for p in _AUTH_CONFIG_PATTERNS
    ):
        zh, en = _SUMMARY_AUTH_CONFIG
        return zh if use_zh else en

    # Priority 2: Rate limiting
    if status_code in _RATE_LIMIT_STATUS_CODES or any(
        p in msg for p in _RATE_LIMIT_PATTERNS
    ):
        zh, en = _SUMMARY_RATE_LIMIT
        return zh if use_zh else en

    # Priority 3: Service unavailable
    if status_code in _SERVICE_UNAVAILABLE_STATUS_CODES or any(
        p in msg for p in _SERVICE_UNAVAILABLE_PATTERNS
    ):
        zh, en = _SUMMARY_SERVICE_UNAVAILABLE
        return zh if use_zh else en

    # Priority 4: AI response error (LLM output parsing / format issues)
    # Must be checked BEFORE SDK module fallback, because OutputParserException
    # lives under langchain_core but is a model output issue, not service outage.
    if isinstance(exception, _LANGCHAIN_PARSER_EXCEPTION) or \
            'invalid response format' in msg:
        zh, en = _SUMMARY_AI_RESPONSE
        return zh if use_zh else en

    # SDK module fallback: other SDK exceptions → service unavailable
    module = type(exception).__module__ or ''
    if any(module.startswith(prefix) for prefix in _SYSTEM_ERROR_MODULE_PREFIXES):
        zh, en = _SUMMARY_SERVICE_UNAVAILABLE
        return zh if use_zh else en

    # Priority 5: System error (catch-all — timeout, unknown infrastructure)
    zh, en = _SUMMARY_SYSTEM_ERROR
    return zh if use_zh else en

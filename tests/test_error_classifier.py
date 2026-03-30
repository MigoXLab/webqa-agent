"""Tests for the system error classifier.

Tests cover:
- is_system_error: Three-layer detection strategy
  - Layer 1: Exception type matching
  - Layer 2: Exception source module matching
  - Layer 3: Error message pattern matching
- Non-system errors: Business/tool-level exceptions
"""

import asyncio

import pytest

from webqa_agent.executor.gen.utils.error_classifier import (
    get_system_error_summary, is_system_error)

# ============================================================================
# Layer 1: Exception type matching
# ============================================================================


class TestExceptionTypeMatching:
    """Test direct exception type detection."""

    def test_timeout_error_is_system_error(self) -> None:
        assert is_system_error(asyncio.TimeoutError()) is True

    def test_output_parser_exception_is_system_error(self) -> None:
        """OutputParserException from langchain_core should be detected."""
        try:
            from langchain_core.exceptions import OutputParserException

            exc = OutputParserException('Failed to parse LLM output')
            assert is_system_error(exc) is True
        except ImportError:
            pytest.skip('langchain_core not installed')


# ============================================================================
# Layer 2: Exception source module matching
# ============================================================================


def _make_module_exception(module: str, msg: str = 'error') -> Exception:
    """Create an exception whose __module__ is set to the given value."""

    class FakeModuleError(Exception):
        pass

    FakeModuleError.__module__ = module
    return FakeModuleError(msg)


class TestModuleMatching:
    """Test exception source module detection."""

    @pytest.mark.parametrize('module', [
        pytest.param('langchain_openai.chat_models', id='langchain'),
        pytest.param('openai._exceptions', id='openai'),
        pytest.param('anthropic._exceptions', id='anthropic'),
        pytest.param('google.generativeai.errors', id='google_genai'),
    ])
    def test_sdk_module_exception_is_system_error(self, module: str) -> None:
        assert is_system_error(_make_module_exception(module)) is True


# ============================================================================
# Layer 3: Error message pattern matching
# ============================================================================


class TestMessagePatternMatching:
    """Test error message pattern detection (covers llm_api.py wrapped
    ValueError)."""

    @pytest.mark.parametrize('message', [
        # OpenAI SDK standard exception format "Error code: XXX - {JSON}"
        pytest.param(
            "Error code: 400 - {'error': {'message': \"Unable to submit request because "
            "`execute_ui_action` functionDeclaration\", 'type': 'upstream_error'}}",
            id='gemini_400_upstream',
        ),
        pytest.param(
            "Error code: 400 - {'error': {'message': \"An assistant message with "
            "'tool_calls' must be followed by tool messages\", 'type': 'invalid_request_error'}}",
            id='openai_400_tool_calls',
        ),
        pytest.param("Error code: 429 - {'error': {'message': 'Rate limit'}}", id='sdk_429'),
        pytest.param("Error code: 500 - {'error': {'message': 'Internal'}}", id='sdk_500'),
        pytest.param("Error code: 401 - {'error': {'message': 'Invalid key'}}", id='sdk_401'),
        # llm_api.py wrapped error patterns
        pytest.param('Chat Completions API connection failed: Connection refused', id='api_connection'),
        pytest.param('Rate limit exceeded for model gpt-4', id='rate_limit'),
        pytest.param('API request failed with Status 500', id='status_500'),
        pytest.param('Request rejected with status 429', id='status_429'),
        pytest.param('Anthropic Messages API request failed: timeout', id='anthropic_messages_api'),
        pytest.param('OpenAI Responses API request failed: internal error', id='openai_responses_api'),
        pytest.param('Relay service returned error 503', id='relay_service'),
        pytest.param('Quota exceeded for this API key', id='quota_exceeded'),
        pytest.param('Model is overloaded, please retry', id='overloaded'),
        pytest.param('Bad gateway from upstream', id='bad_gateway'),
        pytest.param('Service unavailable, try again later', id='service_unavailable'),
        pytest.param('Gateway timeout after 30s', id='gateway_timeout'),
        pytest.param('Invalid API key provided', id='api_key'),
        pytest.param('API authentication failed', id='api_authentication'),
        pytest.param('Invalid response format from LLM', id='invalid_response_format'),
    ])
    def test_error_message_is_system_error(self, message: str) -> None:
        assert is_system_error(ValueError(message)) is True


# ============================================================================
# Non-system errors (should return False)
# ============================================================================


class TestNonSystemErrors:
    """Test that business/tool-level exceptions are NOT classified as system
    errors."""

    @pytest.mark.parametrize('exc', [
        pytest.param(KeyError('missing_key'), id='key_error'),
        pytest.param(IndexError('list index out of range'), id='index_error'),
        pytest.param(ValueError('Invalid argument: expected positive number'), id='generic_value_error'),
        pytest.param(RuntimeError('Element not found on page'), id='runtime_error'),
        pytest.param(AssertionError('Expected title to match'), id='assertion_error'),
        pytest.param(FileNotFoundError('Screenshot path not found'), id='file_not_found'),
        pytest.param(TypeError("unsupported operand type(s) for +: 'int' and 'str'"), id='type_error'),
    ])
    def test_business_exception_not_system_error(self, exc: Exception) -> None:
        assert is_system_error(exc) is False


# ============================================================================
# False-positive boundary tests (must NOT be classified as system errors)
# ============================================================================


class TestFalsePositiveBoundary:
    """Regression tests ensuring business-level exceptions with similar wording
    are NOT misclassified as system errors."""

    def test_website_authentication_page_not_system(self) -> None:
        """Website authentication issues are product defects, not system
        errors."""
        exc = ValueError('The authentication page loaded correctly')
        assert is_system_error(exc) is False

    def test_website_authorization_denied_not_system(self) -> None:
        """Authorization denied on tested website is a product issue."""
        exc = RuntimeError('User authorization denied on dashboard')
        assert is_system_error(exc) is False

    def test_target_server_error_not_system(self) -> None:
        """Server error on the tested website is a product defect."""
        exc = ValueError('Target website returned 500 Internal Server Error')
        assert is_system_error(exc) is False

    def test_google_protobuf_module_not_system(self) -> None:
        """Exceptions from google.protobuf should not match."""
        assert is_system_error(_make_module_exception('google.protobuf.message')) is False

    def test_module_none_not_system(self) -> None:
        """Dynamically created exceptions with __module__=None should not
        crash."""

        class NoneModuleError(Exception):
            pass

        NoneModuleError.__module__ = None  # type: ignore[assignment]
        assert is_system_error(NoneModuleError('some error')) is False

    def test_empty_value_error_not_system(self) -> None:
        assert is_system_error(ValueError('')) is False


# ============================================================================
# get_system_error_summary: 5-category classification
# ============================================================================


class TestGetSystemErrorSummaryAuthConfig:
    """Category 1: Authentication / configuration errors."""

    def test_api_key_error_zh(self) -> None:
        summary = get_system_error_summary(ValueError('Invalid API key'), 'zh-CN')
        assert 'API 密钥' in summary

    def test_api_key_error_en(self) -> None:
        summary = get_system_error_summary(ValueError('Invalid API key'), 'en-US')
        assert 'API key' in summary

    def test_api_authentication_error(self) -> None:
        summary = get_system_error_summary(ValueError('API authentication failed'), 'zh-CN')
        assert '认证配置' in summary

    def test_error_code_401(self) -> None:
        summary = get_system_error_summary(
            ValueError("Error code: 401 - {'error': 'Unauthorized'}"), 'en-US'
        )
        assert 'authentication' in summary.lower()

    def test_error_code_403(self) -> None:
        summary = get_system_error_summary(
            ValueError("Error code: 403 - {'error': 'Forbidden'}"), 'zh-CN'
        )
        assert '认证配置' in summary


class TestGetSystemErrorSummaryRateLimit:
    """Category 2: Rate limiting errors."""

    def test_rate_limit_zh(self) -> None:
        summary = get_system_error_summary(ValueError('Rate limit exceeded'), 'zh-CN')
        assert '频率超限' in summary

    def test_quota_exceeded_en(self) -> None:
        summary = get_system_error_summary(ValueError('Quota exceeded'), 'en-US')
        assert 'quota' in summary.lower()

    def test_error_code_429(self) -> None:
        summary = get_system_error_summary(
            ValueError("Error code: 429 - {'error': 'Too many requests'}"), 'zh-CN'
        )
        assert '频率超限' in summary

    def test_overloaded(self) -> None:
        summary = get_system_error_summary(ValueError('Model is overloaded'), 'en-US')
        assert 'rate limit' in summary.lower()


class TestGetSystemErrorSummaryServiceUnavailable:
    """Category 3: Service unavailable errors."""

    def test_connection_failed_zh(self) -> None:
        summary = get_system_error_summary(ValueError('API connection failed'), 'zh-CN')
        assert '不可用' in summary

    def test_bad_gateway_en(self) -> None:
        summary = get_system_error_summary(ValueError('Bad gateway'), 'en-US')
        assert 'unavailable' in summary.lower()

    def test_error_code_500(self) -> None:
        summary = get_system_error_summary(
            ValueError("Error code: 500 - {'error': 'Internal'}"), 'en-US'
        )
        assert 'unavailable' in summary.lower()

    def test_error_code_502(self) -> None:
        summary = get_system_error_summary(
            ValueError("Error code: 502 - {'error': 'Bad Gateway'}"), 'zh-CN'
        )
        assert '不可用' in summary

    def test_sdk_module_exception(self) -> None:
        """SDK module exceptions without matching message → service
        unavailable."""
        exc = _make_module_exception('openai._exceptions', 'unknown error')
        summary = get_system_error_summary(exc, 'zh-CN')
        assert '不可用' in summary


class TestGetSystemErrorSummaryAIResponse:
    """Category 4: AI response error (model output issues only)."""

    def test_output_parser_exception_zh(self) -> None:
        """OutputParserException → AI response error."""
        try:
            from langchain_core.exceptions import OutputParserException

            exc = OutputParserException('Failed to parse LLM output')
            summary = get_system_error_summary(exc, 'zh-CN')
            assert '响应异常' in summary
        except ImportError:
            pytest.skip('langchain_core not installed')

    def test_invalid_response_format_en(self) -> None:
        summary = get_system_error_summary(
            ValueError('Invalid response format from LLM'), 'en-US'
        )
        assert 'response error' in summary.lower()


class TestGetSystemErrorSummarySystemError:
    """Category 5: System error (catch-all — timeout, unknown)."""

    def test_timeout_error_zh(self) -> None:
        """Timeout is a system issue, not an AI issue."""
        summary = get_system_error_summary(asyncio.TimeoutError(), 'zh-CN')
        assert '系统报错' in summary

    def test_timeout_error_en(self) -> None:
        summary = get_system_error_summary(asyncio.TimeoutError(), 'en-US')
        assert 'system error' in summary.lower()

    def test_generic_unknown_error(self) -> None:
        """Unrecognized error falls to system catch-all."""
        summary = get_system_error_summary(ValueError('something weird'), 'zh-CN')
        assert '系统报错' in summary


class TestGetSystemErrorSummaryPriority:
    """Priority ordering: auth > rate limit > service > catch-all."""

    def test_api_key_with_rate_limit_message_matches_auth(self) -> None:
        """If message contains both 'api key' and 'rate limit', auth wins."""
        exc = ValueError('API key rate limit exceeded')
        summary = get_system_error_summary(exc, 'zh-CN')
        assert '认证配置' in summary

    def test_error_code_429_overrides_connection_pattern(self) -> None:
        """HTTP 429 in error code should match rate limit, not service
        unavailable."""
        exc = ValueError('Error code: 429 - connection failed')
        summary = get_system_error_summary(exc, 'zh-CN')
        assert '频率超限' in summary

    def test_none_language_defaults_to_english(self) -> None:
        """None language should not crash and should fallback to English."""
        summary = get_system_error_summary(ValueError('Rate limit'), None)
        assert 'rate limit' in summary.lower()

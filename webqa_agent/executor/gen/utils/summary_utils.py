"""Shared i18n and user_summary helpers for gen-mode execution.

Used by both execute_agent.py (per-case) and graph.py (timeout/exception).
"""

from __future__ import annotations

__all__ = ['i18n_select', 'make_user_summary']

_PUNCT_STRIP = '。！？.!?，,；;：:、… '


def i18n_select(language: str, zh: str, en: str) -> str:
    """Select language-appropriate string."""
    return zh if language == 'zh-CN' else en


def make_user_summary(
    language: str,
    status: str,
    objective: str,
    reason: str = '',
    exception: Exception | None = None,
) -> str:
    """Generate user-facing summary in business language.

    Args:
        language: 'zh-CN' or other (defaults to English).
        status: 'passed', 'warning', or 'failed'.
        objective: Business objective being tested.
        reason: Optional extra context appended to the base template.
        exception: When provided with status='warning', classifies the system
            error via P1-P5 (API auth / rate limit / service / response /
            generic) and generates a specific actionable message instead of
            the generic warning template.  Examples:
              "搜索功能，API 密钥或认证配置有误，请检查后重新执行"  (P1)
              "搜索功能，AI 服务暂时不可用，请稍后重新执行"          (P3)
              "搜索功能，系统报错，请重新执行"                       (P5)

    Returns:
        Human-readable summary string.
    """
    obj = objective.rstrip(_PUNCT_STRIP)

    # System-error path: use P1-P5 classification for precise actionable message.
    # Lazy import avoids a module-level dependency on error_classifier.
    if status == 'warning' and exception is not None:
        from webqa_agent.executor.gen.utils.error_classifier import \
            get_system_error_summary  # noqa: PLC0415
        raw = get_system_error_summary(exception, language)
        detail = raw.removeprefix('FINAL_SUMMARY: ').strip()
        return i18n_select(language, f'{obj}，{detail}', f'{obj}: {detail}')

    # Template path.
    is_zh = language == 'zh-CN'
    if is_zh:
        templates = {
            'passed': f'{obj}，该用例验证通过。',
            'warning': f'{obj}，系统错误导致测试中断，非产品缺陷。',
            'failed': f'{obj}，该用例验证未通过。',
        }
    else:
        templates = {
            'passed': f'{obj}, test case verified successfully.',
            'warning': f'{obj} test was interrupted due to a system error, not a product defect.',
            'failed': f'{obj}, test case verification failed.',
        }

    base = templates.get(status, templates['failed'])
    if not reason:
        return base
    return f'{base}{reason}' if is_zh else f'{base} {reason}'

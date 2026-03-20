"""Shared i18n and user_summary helpers for gen-mode execution.

Used by both execute_agent.py (per-case) and graph.py (timeout/exception).
"""

__all__ = ['i18n_select', 'make_user_summary']


def i18n_select(language: str, zh: str, en: str) -> str:
    """Select language-appropriate string."""
    return zh if language == 'zh-CN' else en


def make_user_summary(
    language: str,
    status: str,
    objective: str,
    reason: str = '',
) -> str:
    """Generate user-facing summary in business language.

    Args:
        language: 'zh-CN' or other (defaults to English).
        status: 'passed', 'warning', or 'failed'.
        objective: Business objective being tested.
        reason: Optional extra context appended to the summary.

    Returns:
        Human-readable summary string.
    """
    is_zh = language == 'zh-CN'

    if is_zh:
        templates = {
            'passed': f'{objective}验证通过。',
            'warning': f'{objective}，AI 服务调用异常，测试中断，非产品缺陷。',
            'failed': f'{objective}验证未通过。',
        }
    else:
        templates = {
            'passed': f'{objective} verified successfully.',
            'warning': f'{objective} was interrupted due to an AI service issue, not a product defect.',
            'failed': f'{objective} verification failed.',
        }

    base = templates.get(status, templates['failed'])
    if not reason:
        return base
    return f'{base}{reason}' if is_zh else f'{base} {reason}'

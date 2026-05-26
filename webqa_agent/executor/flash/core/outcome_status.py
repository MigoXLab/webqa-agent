"""Parse ``<final_outcome>`` and derive pass/fail (HTML report + Display
progress)."""
from __future__ import annotations

import json
import re
from typing import Any

_FINAL_OUTCOME_TAG_RE = re.compile(
    r'<final_outcome>\s*(\{.*?\})\s*</final_outcome>',
    re.DOTALL | re.IGNORECASE,
)


def extract_final_outcome(final_text: str) -> dict[str, Any] | None:
    """Last ``<final_outcome>{...}`` JSON, or None if missing/invalid."""
    if not (final_text or '').strip():
        return None
    matches = _FINAL_OUTCOME_TAG_RE.findall(final_text)
    if not matches:
        return None
    try:
        parsed = json.loads(matches[-1])
    except (TypeError, ValueError):
        return None
    if not isinstance(parsed, dict):
        return None
    return parsed


def strip_final_outcome_block(final_text: str) -> str:
    """User-facing text without the machine block."""
    if not final_text:
        return ''
    return _FINAL_OUTCOME_TAG_RE.sub('', final_text).strip()


def derive_status(
    *,
    aborted: bool,
    failed_count: int,
    outcome: dict[str, Any] | None,
) -> tuple[str, str]:
    """Return (``'passed'``|``'failed'``|``'warning'``, source tag for
    metrics/debug)."""
    if aborted:
        return 'failed', 'aborted'
    if isinstance(outcome, dict):
        # Prefer explicit status field if present and valid
        explicit = outcome.get('status')
        if explicit in ('passed', 'failed', 'warning'):
            return explicit, 'final_outcome'
        # Fallback: derive from objective_achieved bool
        if isinstance(outcome.get('objective_achieved'), bool):
            oa = bool(outcome['objective_achieved'])
            return (('passed', 'final_outcome') if oa else ('failed', 'final_outcome'))
    if failed_count:
        return 'failed', 'step_fallback'
    return 'passed', 'step_fallback'

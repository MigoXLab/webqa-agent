"""Token usage normalization and LLM timing instrumentation.

Provides callback-based LLM duration tracking, provider-agnostic token
normalization, and step-level time breakdown computation.
"""

__all__ = [
    'LONG_STEPS',
    'MIN_RECOVERY_CONFIDENCE',
    'RETRY_STABILIZATION_DELAY',
    'StepLLMTimingCallback',
    'build_time_breakdown',
    'extract_token_usage_from_result',
    'instrumented_ainvoke',
]

import logging
import time
from typing import Any

from langchain_core.callbacks import BaseCallbackHandler
from langchain_core.messages import AIMessage

from webqa_agent.llm.llm_api import (accumulate_llm_duration_stats,
                                     extract_usage_details)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
LONG_STEPS = 30
RETRY_STABILIZATION_DELAY = 1.0
MIN_RECOVERY_CONFIDENCE = 0.7


# ---------------------------------------------------------------------------
# Token usage normalization
# ---------------------------------------------------------------------------

def _normalize_token_usage(raw: Any) -> dict[str, int]:
    """Normalize a provider-agnostic token usage dict/object to standard 3-key
    dict.

    Handles both OpenAI style (prompt_tokens/completion_tokens) and
    Anthropic/LangChain style (input_tokens/output_tokens).  Always returns
    ``{'prompt_tokens': int, 'completion_tokens': int, 'total_tokens': int}``
    with 0 defaults.
    """
    if raw is None:
        return {'prompt_tokens': 0, 'completion_tokens': 0, 'total_tokens': 0}
    d = raw if isinstance(raw, dict) else (dict(raw) if hasattr(raw, '__iter__') else {})
    prompt = int(d.get('prompt_tokens', 0) or d.get('input_tokens', 0))
    completion = int(d.get('completion_tokens', 0) or d.get('output_tokens', 0))
    total = int(d.get('total_tokens', 0))
    if total == 0:
        total = prompt + completion
    return {'prompt_tokens': prompt, 'completion_tokens': completion, 'total_tokens': total}


# ---------------------------------------------------------------------------
# LangChain callback for per-step LLM timing
# ---------------------------------------------------------------------------

class StepLLMTimingCallback(BaseCallbackHandler):
    """Collect llm call durations for one step execution."""

    def __init__(self) -> None:
        self._starts: dict[str, float] = {}
        self._duration_seconds: float = 0.0

    def reset_step(self) -> None:
        self._starts.clear()
        self._duration_seconds = 0.0

    def consume_step_duration(self) -> float:
        duration = self._duration_seconds
        self.reset_step()
        return duration

    def on_llm_start(self, serialized: dict[str, Any], prompts: list[str], **kwargs: Any) -> None:  # noqa: ARG002
        run_id = kwargs.get('run_id')
        if run_id is not None:
            self._starts[str(run_id)] = time.perf_counter()

    def on_llm_end(self, response: Any, **kwargs: Any) -> None:
        run_id = kwargs.get('run_id')
        if run_id is None:
            return
        start = self._starts.pop(str(run_id), None)
        if start is not None:
            self._duration_seconds += max(time.perf_counter() - start, 0.0)

        # Extract token usage from LLMResult and accumulate into shared stats
        try:
            usage_dict: dict[str, int] | None = None
            llm_output = getattr(response, 'llm_output', None) or {}

            # Path 1: OpenAI — llm_output['token_usage']
            raw = llm_output.get('token_usage') or llm_output.get('usage')
            if raw and isinstance(raw, dict):
                usage_dict = _normalize_token_usage(raw)

            # Path 2: newer LangChain — generations[*][*].message.usage_metadata
            if usage_dict is None or usage_dict.get('total_tokens', 0) == 0:
                for gen_list in getattr(response, 'generations', []):
                    for gen in gen_list:
                        meta = getattr(getattr(gen, 'message', None), 'usage_metadata', None)
                        if meta:
                            usage_dict = _normalize_token_usage(meta)
                            break
                    if usage_dict and usage_dict.get('total_tokens', 0) > 0:
                        break

            if usage_dict and usage_dict.get('total_tokens', 0) > 0:
                accumulate_llm_duration_stats(
                    duration_seconds=0.0,  # duration already tracked via perf_counter
                    usage_details=usage_dict,
                )
        except Exception:
            pass  # Never break the callback chain

    def on_llm_error(self, error: BaseException, **kwargs: Any) -> None:  # noqa: ARG002
        run_id = kwargs.get('run_id')
        if run_id is not None:
            self._starts.pop(str(run_id), None)


# ---------------------------------------------------------------------------
# Token usage extraction from AgentExecutor results
# ---------------------------------------------------------------------------

def extract_token_usage_from_result(
    result: dict[str, Any],
    messages: list[Any],
) -> dict[str, int]:
    """Fallback: extract token usage from AgentExecutor intermediate_steps.

    Scans ``AgentAction.message_log`` AIMessages for ``usage_metadata`` or
    ``response_metadata`` and aggregates across all LLM calls in this step.
    """
    zero = {'prompt_tokens': 0, 'completion_tokens': 0, 'total_tokens': 0}
    aggregated = dict(zero)

    def _msg_usage(msg: Any) -> dict[str, int] | None:
        if not isinstance(msg, AIMessage):
            return None
        # usage_metadata (most reliable, LangChain >=0.2)
        meta = getattr(msg, 'usage_metadata', None)
        if meta:
            u = _normalize_token_usage(meta)
            if u['total_tokens'] > 0:
                return u
        # response_metadata fallback
        resp_meta = getattr(msg, 'response_metadata', None)
        if isinstance(resp_meta, dict):
            for key in ('token_usage', 'usage', 'usage_metadata'):
                raw = resp_meta.get(key)
                if raw and isinstance(raw, dict):
                    u = _normalize_token_usage(raw)
                    if u['total_tokens'] > 0:
                        return u
        return None

    try:
        # Scan intermediate_steps (AgentAction.message_log)
        for step_tuple in result.get('intermediate_steps', []):
            if not isinstance(step_tuple, (list, tuple)) or len(step_tuple) < 1:
                continue
            msg_log = getattr(step_tuple[0], 'message_log', None) or []
            for msg in msg_log:
                usage = _msg_usage(msg)
                if usage:
                    aggregated['prompt_tokens'] += usage['prompt_tokens']
                    aggregated['completion_tokens'] += usage['completion_tokens']
                    aggregated['total_tokens'] += usage['total_tokens']
        if aggregated['total_tokens'] > 0:
            return aggregated

        # Fallback: scan result/passed messages
        for msg in reversed(messages or result.get('messages', [])):
            usage = _msg_usage(msg)
            if usage:
                return usage
    except Exception:
        pass
    return zero


# ---------------------------------------------------------------------------
# Time breakdown computation
# ---------------------------------------------------------------------------

def _safe_ratio(numerator: float, denominator: float) -> float:
    """Compute safe ratio with zero guard."""
    if denominator <= 0:
        return 0.0
    return round(max(numerator / denominator, 0.0), 4)


def _round_s(value: float) -> float:
    """Round seconds to 2 decimal places for readability."""
    return round(value, 2)


def build_time_breakdown(
    *,
    e2e_duration_seconds: float,
    llm_duration_seconds: float,
    message_prep_seconds: float,
    screenshot_seconds: float,
    tool_execution_seconds: float,
) -> dict[str, Any]:
    """Build normalized time breakdown for one step."""
    e2e = max(float(e2e_duration_seconds), 0.0)
    llm = max(float(llm_duration_seconds), 0.0)
    message_prep = max(float(message_prep_seconds), 0.0)
    screenshot = max(float(screenshot_seconds), 0.0)
    tool_total = max(float(tool_execution_seconds), 0.0)

    system_total = max(e2e - llm, 0.0)
    message_effective = min(message_prep, system_total)
    after_message = max(system_total - message_effective, 0.0)
    screenshot_effective = min(screenshot, after_message)
    after_screenshot = max(after_message - screenshot_effective, 0.0)
    tool_effective = min(tool_total, after_screenshot)
    orchestration_overhead = max(after_screenshot - tool_effective, 0.0)

    return {
        'e2e_duration_seconds': _round_s(e2e),
        'llm_duration_seconds': _round_s(llm),
        'system_total_seconds': _round_s(system_total),
        'system_breakdown': {
            'message_prep_seconds': _round_s(message_effective),
            'screenshot_seconds': _round_s(screenshot_effective),
            'tool_execution_seconds': _round_s(tool_effective),
            'orchestration_overhead_seconds': _round_s(orchestration_overhead),
        },
        'ratio': {
            'llm_ratio': _safe_ratio(llm, e2e),
            'system_ratio': _safe_ratio(system_total, e2e),
            'message_prep_ratio': _safe_ratio(message_effective, e2e),
            'screenshot_ratio': _safe_ratio(screenshot_effective, e2e),
            'tool_execution_ratio': _safe_ratio(tool_effective, e2e),
            'orchestration_overhead_ratio': _safe_ratio(orchestration_overhead, e2e),
        },
    }


# ---------------------------------------------------------------------------
# LangChain usage extraction
# ---------------------------------------------------------------------------

def _extract_langchain_usage(response: Any) -> tuple[dict[str, int], dict[str, Any]]:
    """Extract token usage from LangChain AIMessage-compatible responses."""
    usage_source = getattr(response, 'usage_metadata', None)

    if usage_source is None:
        response_metadata = getattr(response, 'response_metadata', None)
        if isinstance(response_metadata, dict):
            usage_source = (
                response_metadata.get('token_usage')
                or response_metadata.get('usage')
                or response_metadata.get('usage_metadata')
            )

    return extract_usage_details(usage_source)


# ---------------------------------------------------------------------------
# Instrumented async invocation
# ---------------------------------------------------------------------------

async def instrumented_ainvoke(
    runnable: Any,
    invoke_input: Any,
    *,
    model_name: str,
    capture_metrics: bool = False,
) -> Any:
    """Invoke a Runnable and optionally capture timing/usage metrics."""
    original_ainvoke = getattr(runnable, 'ainvoke', None)
    if not callable(original_ainvoke):
        raise AttributeError(f'{type(runnable).__name__} does not support ainvoke')

    start_ts = time.perf_counter()
    response = await original_ainvoke(invoke_input)
    if capture_metrics:
        usage_details, usage_raw = _extract_langchain_usage(response)
        duration_ms = int((time.perf_counter() - start_ts) * 1000)
        invoke_metrics = {
            'model': model_name,
            'duration_ms': duration_ms,
            'duration_seconds': duration_ms / 1000.0,
            'token_usage': usage_details,
            'usage_raw': usage_raw,
        }
        return response, invoke_metrics
    return response

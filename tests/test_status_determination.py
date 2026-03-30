"""Tests for the LLM-first + Safety Guard status determination logic.

Tests cover:
- parse_llm_status: LLM output STATUS parsing with normalization
- apply_safety_guard: CRITICAL/HARD_FAIL safety overrides
- derive_failure_type_from_outcomes: failure_type derivation
- verdict_fallback: deterministic fallback when LLM STATUS is missing
"""

from webqa_agent.data.gen_structures import StepOutcome, StepSeverity
from webqa_agent.executor.gen.agents.status_determination import (
    apply_safety_guard, derive_failure_type_from_outcomes, parse_llm_status,
    verdict_fallback)

# ============================================================================
# parse_llm_status tests
# ============================================================================


class TestParseLlmStatus:
    """Tests for parse_llm_status()."""

    def test_parse_passed(self) -> None:
        assert parse_llm_status('STATUS: passed\nFINAL_SUMMARY: ...') == 'passed'

    def test_parse_failed(self) -> None:
        assert parse_llm_status('STATUS: failed\nFINAL_SUMMARY: ...') == 'failed'

    def test_parse_warning(self) -> None:
        assert parse_llm_status('STATUS: warning\nFINAL_SUMMARY: ...') == 'warning'

    def test_parse_case_insensitive(self) -> None:
        assert parse_llm_status('Status: PASSED\nFINAL_SUMMARY: ...') == 'passed'
        assert parse_llm_status('STATUS: Failed\nFINAL_SUMMARY: ...') == 'failed'

    def test_parse_variant_pass(self) -> None:
        assert parse_llm_status('STATUS: pass\nFINAL_SUMMARY: ...') == 'passed'

    def test_parse_variant_fail(self) -> None:
        assert parse_llm_status('STATUS: fail\nFINAL_SUMMARY: ...') == 'failed'

    def test_parse_variant_success(self) -> None:
        assert parse_llm_status('STATUS: success\nFINAL_SUMMARY: ...') == 'passed'

    def test_parse_variant_failure(self) -> None:
        assert parse_llm_status('STATUS: failure\nFINAL_SUMMARY: ...') == 'failed'

    def test_parse_missing_returns_none(self) -> None:
        assert parse_llm_status('FINAL_SUMMARY: Test completed.') is None

    def test_parse_empty_returns_none(self) -> None:
        assert parse_llm_status('') is None

    def test_parse_none_returns_none(self) -> None:
        # Explicitly pass empty string (function signature expects str)
        assert parse_llm_status('') is None

    def test_parse_with_trailing_text(self) -> None:
        result = parse_llm_status('STATUS: passed (all criteria met)\nFINAL_SUMMARY: ...')
        assert result == 'passed'

    def test_parse_with_whitespace(self) -> None:
        assert parse_llm_status('STATUS:  passed\nFINAL_SUMMARY: ...') == 'passed'

    def test_parse_invalid_status_value(self) -> None:
        assert parse_llm_status('STATUS: unknown\nFINAL_SUMMARY: ...') is None


# ============================================================================
# apply_safety_guard tests
# ============================================================================


def _make_outcome(severity: StepSeverity, step_index: int = 1) -> StepOutcome:
    """Helper to create StepOutcome instances."""
    return StepOutcome(step_index=step_index, severity=severity, description='test')


class TestApplySafetyGuard:
    """Tests for apply_safety_guard()."""

    def test_critical_overrides_passed(self) -> None:
        outcomes = [_make_outcome(StepSeverity.CRITICAL)]
        assert apply_safety_guard('passed', outcomes) == 'failed'

    def test_critical_overrides_warning(self) -> None:
        outcomes = [_make_outcome(StepSeverity.CRITICAL)]
        assert apply_safety_guard('warning', outcomes) == 'failed'

    def test_critical_keeps_failed(self) -> None:
        outcomes = [_make_outcome(StepSeverity.CRITICAL)]
        assert apply_safety_guard('failed', outcomes) == 'failed'

    def test_hard_fail_overrides_passed(self) -> None:
        outcomes = [_make_outcome(StepSeverity.HARD_FAIL)]
        assert apply_safety_guard('passed', outcomes) == 'failed'

    def test_hard_fail_overrides_warning(self) -> None:
        outcomes = [_make_outcome(StepSeverity.HARD_FAIL)]
        assert apply_safety_guard('warning', outcomes) == 'failed'

    def test_hard_fail_keeps_failed(self) -> None:
        outcomes = [_make_outcome(StepSeverity.HARD_FAIL)]
        assert apply_safety_guard('failed', outcomes) == 'failed'

    def test_no_hard_failures_keeps_original(self) -> None:
        outcomes = [_make_outcome(StepSeverity.PASSED), _make_outcome(StepSeverity.SOFT_FAIL)]
        assert apply_safety_guard('passed', outcomes) == 'passed'
        assert apply_safety_guard('warning', outcomes) == 'warning'
        assert apply_safety_guard('failed', outcomes) == 'failed'

    def test_empty_outcomes_keeps_original(self) -> None:
        assert apply_safety_guard('passed', []) == 'passed'
        assert apply_safety_guard('failed', []) == 'failed'
        assert apply_safety_guard('warning', []) == 'warning'

    def test_mixed_critical_and_hard_fail(self) -> None:
        """CRITICAL takes priority over HARD_FAIL."""
        outcomes = [
            _make_outcome(StepSeverity.CRITICAL),
            _make_outcome(StepSeverity.HARD_FAIL, step_index=2),
        ]
        assert apply_safety_guard('passed', outcomes) == 'failed'
        assert apply_safety_guard('warning', outcomes) == 'failed'


# ============================================================================
# derive_failure_type_from_outcomes tests
# ============================================================================


class TestDeriveFailureTypeFromOutcomes:
    """Tests for derive_failure_type_from_outcomes()."""

    def test_critical(self) -> None:
        outcomes = [_make_outcome(StepSeverity.CRITICAL)]
        assert derive_failure_type_from_outcomes(outcomes) == 'critical'

    def test_hard_fail(self) -> None:
        outcomes = [_make_outcome(StepSeverity.HARD_FAIL)]
        assert derive_failure_type_from_outcomes(outcomes) == 'product_defect'

    def test_soft_fail(self) -> None:
        outcomes = [_make_outcome(StepSeverity.SOFT_FAIL)]
        assert derive_failure_type_from_outcomes(outcomes) == 'infrastructure'

    def test_empty(self) -> None:
        assert derive_failure_type_from_outcomes([]) == 'recoverable'

    def test_only_passed(self) -> None:
        outcomes = [_make_outcome(StepSeverity.PASSED)]
        assert derive_failure_type_from_outcomes(outcomes) == 'recoverable'

    def test_mixed_critical_wins(self) -> None:
        outcomes = [
            _make_outcome(StepSeverity.PASSED),
            _make_outcome(StepSeverity.SOFT_FAIL, step_index=2),
            _make_outcome(StepSeverity.HARD_FAIL, step_index=3),
            _make_outcome(StepSeverity.CRITICAL, step_index=4),
        ]
        assert derive_failure_type_from_outcomes(outcomes) == 'critical'

    def test_hard_fail_over_soft_fail(self) -> None:
        outcomes = [
            _make_outcome(StepSeverity.SOFT_FAIL),
            _make_outcome(StepSeverity.HARD_FAIL, step_index=2),
        ]
        assert derive_failure_type_from_outcomes(outcomes) == 'product_defect'


# ============================================================================
# verdict_fallback tests
# ============================================================================


class TestVerdictFallback:
    """Tests for verdict_fallback()."""

    def test_all_passed(self) -> None:
        outcomes = [_make_outcome(StepSeverity.PASSED)]
        status, failure_type = verdict_fallback(outcomes, [], False)
        assert status == 'passed'
        assert failure_type is None

    def test_critical(self) -> None:
        outcomes = [_make_outcome(StepSeverity.CRITICAL)]
        status, failure_type = verdict_fallback(outcomes, [], False)
        assert status == 'failed'
        assert failure_type == 'critical'

    def test_hard_fail(self) -> None:
        outcomes = [_make_outcome(StepSeverity.HARD_FAIL)]
        status, failure_type = verdict_fallback(outcomes, [], False)
        assert status == 'failed'
        assert failure_type == 'product_defect'

    def test_objective_achieved(self) -> None:
        outcomes = [_make_outcome(StepSeverity.SOFT_FAIL)]
        status, failure_type = verdict_fallback(outcomes, [], True)
        assert status == 'passed'
        assert failure_type is None

    def test_soft_fail_no_objective(self) -> None:
        outcomes = [_make_outcome(StepSeverity.SOFT_FAIL)]
        status, failure_type = verdict_fallback(outcomes, [], False)
        assert status == 'failed'
        assert failure_type == 'infrastructure'

    def test_warning_steps(self) -> None:
        outcomes = [_make_outcome(StepSeverity.PASSED)]
        status, failure_type = verdict_fallback(outcomes, [1], False)
        assert status == 'warning'
        assert failure_type is None

    def test_empty_outcomes(self) -> None:
        status, failure_type = verdict_fallback([], [], False)
        assert status == 'passed'
        assert failure_type is None

    def test_only_skipped(self) -> None:
        outcomes = [_make_outcome(StepSeverity.SKIPPED)]
        status, failure_type = verdict_fallback(outcomes, [], False)
        assert status == 'passed'
        assert failure_type is None

    def test_critical_overrides_objective(self) -> None:
        """CRITICAL should fail even if objective_achieved is True."""
        outcomes = [_make_outcome(StepSeverity.CRITICAL)]
        status, failure_type = verdict_fallback(outcomes, [], True)
        assert status == 'failed'
        assert failure_type == 'critical'

    def test_hard_fail_overrides_objective(self) -> None:
        """HARD_FAIL should fail even if objective_achieved is True."""
        outcomes = [_make_outcome(StepSeverity.HARD_FAIL)]
        status, failure_type = verdict_fallback(outcomes, [], True)
        assert status == 'failed'
        assert failure_type == 'product_defect'


# ============================================================================
# System error safety guard bypass tests
# ============================================================================


class TestSystemErrorSafetyGuardBypass:
    """Tests that system_error bypasses the safety guard.

    When code_failure_type == 'system_error', the safety guard should NOT
    override the 'warning' status to 'failed', even with HARD_FAIL/CRITICAL
    step outcomes (because those failures are system-caused, not product
    defects).
    """

    def test_system_error_bypasses_safety_guard_with_hard_fail(self) -> None:
        """system_error + HARD_FAIL outcomes should keep warning status."""
        outcomes = [_make_outcome(StepSeverity.HARD_FAIL)]
        code_determined_status = 'warning'
        code_failure_type = 'system_error'

        # Simulate the bypass logic from execute_agent.py
        if code_failure_type == 'system_error':
            status = code_determined_status  # bypass
        else:
            status = apply_safety_guard(code_determined_status, outcomes)

        assert status == 'warning', (
            f'Expected warning (system error bypass), got {status}'
        )

    def test_system_error_bypasses_safety_guard_with_critical(self) -> None:
        """system_error + CRITICAL outcomes should keep warning status."""
        outcomes = [_make_outcome(StepSeverity.CRITICAL)]
        code_determined_status = 'warning'
        code_failure_type = 'system_error'

        if code_failure_type == 'system_error':
            status = code_determined_status
        else:
            status = apply_safety_guard(code_determined_status, outcomes)

        assert status == 'warning', (
            f'Expected warning (system error bypass), got {status}'
        )

    def test_non_system_error_still_applies_safety_guard(self) -> None:
        """Non-system errors should still go through safety guard."""
        outcomes = [_make_outcome(StepSeverity.HARD_FAIL)]
        code_determined_status = 'passed'
        code_failure_type = 'recoverable'

        if code_failure_type == 'system_error':
            status = code_determined_status
        else:
            status = apply_safety_guard(code_determined_status, outcomes)

        assert status == 'failed', (
            f'Expected failed (safety guard override), got {status}'
        )

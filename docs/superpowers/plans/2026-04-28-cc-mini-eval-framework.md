# webqa-cc-mini Eval Framework Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a local-first automated evaluation framework for `webqa-cc-mini` that tests harness changes (prompts, tools, engine, skills) against deterministic benchmarks, collects structured traces, and supports CI regression gating — without modifying production runner code.

**Architecture:** Four-layer design: `EvalCase (YAML) → EvalRunner (pytest) → Scorer (validators) → Report (JSON + HTML)`. Cases are YAML files loaded via pytest `conftest.py` parametrization. The runner calls `run_cc_mini()` with `on_event` for trace capture. Scorers are composable validator classes. Reports are JSON summaries + optional HTML diffs against baselines. No external SaaS dependency.

**Tech Stack:** Python 3.11+, pytest (native integration), pydantic 2.9 (schemas), pyyaml (case loading), stdlib `http.server` (fixtures), existing cc-mini engine mock patterns.

______________________________________________________________________

## Context

The `webqa-cc-mini` harness wraps the cc-mini engine for browser-based web testing. As prompts, tools, skills, and engine logic evolve, there is no automated way to know whether a change improves or degrades agent behavior. This framework provides that signal through deterministic local benchmarks, structured trace collection, multi-dimensional scoring, and baseline comparison.

Key design decisions (informed by external research):

- **Zero modification to `runner.py`**: Use existing `on_event`, `extra_tools`, and `pre_engine_hook` extension points
- **pytest native integration**: Not a custom CLI — cases run via `pytest -m eval`
- **Mock LLM layer for framework tests**: Tier 1 uses pre-recorded event sequences, no real LLM calls
- **pass@k scoring**: Multiple trials per case, statistical aggregation
- **Inspect AI / BrowserGym patterns**: Dataset → Task → Scorer separation; `validate()` for state checks

## File Structure

```
evals/
├── __init__.py                          # Package marker
├── conftest.py                          # pytest fixtures: fixture server, case loading, worker_id pool
├── models/
│   ├── __init__.py
│   ├── case.py                          # EvalCase pydantic model (YAML schema)
│   ├── trace.py                         # TraceEvent, TraceRecord pydantic models
│   ├── result.py                        # EvalCaseResult, SuiteResult pydantic models
│   └── baseline.py                      # BaselineEntry, BaselineDiff models + comparison logic
├── runner.py                            # EvalCaseRunner: calls run_cc_mini, collects traces, runs scorers
├── scorers/
│   ├── __init__.py                      # re-exports all scorers
│   ├── base.py                          # Scorer ABC + ScorerResult dataclass
│   ├── status.py                        # FinalStatusScorer (oracle vs agent-reported)
│   ├── text.py                          # TextContainsScorer, RegexMatchScorer
│   ├── budget.py                        # StepBudgetScorer, TokenBudgetScorer
│   └── trace.py                         # TracePatternScorer (tool sequence checks)
├── report.py                            # JSON summary writer + HTML diff report generator
├── fixtures/                            # Static HTML pages for deterministic browser tests
│   ├── hello.html                       # Minimal page: H1 heading, paragraph
│   ├── form_required.html               # Form with required fields, validation
│   ├── search_filter.html               # Searchable/filterable list
│   └── nav_links.html                   # Multi-page navigation (relative links)
├── cases/
│   ├── smoke.yaml                       # Smoke suite: 5-8 quick deterministic cases
│   └── full.yaml                        # Full suite: 20+ cases across capability categories
└── baselines/
    └── smoke.baseline.json              # Pinned baseline for smoke suite
```

Existing files referenced (read-only, not modified):

- `webqa-cc-mini/runner.py` — `run_cc_mini()`, `RunResult`, `Step`, `ToolCall`, `EventCallback`
- `webqa-cc-mini/core/outcome_status.py` — `extract_final_outcome()`, `derive_status()`
- `webqa-cc-mini/core/tool.py` — `Tool` ABC, `ToolResult`
- `webqa-cc-mini/core/engine.py` — `Engine`, event tuple types
- `webqa-cc-mini/features/report.py` — `render_html_report()` (reuse for per-case reports)
- `tests/test_cc_mini_report.py` — existing mock patterns (`_RunResult`, `_Step`)
- `cc-mini/tests/test_engine.py` — `_make_text_response()`, `_make_tool_then_text_response()` mock helpers

______________________________________________________________________

## Task 1: Eval Data Models (case, trace, result)

**Files:**

- Create: `evals/__init__.py`

- Create: `evals/models/__init__.py`

- Create: `evals/models/case.py`

- Create: `evals/models/trace.py`

- Create: `evals/models/result.py`

- Create: `tests/evals/__init__.py`

- Create: `tests/evals/test_models.py`

- [ ] **Step 1: Write failing tests for EvalCase model**

```python
# tests/evals/test_models.py
"""Tests for eval data models."""
from __future__ import annotations

import pytest
import yaml

from evals.models.case import EvalCase, Limits


class TestEvalCase:
    def test_minimal_case_from_dict(self):
        raw = {
            "id": "hello_h1",
            "suite": "smoke",
            "url": "http://localhost:{port}/hello.html",
            "task": "Find the H1 heading and report its text",
            "validators": [{"type": "final_status", "expected": "passed"}],
        }
        case = EvalCase.model_validate(raw)
        assert case.id == "hello_h1"
        assert case.suite == "smoke"
        assert case.limits.max_iterations == 20  # default

    def test_case_with_limits(self):
        raw = {
            "id": "form_fill",
            "suite": "smoke",
            "url": "http://localhost:{port}/form_required.html",
            "task": "Fill and submit the form",
            "limits": {"max_iterations": 10, "max_tokens": 50000},
            "validators": [{"type": "final_status", "expected": "passed"}],
            "tags": ["form", "validation"],
        }
        case = EvalCase.model_validate(raw)
        assert case.limits.max_iterations == 10
        assert case.limits.max_tokens == 50000
        assert "form" in case.tags

    def test_case_requires_id(self):
        with pytest.raises(Exception):
            EvalCase.model_validate({"suite": "smoke", "url": "x", "task": "y", "validators": []})

    def test_url_trailing_slash_stripped(self):
        case = EvalCase.model_validate({
            "id": "t", "suite": "smoke",
            "url": "http://localhost:8080/",
            "task": "t", "validators": [],
        })
        assert case.url == "http://localhost:8080"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/evals/test_models.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'evals'`

- [ ] **Step 3: Implement EvalCase model**

```python
# evals/__init__.py
"""webqa-cc-mini evaluation framework."""

# evals/models/__init__.py
"""Eval data models."""
from .case import EvalCase, Limits
from .trace import TraceEvent, TraceRecord
from .result import EvalCaseResult, ValidatorVerdict

# evals/models/case.py
"""YAML eval case schema."""
from __future__ import annotations

from pydantic import BaseModel, field_validator
from typing_extensions import Self


class Limits(BaseModel):
    max_iterations: int = 20
    max_time_seconds: float | None = None
    max_tokens: int | None = None
    max_tool_errors: int | None = None


class ValidatorSpec(BaseModel):
    type: str
    expected: str | None = None
    pattern: str | None = None
    contains: str | None = None
    max_value: int | None = None


class EvalCase(BaseModel):
    id: str
    suite: str
    url: str
    task: str
    validators: list[ValidatorSpec] = []
    limits: Limits = Limits()
    tags: list[str] = []
    trials: int = 3

    @field_validator("url", mode="before")
    @classmethod
    def strip_trailing_slash(cls, v: str) -> str:
        return v.rstrip("/")
```

- [ ] **Step 4: Write failing tests for TraceEvent and TraceRecord**

```python
# Append to tests/evals/test_models.py
import json
import time
from evals.models.trace import TraceEvent, TraceRecord


class TestTraceEvent:
    def test_from_engine_text_event(self):
        evt = TraceEvent.from_engine_event(("text", "hello world"))
        assert evt.kind == "text"
        assert evt.data == {"chunk": "hello world"}

    def test_from_engine_tool_call_event(self):
        evt = TraceEvent.from_engine_event(
            ("tool_call", "mcp__browser__click", {"selector": "#btn"}, "clicking")
        )
        assert evt.kind == "tool_call"
        assert evt.data["tool"] == "mcp__browser__click"

    def test_from_engine_usage_event(self):
        class _Usage:
            input_tokens = 100
            output_tokens = 50
        evt = TraceEvent.from_engine_event(("usage", _Usage()))
        assert evt.kind == "usage"
        assert evt.data["input_tokens"] == 100

    def test_jsonl_round_trip(self):
        evt = TraceEvent(kind="text", data={"chunk": "hi"}, timestamp=1234567890.0)
        line = evt.model_dump_json()
        restored = TraceEvent.model_validate_json(line)
        assert restored.kind == evt.kind
        assert restored.timestamp == evt.timestamp


class TestTraceRecord:
    def test_append_and_load(self, tmp_path):
        path = tmp_path / "trace.jsonl"
        record = TraceRecord(case_id="test_1", trial=0)
        record.append(TraceEvent(kind="text", data={"chunk": "hi"}))
        record.append(TraceEvent(kind="usage", data={"input_tokens": 10, "output_tokens": 5}))
        record.save(path)

        loaded = TraceRecord.load(path)
        assert loaded.case_id == "test_1"
        assert len(loaded.events) == 2
```

- [ ] **Step 5: Implement TraceEvent and TraceRecord**

```python
# evals/models/trace.py
"""Structured trace capture from engine events."""
from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field


class TraceEvent(BaseModel):
    kind: str
    data: dict[str, Any] = {}
    timestamp: float = Field(default_factory=time.time)

    @classmethod
    def from_engine_event(cls, evt: tuple) -> TraceEvent:
        kind = evt[0]
        if kind == "text":
            return cls(kind="text", data={"chunk": str(evt[1]) if len(evt) > 1 else ""})
        if kind == "tool_call":
            return cls(kind="tool_call", data={
                "tool": str(evt[1]) if len(evt) > 1 else "",
                "input": evt[2] if len(evt) > 2 else {},
                "activity": str(evt[3]) if len(evt) > 3 else "",
            })
        if kind == "tool_result":
            result = evt[3] if len(evt) > 3 else None
            return cls(kind="tool_result", data={
                "tool": str(evt[1]) if len(evt) > 1 else "",
                "content": str(getattr(result, "content", ""))[:500],
                "is_error": bool(getattr(result, "is_error", False)),
            })
        if kind == "usage":
            usage = evt[1] if len(evt) > 1 else None
            return cls(kind="usage", data={
                "input_tokens": int(getattr(usage, "input_tokens", 0) or 0),
                "output_tokens": int(getattr(usage, "output_tokens", 0) or 0),
            })
        if kind == "error":
            return cls(kind="error", data={"message": str(evt[1]) if len(evt) > 1 else ""})
        return cls(kind=kind, data={})


class TraceRecord(BaseModel):
    case_id: str
    trial: int = 0
    events: list[TraceEvent] = []

    def append(self, event: TraceEvent) -> None:
        self.events.append(event)

    def save(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w", encoding="utf-8") as f:
            f.write(self.model_dump_json() + "\n")

    @classmethod
    def load(cls, path: Path) -> TraceRecord:
        text = path.read_text(encoding="utf-8").strip()
        return cls.model_validate_json(text)
```

- [ ] **Step 6: Write failing tests for EvalCaseResult**

```python
# Append to tests/evals/test_models.py
from evals.models.result import EvalCaseResult, ValidatorVerdict


class TestEvalCaseResult:
    def test_is_pass_when_all_verdicts_pass(self):
        r = EvalCaseResult(
            case_id="t",
            trial=0,
            verdicts=[
                ValidatorVerdict(validator="final_status", passed=True),
                ValidatorVerdict(validator="text_contains", passed=True),
            ],
            steps=5,
            input_tokens=1000,
            output_tokens=500,
            aborted=False,
            agent_status="passed",
        )
        assert r.oracle_passed is True

    def test_is_fail_when_any_verdict_fails(self):
        r = EvalCaseResult(
            case_id="t",
            trial=0,
            verdicts=[
                ValidatorVerdict(validator="final_status", passed=True),
                ValidatorVerdict(validator="text_contains", passed=False, reason="missing text"),
            ],
            steps=5,
            input_tokens=1000,
            output_tokens=500,
            aborted=False,
            agent_status="passed",
        )
        assert r.oracle_passed is False

    def test_agreement_true_when_oracle_matches_agent(self):
        r = EvalCaseResult(
            case_id="t", trial=0,
            verdicts=[ValidatorVerdict(validator="s", passed=True)],
            steps=3, input_tokens=100, output_tokens=50,
            aborted=False, agent_status="passed",
        )
        assert r.agreement is True

    def test_agreement_false_on_overclaiming(self):
        r = EvalCaseResult(
            case_id="t", trial=0,
            verdicts=[ValidatorVerdict(validator="s", passed=False, reason="fail")],
            steps=3, input_tokens=100, output_tokens=50,
            aborted=False, agent_status="passed",
        )
        assert r.agreement is False
```

- [ ] **Step 7: Implement EvalCaseResult**

```python
# evals/models/result.py
"""Eval run result models."""
from __future__ import annotations

from pydantic import BaseModel, computed_field


class ValidatorVerdict(BaseModel):
    validator: str
    passed: bool
    reason: str | None = None


class EvalCaseResult(BaseModel):
    case_id: str
    trial: int
    verdicts: list[ValidatorVerdict]
    steps: int
    input_tokens: int
    output_tokens: int
    duration_seconds: float = 0.0
    aborted: bool
    agent_status: str
    trace_path: str | None = None

    @computed_field
    @property
    def oracle_passed(self) -> bool:
        return all(v.passed for v in self.verdicts)

    @computed_field
    @property
    def agreement(self) -> bool:
        oracle = self.oracle_passed
        agent = self.agent_status == "passed"
        return oracle == agent
```

- [ ] **Step 8: Run all model tests**

Run: `uv run pytest tests/evals/test_models.py -v`
Expected: all PASS

- [ ] **Step 9: Commit**

```bash
git add evals/ tests/evals/
git commit -m "feat(evals): add eval data models — EvalCase, TraceEvent, EvalCaseResult"
```

______________________________________________________________________

## Task 2: Scorer Framework (validators)

**Files:**

- Create: `evals/scorers/__init__.py`

- Create: `evals/scorers/base.py`

- Create: `evals/scorers/status.py`

- Create: `evals/scorers/text.py`

- Create: `evals/scorers/budget.py`

- Create: `evals/scorers/trace.py`

- Create: `tests/evals/test_scorers.py`

- [ ] **Step 1: Write failing tests for scorer base and FinalStatusScorer**

```python
# tests/evals/test_scorers.py
"""Tests for eval scorers."""
from __future__ import annotations

import sys
from dataclasses import dataclass, field
from pathlib import Path

import pytest

from evals.models.case import ValidatorSpec
from evals.models.trace import TraceEvent
from evals.scorers.base import build_scorer
from evals.scorers.status import FinalStatusScorer
from evals.scorers.text import TextContainsScorer, RegexMatchScorer
from evals.scorers.budget import StepBudgetScorer, TokenBudgetScorer
from evals.scorers.trace import TracePatternScorer


# Minimal RunResult stub matching webqa-cc-mini/runner.py shape
@dataclass
class _ToolCall:
    tool: str = "nav"
    input: dict = field(default_factory=dict)
    result: str = "ok"
    is_error: bool = False


@dataclass
class _Step:
    description: str = ""
    tool_calls: list[_ToolCall] = field(default_factory=list)
    screenshots: list = field(default_factory=list)

    @property
    def is_error(self) -> bool:
        return any(tc.is_error for tc in self.tool_calls)


@dataclass
class _RunResult:
    final_text: str = ""
    steps: list = field(default_factory=list)
    aborted: bool = False
    input_tokens: int = 0
    output_tokens: int = 0


class TestFinalStatusScorer:
    def test_passed_when_outcome_matches(self):
        result = _RunResult(
            final_text='<final_outcome>{"status":"passed","summary":"ok"}</final_outcome>'
        )
        scorer = FinalStatusScorer(expected="passed")
        verdict = scorer.score(result, [])
        assert verdict.passed is True

    def test_failed_when_outcome_mismatches(self):
        result = _RunResult(
            final_text='<final_outcome>{"status":"failed","summary":"err"}</final_outcome>'
        )
        scorer = FinalStatusScorer(expected="passed")
        verdict = scorer.score(result, [])
        assert verdict.passed is False
        assert "failed" in (verdict.reason or "")

    def test_failed_when_aborted(self):
        result = _RunResult(aborted=True)
        scorer = FinalStatusScorer(expected="passed")
        verdict = scorer.score(result, [])
        assert verdict.passed is False

    def test_failed_when_no_outcome_tag(self):
        result = _RunResult(final_text="just some text without outcome")
        scorer = FinalStatusScorer(expected="passed")
        verdict = scorer.score(result, [])
        assert verdict.passed is False
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/evals/test_scorers.py::TestFinalStatusScorer -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'evals.scorers'`

- [ ] **Step 3: Implement Scorer base and FinalStatusScorer**

```python
# evals/scorers/base.py
"""Scorer base class and factory."""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from evals.models.case import ValidatorSpec
from evals.models.result import ValidatorVerdict
from evals.models.trace import TraceEvent


class Scorer(ABC):
    @abstractmethod
    def score(self, run_result: Any, trace_events: list[TraceEvent]) -> ValidatorVerdict: ...


def build_scorer(spec: ValidatorSpec) -> Scorer:
    from evals.scorers.status import FinalStatusScorer
    from evals.scorers.text import TextContainsScorer, RegexMatchScorer
    from evals.scorers.budget import StepBudgetScorer, TokenBudgetScorer
    from evals.scorers.trace import TracePatternScorer

    _REGISTRY: dict[str, type] = {
        "final_status": FinalStatusScorer,
        "text_contains": TextContainsScorer,
        "regex_match": RegexMatchScorer,
        "step_budget": StepBudgetScorer,
        "token_budget": TokenBudgetScorer,
        "trace_pattern": TracePatternScorer,
    }
    cls = _REGISTRY.get(spec.type)
    if cls is None:
        raise ValueError(f"Unknown scorer type: {spec.type!r}")
    return cls.from_spec(spec)


# evals/scorers/__init__.py
"""Eval scorers."""
from .base import Scorer, build_scorer
from .status import FinalStatusScorer
from .text import TextContainsScorer, RegexMatchScorer
from .budget import StepBudgetScorer, TokenBudgetScorer
from .trace import TracePatternScorer
```

```python
# evals/scorers/status.py
"""Final outcome status scorer."""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

from evals.models.case import ValidatorSpec
from evals.models.result import ValidatorVerdict
from evals.models.trace import TraceEvent
from evals.scorers.base import Scorer

_CC_MINI_ROOT = Path(__file__).resolve().parent.parent.parent / "webqa-cc-mini"
if str(_CC_MINI_ROOT) not in sys.path:
    sys.path.insert(0, str(_CC_MINI_ROOT))

from core.outcome_status import derive_status, extract_final_outcome


class FinalStatusScorer(Scorer):
    def __init__(self, expected: str) -> None:
        self.expected = expected

    @classmethod
    def from_spec(cls, spec: ValidatorSpec) -> FinalStatusScorer:
        return cls(expected=spec.expected or "passed")

    def score(self, run_result: Any, trace_events: list[TraceEvent]) -> ValidatorVerdict:
        if run_result.aborted:
            return ValidatorVerdict(
                validator="final_status", passed=False, reason="run was aborted"
            )
        outcome = extract_final_outcome(run_result.final_text or "")
        failed_count = sum(1 for s in (run_result.steps or []) if getattr(s, "is_error", False))
        status, source = derive_status(
            aborted=run_result.aborted, failed_count=failed_count, outcome=outcome,
        )
        passed = status == self.expected
        reason = None if passed else f"expected {self.expected!r}, got {status!r} (source: {source})"
        return ValidatorVerdict(validator="final_status", passed=passed, reason=reason)
```

- [ ] **Step 4: Write tests and implement TextContainsScorer, RegexMatchScorer**

```python
# Append to tests/evals/test_scorers.py
class TestTextContainsScorer:
    def test_passes_when_text_present(self):
        result = _RunResult(final_text="The heading says Hello World")
        scorer = TextContainsScorer(contains="Hello World")
        assert scorer.score(result, []).passed is True

    def test_fails_when_text_absent(self):
        result = _RunResult(final_text="Nothing here")
        scorer = TextContainsScorer(contains="Hello World")
        v = scorer.score(result, [])
        assert v.passed is False

    def test_case_insensitive(self):
        result = _RunResult(final_text="hello world")
        scorer = TextContainsScorer(contains="Hello World")
        assert scorer.score(result, []).passed is True


class TestRegexMatchScorer:
    def test_matches_pattern(self):
        result = _RunResult(final_text="Found 42 items on the page")
        scorer = RegexMatchScorer(pattern=r"\d+ items")
        assert scorer.score(result, []).passed is True

    def test_no_match(self):
        result = _RunResult(final_text="No numeric info")
        scorer = RegexMatchScorer(pattern=r"\d+ items")
        assert scorer.score(result, []).passed is False
```

```python
# evals/scorers/text.py
"""Text content scorers."""
from __future__ import annotations

import re
from typing import Any

from evals.models.case import ValidatorSpec
from evals.models.result import ValidatorVerdict
from evals.models.trace import TraceEvent
from evals.scorers.base import Scorer


class TextContainsScorer(Scorer):
    def __init__(self, contains: str) -> None:
        self.contains = contains

    @classmethod
    def from_spec(cls, spec: ValidatorSpec) -> TextContainsScorer:
        return cls(contains=spec.contains or "")

    def score(self, run_result: Any, trace_events: list[TraceEvent]) -> ValidatorVerdict:
        text = (run_result.final_text or "").lower()
        found = self.contains.lower() in text
        return ValidatorVerdict(
            validator="text_contains",
            passed=found,
            reason=None if found else f"{self.contains!r} not found in final_text",
        )


class RegexMatchScorer(Scorer):
    def __init__(self, pattern: str) -> None:
        self.pattern = pattern

    @classmethod
    def from_spec(cls, spec: ValidatorSpec) -> RegexMatchScorer:
        return cls(pattern=spec.pattern or "")

    def score(self, run_result: Any, trace_events: list[TraceEvent]) -> ValidatorVerdict:
        text = run_result.final_text or ""
        found = bool(re.search(self.pattern, text))
        return ValidatorVerdict(
            validator="regex_match",
            passed=found,
            reason=None if found else f"pattern {self.pattern!r} not matched",
        )
```

- [ ] **Step 5: Write tests and implement StepBudgetScorer, TokenBudgetScorer**

```python
# Append to tests/evals/test_scorers.py
class TestStepBudgetScorer:
    def test_within_budget(self):
        result = _RunResult(steps=[_Step() for _ in range(5)])
        scorer = StepBudgetScorer(max_steps=10)
        assert scorer.score(result, []).passed is True

    def test_over_budget(self):
        result = _RunResult(steps=[_Step() for _ in range(15)])
        scorer = StepBudgetScorer(max_steps=10)
        v = scorer.score(result, [])
        assert v.passed is False
        assert "15" in (v.reason or "")


class TestTokenBudgetScorer:
    def test_within_budget(self):
        result = _RunResult(input_tokens=5000, output_tokens=2000)
        scorer = TokenBudgetScorer(max_tokens=10000)
        assert scorer.score(result, []).passed is True

    def test_over_budget(self):
        result = _RunResult(input_tokens=8000, output_tokens=5000)
        scorer = TokenBudgetScorer(max_tokens=10000)
        v = scorer.score(result, [])
        assert v.passed is False
```

```python
# evals/scorers/budget.py
"""Resource budget scorers."""
from __future__ import annotations

from typing import Any

from evals.models.case import ValidatorSpec
from evals.models.result import ValidatorVerdict
from evals.models.trace import TraceEvent
from evals.scorers.base import Scorer


class StepBudgetScorer(Scorer):
    def __init__(self, max_steps: int) -> None:
        self.max_steps = max_steps

    @classmethod
    def from_spec(cls, spec: ValidatorSpec) -> StepBudgetScorer:
        return cls(max_steps=spec.max_value or 20)

    def score(self, run_result: Any, trace_events: list[TraceEvent]) -> ValidatorVerdict:
        n = len(run_result.steps or [])
        passed = n <= self.max_steps
        return ValidatorVerdict(
            validator="step_budget",
            passed=passed,
            reason=None if passed else f"{n} steps exceeds budget of {self.max_steps}",
        )


class TokenBudgetScorer(Scorer):
    def __init__(self, max_tokens: int) -> None:
        self.max_tokens = max_tokens

    @classmethod
    def from_spec(cls, spec: ValidatorSpec) -> TokenBudgetScorer:
        return cls(max_tokens=spec.max_value or 100000)

    def score(self, run_result: Any, trace_events: list[TraceEvent]) -> ValidatorVerdict:
        total = (run_result.input_tokens or 0) + (run_result.output_tokens or 0)
        passed = total <= self.max_tokens
        return ValidatorVerdict(
            validator="token_budget",
            passed=passed,
            reason=None if passed else f"{total} tokens exceeds budget of {self.max_tokens}",
        )
```

- [ ] **Step 6: Write tests and implement TracePatternScorer**

```python
# Append to tests/evals/test_scorers.py
class TestTracePatternScorer:
    def test_required_tool_present(self):
        events = [
            TraceEvent(kind="tool_call", data={"tool": "mcp__browser__navigate_page"}),
            TraceEvent(kind="tool_call", data={"tool": "verify"}),
        ]
        scorer = TracePatternScorer(required_tools=["verify"])
        result = _RunResult()
        assert scorer.score(result, events).passed is True

    def test_required_tool_missing(self):
        events = [
            TraceEvent(kind="tool_call", data={"tool": "mcp__browser__navigate_page"}),
        ]
        scorer = TracePatternScorer(required_tools=["verify"])
        result = _RunResult()
        v = scorer.score(result, events)
        assert v.passed is False
        assert "verify" in (v.reason or "")
```

```python
# evals/scorers/trace.py
"""Trace-level scorers."""
from __future__ import annotations

from typing import Any

from evals.models.case import ValidatorSpec
from evals.models.result import ValidatorVerdict
from evals.models.trace import TraceEvent
from evals.scorers.base import Scorer


class TracePatternScorer(Scorer):
    def __init__(self, required_tools: list[str] | None = None) -> None:
        self.required_tools = required_tools or []

    @classmethod
    def from_spec(cls, spec: ValidatorSpec) -> TracePatternScorer:
        tools = []
        if spec.contains:
            tools = [t.strip() for t in spec.contains.split(",")]
        return cls(required_tools=tools)

    def score(self, run_result: Any, trace_events: list[TraceEvent]) -> ValidatorVerdict:
        called = {
            e.data.get("tool", "") for e in trace_events if e.kind == "tool_call"
        }
        missing = [t for t in self.required_tools if t not in called]
        passed = len(missing) == 0
        return ValidatorVerdict(
            validator="trace_pattern",
            passed=passed,
            reason=None if passed else f"required tools not called: {missing}",
        )
```

- [ ] **Step 7: Write test for build_scorer factory**

```python
# Append to tests/evals/test_scorers.py
class TestBuildScorer:
    def test_builds_final_status(self):
        spec = ValidatorSpec(type="final_status", expected="passed")
        scorer = build_scorer(spec)
        assert isinstance(scorer, FinalStatusScorer)

    def test_builds_text_contains(self):
        spec = ValidatorSpec(type="text_contains", contains="hello")
        scorer = build_scorer(spec)
        assert isinstance(scorer, TextContainsScorer)

    def test_unknown_type_raises(self):
        spec = ValidatorSpec(type="nonexistent")
        with pytest.raises(ValueError, match="Unknown scorer"):
            build_scorer(spec)
```

- [ ] **Step 8: Run all scorer tests**

Run: `uv run pytest tests/evals/test_scorers.py -v`
Expected: all PASS

- [ ] **Step 9: Commit**

```bash
git add evals/scorers/ tests/evals/test_scorers.py
git commit -m "feat(evals): add scorer framework — status, text, budget, trace validators"
```

______________________________________________________________________

## Task 3: YAML Case Loader and Fixture Server

**Files:**

- Create: `evals/conftest.py`

- Create: `evals/fixtures/hello.html`

- Create: `evals/fixtures/form_required.html`

- Create: `evals/fixtures/nav_links.html`

- Create: `evals/cases/smoke.yaml`

- Create: `tests/evals/test_case_loader.py`

- [ ] **Step 1: Write failing tests for YAML case loading**

```python
# tests/evals/test_case_loader.py
"""Tests for YAML case loader and fixture server."""
from __future__ import annotations

from pathlib import Path

import yaml
import pytest

from evals.models.case import EvalCase

_CASES_DIR = Path(__file__).resolve().parent.parent.parent / "evals" / "cases"


class TestYamlCaseLoader:
    def test_smoke_yaml_is_valid(self):
        path = _CASES_DIR / "smoke.yaml"
        assert path.exists(), f"smoke.yaml not found at {path}"
        with path.open(encoding="utf-8") as f:
            raw = yaml.safe_load(f)
        assert "cases" in raw
        cases = [EvalCase.model_validate(c) for c in raw["cases"]]
        assert len(cases) >= 3
        ids = [c.id for c in cases]
        assert len(ids) == len(set(ids)), "duplicate case IDs"

    def test_all_cases_have_validators(self):
        path = _CASES_DIR / "smoke.yaml"
        with path.open(encoding="utf-8") as f:
            raw = yaml.safe_load(f)
        for c in raw["cases"]:
            case = EvalCase.model_validate(c)
            assert len(case.validators) > 0, f"case {case.id} has no validators"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/evals/test_case_loader.py -v`
Expected: FAIL — `smoke.yaml not found`

- [ ] **Step 3: Create fixture HTML files**

```html
<!-- evals/fixtures/hello.html -->
<!DOCTYPE html>
<html lang="en">
<head><meta charset="utf-8"><title>Hello Fixture</title></head>
<body>
  <h1 id="main-heading">Hello World</h1>
  <p id="description">This is a simple test fixture for eval validation.</p>
  <a href="nav_links.html">Go to nav page</a>
</body>
</html>
```

```html
<!-- evals/fixtures/form_required.html -->
<!DOCTYPE html>
<html lang="en">
<head><meta charset="utf-8"><title>Form Fixture</title></head>
<body>
  <h1>Contact Form</h1>
  <form id="contact-form" onsubmit="handleSubmit(event)">
    <label for="name">Name (required):</label>
    <input type="text" id="name" name="name" required>
    <label for="email">Email (required):</label>
    <input type="email" id="email" name="email" required>
    <label for="message">Message:</label>
    <textarea id="message" name="message"></textarea>
    <button type="submit" id="submit-btn">Submit</button>
  </form>
  <div id="result" style="display:none;">
    <p id="success-msg">Form submitted successfully!</p>
  </div>
  <script>
    function handleSubmit(e) {
      e.preventDefault();
      document.getElementById('result').style.display = 'block';
    }
  </script>
</body>
</html>
```

```html
<!-- evals/fixtures/nav_links.html -->
<!DOCTYPE html>
<html lang="en">
<head><meta charset="utf-8"><title>Navigation Fixture</title></head>
<body>
  <h1>Navigation Page</h1>
  <nav id="main-nav">
    <ul>
      <li><a href="hello.html">Home</a></li>
      <li><a href="form_required.html">Contact Form</a></li>
      <li><a href="#section-a">Section A</a></li>
    </ul>
  </nav>
  <section id="section-a">
    <h2>Section A</h2>
    <p>Anchor link target.</p>
  </section>
</body>
</html>
```

- [ ] **Step 4: Create smoke.yaml case definitions**

```yaml
# evals/cases/smoke.yaml
cases:
  - id: hello_find_heading
    suite: smoke
    url: "http://localhost:{port}/hello.html"
    task: "Navigate to the page and report the text of the H1 heading."
    validators:
      - type: final_status
        expected: passed
      - type: text_contains
        contains: "Hello World"
    limits:
      max_iterations: 10
    tags: [navigation, read]
    trials: 3

  - id: hello_find_paragraph
    suite: smoke
    url: "http://localhost:{port}/hello.html"
    task: "Find the paragraph text on the page and report it."
    validators:
      - type: final_status
        expected: passed
      - type: text_contains
        contains: "simple test fixture"
    limits:
      max_iterations: 10
    tags: [navigation, read]
    trials: 3

  - id: form_required_fields
    suite: smoke
    url: "http://localhost:{port}/form_required.html"
    task: "Fill the contact form with name 'Test User' and email 'test@example.com', then submit it. Verify the success message appears."
    validators:
      - type: final_status
        expected: passed
      - type: text_contains
        contains: "submitted"
    limits:
      max_iterations: 15
    tags: [form, interaction]
    trials: 3

  - id: nav_links_explore
    suite: smoke
    url: "http://localhost:{port}/nav_links.html"
    task: "List all navigation links on the page and verify the anchor link to Section A works."
    validators:
      - type: final_status
        expected: passed
      - type: text_contains
        contains: "Section A"
    limits:
      max_iterations: 12
    tags: [navigation, links]
    trials: 3

  - id: form_verify_tool
    suite: smoke
    url: "http://localhost:{port}/form_required.html"
    task: "Fill the form with name 'Alice' and email 'alice@test.com', submit it, then verify the success message appears using the verify tool."
    validators:
      - type: final_status
        expected: passed
      - type: trace_pattern
        contains: "verify"
    limits:
      max_iterations: 15
    tags: [form, verify]
    trials: 3
```

- [ ] **Step 5: Write test for fixture server**

```python
# Append to tests/evals/test_case_loader.py
import http.client


class TestFixtureServer:
    def test_fixture_server_serves_hello(self, fixture_server):
        port = fixture_server
        conn = http.client.HTTPConnection("localhost", port, timeout=5)
        conn.request("GET", "/hello.html")
        resp = conn.getresponse()
        body = resp.read().decode("utf-8")
        conn.close()
        assert resp.status == 200
        assert "Hello World" in body

    def test_fixture_server_serves_form(self, fixture_server):
        port = fixture_server
        conn = http.client.HTTPConnection("localhost", port, timeout=5)
        conn.request("GET", "/form_required.html")
        resp = conn.getresponse()
        assert resp.status == 200
        conn.close()
```

- [ ] **Step 6: Implement conftest.py with fixture server and case loading**

```python
# evals/conftest.py
"""Pytest fixtures for eval framework: fixture HTTP server, case loading, worker_id pool."""
from __future__ import annotations

import functools
import http.server
import threading
from pathlib import Path
from typing import Iterator

import pytest
import yaml

from evals.models.case import EvalCase

_EVALS_ROOT = Path(__file__).resolve().parent
_FIXTURES_DIR = _EVALS_ROOT / "fixtures"
_CASES_DIR = _EVALS_ROOT / "cases"


# ---------------------------------------------------------------------------
# Fixture HTTP server (session-scoped, shared across all eval cases)
# ---------------------------------------------------------------------------

class _SilentHandler(http.server.SimpleHTTPRequestHandler):
    def log_message(self, format, *args):  # noqa: A002
        pass


@pytest.fixture(scope="session")
def fixture_server() -> Iterator[int]:
    handler = functools.partial(_SilentHandler, directory=str(_FIXTURES_DIR))
    srv = http.server.HTTPServer(("127.0.0.1", 0), handler)
    port = srv.server_address[1]
    thread = threading.Thread(target=srv.serve_forever, daemon=True)
    thread.start()
    yield port
    srv.shutdown()


# ---------------------------------------------------------------------------
# Case loading
# ---------------------------------------------------------------------------

def load_suite(suite_name: str) -> list[EvalCase]:
    path = _CASES_DIR / f"{suite_name}.yaml"
    if not path.exists():
        raise FileNotFoundError(f"Suite file not found: {path}")
    with path.open(encoding="utf-8") as f:
        raw = yaml.safe_load(f)
    return [EvalCase.model_validate(c) for c in raw.get("cases", [])]


def resolve_url(url_template: str, port: int) -> str:
    return url_template.replace("{port}", str(port))


# ---------------------------------------------------------------------------
# Worker ID pool for concurrent Chrome isolation
# ---------------------------------------------------------------------------

class WorkerIdPool:
    def __init__(self, max_workers: int = 8) -> None:
        self._available = list(range(100, 100 + max_workers))
        self._lock = threading.Lock()

    def acquire(self) -> int:
        with self._lock:
            if not self._available:
                raise RuntimeError("No worker IDs available")
            return self._available.pop(0)

    def release(self, worker_id: int) -> None:
        with self._lock:
            if worker_id not in self._available:
                self._available.append(worker_id)


@pytest.fixture(scope="session")
def worker_pool() -> WorkerIdPool:
    return WorkerIdPool()
```

- [ ] **Step 7: Run all case loader and fixture tests**

Run: `uv run pytest tests/evals/test_case_loader.py -v`
Expected: all PASS

- [ ] **Step 8: Commit**

```bash
git add evals/conftest.py evals/fixtures/ evals/cases/ tests/evals/test_case_loader.py
git commit -m "feat(evals): add YAML case loader, fixture HTML pages, fixture HTTP server"
```

______________________________________________________________________

## Task 4: EvalCaseRunner (orchestrator)

**Files:**

- Create: `evals/runner.py`

- Create: `tests/evals/test_runner.py`

- [ ] **Step 1: Write failing test for EvalCaseRunner with mock**

```python
# tests/evals/test_runner.py
"""Tests for EvalCaseRunner — uses mock RunResult, no real LLM."""
from __future__ import annotations

import sys
from dataclasses import dataclass, field
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

from evals.models.case import EvalCase, ValidatorSpec, Limits
from evals.models.result import EvalCaseResult
from evals.models.trace import TraceRecord
from evals.runner import EvalCaseRunner


@dataclass
class _ToolCall:
    tool: str = "mcp__browser__navigate_page"
    input: dict = field(default_factory=dict)
    result: str = "ok"
    is_error: bool = False


@dataclass
class _Step:
    description: str = ""
    tool_calls: list[_ToolCall] = field(default_factory=list)
    screenshots: list = field(default_factory=list)

    @property
    def is_error(self) -> bool:
        return any(tc.is_error for tc in self.tool_calls)


@dataclass
class _RunResult:
    final_text: str = '<final_outcome>{"status":"passed","summary":"found heading"}</final_outcome>'
    steps: list = field(default_factory=lambda: [
        _Step(tool_calls=[_ToolCall()]),
        _Step(tool_calls=[_ToolCall(tool="verify")]),
    ])
    aborted: bool = False
    input_tokens: int = 500
    output_tokens: int = 200
    extensions_failed: list = field(default_factory=list)


class TestEvalCaseRunner:
    def test_run_single_trial_with_mock(self, tmp_path):
        case = EvalCase.model_validate({
            "id": "test_mock",
            "suite": "smoke",
            "url": "http://localhost:9999/hello.html",
            "task": "Find the heading",
            "validators": [
                {"type": "final_status", "expected": "passed"},
            ],
            "trials": 1,
        })

        mock_result = _RunResult()

        with patch("evals.runner.run_cc_mini", return_value=mock_result):
            runner = EvalCaseRunner(output_dir=tmp_path)
            results = runner.run_case(case, url="http://localhost:9999/hello.html")

        assert len(results) == 1
        assert results[0].oracle_passed is True
        assert results[0].case_id == "test_mock"
        # Check trace was written
        trace_path = tmp_path / "test_mock" / "trial_0.trace.json"
        assert trace_path.exists()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/evals/test_runner.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'evals.runner'`

- [ ] **Step 3: Implement EvalCaseRunner**

```python
# evals/runner.py
"""EvalCaseRunner — orchestrates run_cc_mini() calls, trace capture, and scoring."""
from __future__ import annotations

import logging
import sys
import time
from pathlib import Path
from typing import Any

from evals.models.case import EvalCase
from evals.models.result import EvalCaseResult, ValidatorVerdict
from evals.models.trace import TraceEvent, TraceRecord
from evals.scorers.base import build_scorer

_CC_MINI_ROOT = Path(__file__).resolve().parent.parent / "webqa-cc-mini"
if str(_CC_MINI_ROOT) not in sys.path:
    sys.path.insert(0, str(_CC_MINI_ROOT))

from runner import run_cc_mini, RunResult
from core.outcome_status import derive_status, extract_final_outcome

log = logging.getLogger("evals.runner")


class EvalCaseRunner:
    def __init__(
        self,
        output_dir: Path,
        *,
        provider: str | None = None,
        model: str | None = None,
        api_key: str | None = None,
        base_url: str | None = None,
        effort: str | None = None,
        filter_model: str | None = None,
        worker_id: int = 100,
        headless: bool = True,
    ) -> None:
        self.output_dir = Path(output_dir)
        self.provider = provider
        self.model = model
        self.api_key = api_key
        self.base_url = base_url
        self.effort = effort
        self.filter_model = filter_model
        self.worker_id = worker_id
        self.headless = headless

    def run_case(
        self,
        case: EvalCase,
        *,
        url: str | None = None,
    ) -> list[EvalCaseResult]:
        resolved_url = url or case.url
        results: list[EvalCaseResult] = []

        for trial in range(case.trials):
            log.info("Case %s trial %d/%d", case.id, trial + 1, case.trials)
            trace = TraceRecord(case_id=case.id, trial=trial)
            start = time.monotonic()

            def _on_event(evt: tuple) -> None:
                trace.append(TraceEvent.from_engine_event(evt))

            run_result = run_cc_mini(
                url=resolved_url,
                user_input=case.task,
                worker_id=self.worker_id,
                provider=self.provider,
                model=self.model,
                api_key=self.api_key,
                base_url=self.base_url,
                effort=self.effort,
                filter_model=self.filter_model,
                max_iterations=case.limits.max_iterations,
                max_time_seconds=case.limits.max_time_seconds,
                on_event=_on_event,
                browser_headless=self.headless,
            )

            duration = time.monotonic() - start

            # Save trace
            case_dir = self.output_dir / case.id
            case_dir.mkdir(parents=True, exist_ok=True)
            trace_path = case_dir / f"trial_{trial}.trace.json"
            trace.save(trace_path)

            # Derive agent-reported status
            outcome = extract_final_outcome(run_result.final_text or "")
            failed_count = sum(1 for s in run_result.steps if getattr(s, "is_error", False))
            agent_status, _ = derive_status(
                aborted=run_result.aborted, failed_count=failed_count, outcome=outcome,
            )

            # Run scorers
            scorers = [build_scorer(spec) for spec in case.validators]
            verdicts = [s.score(run_result, trace.events) for s in scorers]

            result = EvalCaseResult(
                case_id=case.id,
                trial=trial,
                verdicts=verdicts,
                steps=len(run_result.steps),
                input_tokens=run_result.input_tokens,
                output_tokens=run_result.output_tokens,
                duration_seconds=round(duration, 2),
                aborted=run_result.aborted,
                agent_status=agent_status,
                trace_path=str(trace_path),
            )
            results.append(result)

            # Save per-trial result
            result_path = case_dir / f"trial_{trial}.result.json"
            result_path.write_text(result.model_dump_json(indent=2), encoding="utf-8")

        return results
```

- [ ] **Step 4: Write test for multi-trial pass@k**

```python
# Append to tests/evals/test_runner.py
class TestPassAtK:
    def test_pass_at_k_all_pass(self, tmp_path):
        case = EvalCase.model_validate({
            "id": "pass_k_test",
            "suite": "smoke",
            "url": "http://localhost:9999/hello.html",
            "task": "Find heading",
            "validators": [{"type": "final_status", "expected": "passed"}],
            "trials": 3,
        })
        mock_result = _RunResult()

        with patch("evals.runner.run_cc_mini", return_value=mock_result):
            runner = EvalCaseRunner(output_dir=tmp_path)
            results = runner.run_case(case, url="http://localhost:9999/hello.html")

        assert len(results) == 3
        pass_rate = sum(1 for r in results if r.oracle_passed) / len(results)
        assert pass_rate == 1.0
```

- [ ] **Step 5: Run all runner tests**

Run: `uv run pytest tests/evals/test_runner.py -v`
Expected: all PASS

- [ ] **Step 6: Commit**

```bash
git add evals/runner.py tests/evals/test_runner.py
git commit -m "feat(evals): add EvalCaseRunner with trace capture, scoring, multi-trial"
```

______________________________________________________________________

## Task 5: Baseline Comparison

**Files:**

- Create: `evals/models/baseline.py`

- Create: `tests/evals/test_baseline.py`

- [ ] **Step 1: Write failing tests for baseline comparison**

```python
# tests/evals/test_baseline.py
"""Tests for baseline comparison logic."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from evals.models.baseline import BaselineEntry, BaselineDiff, compare_to_baseline
from evals.models.result import EvalCaseResult, ValidatorVerdict


def _make_result(case_id: str, passed: bool, steps: int = 5, tokens: int = 1000) -> EvalCaseResult:
    return EvalCaseResult(
        case_id=case_id,
        trial=0,
        verdicts=[ValidatorVerdict(validator="final_status", passed=passed)],
        steps=steps,
        input_tokens=tokens,
        output_tokens=tokens // 2,
        aborted=False,
        agent_status="passed" if passed else "failed",
    )


class TestBaselineEntry:
    def test_from_results(self):
        results = [
            _make_result("c1", True, steps=5, tokens=1000),
            _make_result("c1", True, steps=7, tokens=1200),
            _make_result("c1", False, steps=10, tokens=2000),
        ]
        entry = BaselineEntry.from_results("c1", results)
        assert entry.case_id == "c1"
        assert entry.pass_rate == pytest.approx(2 / 3)
        assert entry.median_steps == 7
        assert entry.trials == 3


class TestCompareToBaseline:
    def test_no_regression(self):
        baseline = {"c1": BaselineEntry(case_id="c1", pass_rate=1.0, median_steps=5, median_tokens=1500, trials=3)}
        candidate = {"c1": [_make_result("c1", True, 4, 1000)]}
        diffs = compare_to_baseline(baseline, candidate)
        assert len(diffs) == 1
        assert diffs[0].regressed is False

    def test_detects_regression(self):
        baseline = {"c1": BaselineEntry(case_id="c1", pass_rate=1.0, median_steps=5, median_tokens=1500, trials=3)}
        candidate = {"c1": [_make_result("c1", False, 10, 3000)]}
        diffs = compare_to_baseline(baseline, candidate)
        assert diffs[0].regressed is True
        assert diffs[0].pass_rate_delta < 0

    def test_new_case_not_regressed(self):
        baseline = {}
        candidate = {"new_case": [_make_result("new_case", True)]}
        diffs = compare_to_baseline(baseline, candidate)
        assert len(diffs) == 1
        assert diffs[0].regressed is False
        assert diffs[0].is_new is True

    def test_save_and_load_baseline(self, tmp_path):
        entries = {"c1": BaselineEntry(case_id="c1", pass_rate=0.8, median_steps=6, median_tokens=2000, trials=5)}
        path = tmp_path / "baseline.json"
        BaselineEntry.save_baseline(entries, path)
        loaded = BaselineEntry.load_baseline(path)
        assert loaded["c1"].pass_rate == pytest.approx(0.8)
        assert loaded["c1"].median_steps == 6
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/evals/test_baseline.py -v`
Expected: FAIL — `ModuleNotFoundError`

- [ ] **Step 3: Implement baseline comparison**

```python
# evals/models/baseline.py
"""Baseline persistence and comparison."""
from __future__ import annotations

import json
import statistics
from pathlib import Path

from pydantic import BaseModel

from evals.models.result import EvalCaseResult


class BaselineEntry(BaseModel):
    case_id: str
    pass_rate: float
    median_steps: int
    median_tokens: int
    trials: int

    @classmethod
    def from_results(cls, case_id: str, results: list[EvalCaseResult]) -> BaselineEntry:
        n = len(results)
        passed = sum(1 for r in results if r.oracle_passed)
        steps = sorted(r.steps for r in results)
        tokens = sorted(r.input_tokens + r.output_tokens for r in results)
        return cls(
            case_id=case_id,
            pass_rate=passed / n if n else 0.0,
            median_steps=int(statistics.median(steps)) if steps else 0,
            median_tokens=int(statistics.median(tokens)) if tokens else 0,
            trials=n,
        )

    @staticmethod
    def save_baseline(entries: dict[str, BaselineEntry], path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        data = {k: v.model_dump() for k, v in entries.items()}
        path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")

    @staticmethod
    def load_baseline(path: Path) -> dict[str, BaselineEntry]:
        raw = json.loads(path.read_text(encoding="utf-8"))
        return {k: BaselineEntry.model_validate(v) for k, v in raw.items()}


class BaselineDiff(BaseModel):
    case_id: str
    pass_rate_delta: float
    steps_delta: int
    tokens_delta: int
    regressed: bool
    is_new: bool = False


def compare_to_baseline(
    baseline: dict[str, BaselineEntry],
    candidate: dict[str, list[EvalCaseResult]],
    *,
    regression_threshold: float = 0.1,
) -> list[BaselineDiff]:
    diffs: list[BaselineDiff] = []
    for case_id, results in candidate.items():
        entry = BaselineEntry.from_results(case_id, results)
        base = baseline.get(case_id)
        if base is None:
            diffs.append(BaselineDiff(
                case_id=case_id, pass_rate_delta=0, steps_delta=0,
                tokens_delta=0, regressed=False, is_new=True,
            ))
            continue
        pr_delta = entry.pass_rate - base.pass_rate
        steps_delta = entry.median_steps - base.median_steps
        tokens_delta = entry.median_tokens - base.median_tokens
        regressed = pr_delta < -regression_threshold
        diffs.append(BaselineDiff(
            case_id=case_id, pass_rate_delta=round(pr_delta, 4),
            steps_delta=steps_delta, tokens_delta=tokens_delta,
            regressed=regressed,
        ))
    return diffs
```

- [ ] **Step 4: Run baseline tests**

Run: `uv run pytest tests/evals/test_baseline.py -v`
Expected: all PASS

- [ ] **Step 5: Commit**

```bash
git add evals/models/baseline.py tests/evals/test_baseline.py
git commit -m "feat(evals): add baseline comparison with regression detection"
```

______________________________________________________________________

## Task 6: JSON/HTML Report Generation

**Files:**

- Create: `evals/report.py`

- Create: `tests/evals/test_report.py`

- [ ] **Step 1: Write failing tests for report generation**

```python
# tests/evals/test_report.py
"""Tests for eval report generation."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from evals.models.result import EvalCaseResult, ValidatorVerdict
from evals.models.baseline import BaselineDiff
from evals.report import write_summary_json, render_eval_report


def _make_result(case_id: str, passed: bool, trial: int = 0) -> EvalCaseResult:
    return EvalCaseResult(
        case_id=case_id, trial=trial,
        verdicts=[ValidatorVerdict(validator="final_status", passed=passed)],
        steps=5, input_tokens=1000, output_tokens=500,
        duration_seconds=10.5, aborted=False,
        agent_status="passed" if passed else "failed",
    )


class TestSummaryJson:
    def test_writes_valid_json(self, tmp_path):
        results = {
            "hello_h1": [_make_result("hello_h1", True, t) for t in range(3)],
            "form_fill": [_make_result("form_fill", False, t) for t in range(3)],
        }
        path = tmp_path / "summary.json"
        write_summary_json(results, path)
        data = json.loads(path.read_text(encoding="utf-8"))
        assert "cases" in data
        assert data["aggregate"]["total_cases"] == 2
        assert data["aggregate"]["pass_rate"] == pytest.approx(0.5)


class TestHtmlReport:
    def test_renders_valid_html(self, tmp_path):
        results = {"c1": [_make_result("c1", True)]}
        diffs = [BaselineDiff(
            case_id="c1", pass_rate_delta=0.0,
            steps_delta=0, tokens_delta=0, regressed=False,
        )]
        path = tmp_path / "report.html"
        render_eval_report(results, diffs, path)
        content = path.read_text(encoding="utf-8")
        assert "<!DOCTYPE html>" in content
        assert "c1" in content
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/evals/test_report.py -v`
Expected: FAIL

- [ ] **Step 3: Implement report generation**

```python
# evals/report.py
"""JSON summary and HTML report generation."""
from __future__ import annotations

import html
import json
import statistics
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from evals.models.baseline import BaselineDiff
from evals.models.result import EvalCaseResult


def write_summary_json(
    results: dict[str, list[EvalCaseResult]],
    path: Path,
) -> None:
    cases: dict[str, Any] = {}
    total_passed = 0
    total_cases = len(results)

    for case_id, trials in results.items():
        pass_count = sum(1 for t in trials if t.oracle_passed)
        pass_rate = pass_count / len(trials) if trials else 0.0
        if pass_rate >= 0.5:
            total_passed += 1
        steps = [t.steps for t in trials]
        tokens = [t.input_tokens + t.output_tokens for t in trials]
        cases[case_id] = {
            "trials": len(trials),
            "pass_rate": round(pass_rate, 4),
            "median_steps": int(statistics.median(steps)) if steps else 0,
            "median_tokens": int(statistics.median(tokens)) if tokens else 0,
            "results": [t.model_dump() for t in trials],
        }

    summary = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "aggregate": {
            "total_cases": total_cases,
            "cases_passed": total_passed,
            "pass_rate": round(total_passed / total_cases, 4) if total_cases else 0.0,
        },
        "cases": cases,
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8")


def render_eval_report(
    results: dict[str, list[EvalCaseResult]],
    diffs: list[BaselineDiff],
    path: Path,
) -> Path:
    diff_map = {d.case_id: d for d in diffs}
    rows: list[str] = []
    for case_id, trials in results.items():
        pass_count = sum(1 for t in trials if t.oracle_passed)
        pass_rate = pass_count / len(trials) if trials else 0.0
        d = diff_map.get(case_id)
        delta_str = ""
        status_cls = "ok" if pass_rate >= 0.5 else "err"
        if d is not None:
            if d.is_new:
                delta_str = '<span class="new">NEW</span>'
            elif d.regressed:
                delta_str = f'<span class="reg">{d.pass_rate_delta:+.0%}</span>'
                status_cls = "err"
            else:
                delta_str = f'<span class="ok">{d.pass_rate_delta:+.0%}</span>'
        steps = [t.steps for t in trials]
        tokens = [t.input_tokens + t.output_tokens for t in trials]
        med_steps = int(statistics.median(steps)) if steps else 0
        med_tokens = int(statistics.median(tokens)) if tokens else 0
        rows.append(
            f'<tr class="{status_cls}">'
            f"<td>{html.escape(case_id)}</td>"
            f"<td>{pass_rate:.0%} ({pass_count}/{len(trials)})</td>"
            f"<td>{delta_str}</td>"
            f"<td>{med_steps}</td>"
            f"<td>{med_tokens:,}</td></tr>"
        )

    table_body = "\n".join(rows)
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    total = len(results)
    total_passed = sum(
        1 for trials in results.values()
        if sum(1 for t in trials if t.oracle_passed) / max(len(trials), 1) >= 0.5
    )

    page = f"""<!DOCTYPE html>
<html lang="en">
<head><meta charset="utf-8"><title>Eval Report</title>
<style>
body {{ font-family: system-ui, sans-serif; margin: 24px; background: #0f1419; color: #e6e6e6; }}
h1 {{ font-size: 20px; }} .meta {{ color: #8b9098; font-size: 13px; margin-bottom: 16px; }}
table {{ border-collapse: collapse; width: 100%; }} th, td {{ padding: 8px 12px; text-align: left; border-bottom: 1px solid #2a2f38; }}
th {{ color: #8b9098; font-size: 12px; text-transform: uppercase; }}
tr.ok td:first-child {{ border-left: 3px solid #4ade80; }}
tr.err td:first-child {{ border-left: 3px solid #f87171; }}
.reg {{ color: #f87171; font-weight: 600; }} .ok {{ color: #4ade80; }} .new {{ color: #60a5fa; }}
</style></head>
<body>
<h1>Eval Report</h1>
<div class="meta">{now} &mdash; {total_passed}/{total} cases passed</div>
<table><thead><tr><th>Case</th><th>Pass Rate</th><th>Delta</th><th>Steps (med)</th><th>Tokens (med)</th></tr></thead>
<tbody>{table_body}</tbody></table>
</body></html>"""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(page, encoding="utf-8")
    return path
```

- [ ] **Step 4: Run report tests**

Run: `uv run pytest tests/evals/test_report.py -v`
Expected: all PASS

- [ ] **Step 5: Commit**

```bash
git add evals/report.py tests/evals/test_report.py
git commit -m "feat(evals): add JSON summary and HTML diff report generation"
```

______________________________________________________________________

## Task 7: pytest Integration (conftest hooks + test entry point)

**Files:**

- Modify: `evals/conftest.py` (add pytest_addoption, pytest_generate_tests, pytest_configure, eval_output_dir, session report)
- Create: `evals/test_eval_smoke.py` (pure test file — parametrized via conftest hooks)
- Create: `tests/evals/test_integration.py`

Note: All pytest hooks (`pytest_addoption`, `pytest_generate_tests`, `pytest_configure`) **must** live in `evals/conftest.py`, not in the test file. pytest only discovers hooks from conftest.py files.

- [ ] **Step 1: Add pytest hooks and eval options to evals/conftest.py**

Append to the existing `evals/conftest.py` (created in Task 3):

```python
# Append to evals/conftest.py

def pytest_configure(config: pytest.Config) -> None:
    config.addinivalue_line("markers", "eval: marks tests as eval benchmark cases")


def pytest_addoption(parser: pytest.Parser) -> None:
    group = parser.getgroup("eval", "Eval framework options")
    group.addoption("--suite", default="smoke", help="Suite name (default: smoke)")
    group.addoption("--provider", default=None, help="LLM provider")
    group.addoption("--model", default=None, help="LLM model")
    group.addoption("--filter-model", default=None, help="Filter model for verify tool")
    group.addoption("--api-key", default=None, help="API key")
    group.addoption("--effort", default=None, help="Reasoning effort")
    group.addoption("--eval-trials", default=None, type=int, help="Override trials per case")
    group.addoption("--mock", action="store_true", default=False, help="Use mock LLM (no real API calls)")


def pytest_generate_tests(metafunc: pytest.Metafunc) -> None:
    if "eval_case" in metafunc.fixturenames:
        suite_name = metafunc.config.getoption("--suite", "smoke")
        cases = load_suite(suite_name)
        trial_override = metafunc.config.getoption("--eval-trials", None)
        if trial_override is not None:
            for c in cases:
                c.trials = trial_override
        metafunc.parametrize("eval_case", cases, ids=[c.id for c in cases])


@pytest.fixture(scope="session")
def eval_output_dir(tmp_path_factory: pytest.TempPathFactory) -> str:
    return str(tmp_path_factory.mktemp("eval_results"))
```

- [ ] **Step 2: Write the pytest eval test file**

```python
# evals/test_eval_smoke.py
"""Pytest-native eval entry point.

Run: uv run pytest evals/test_eval_smoke.py -v -m eval
       --provider anthropic --model claude-haiku-4-5-20251001

Or with mock (no LLM): uv run pytest evals/test_eval_smoke.py -v -m eval --mock
"""
from __future__ import annotations

from pathlib import Path

import pytest

from evals.conftest import resolve_url
from evals.models.case import EvalCase
from evals.runner import EvalCaseRunner


@pytest.mark.eval
def test_eval_case(
    eval_case: EvalCase,
    fixture_server: int,
    eval_output_dir: str,
    request: pytest.FixtureRequest,
) -> None:
    url = resolve_url(eval_case.url, fixture_server)
    runner = EvalCaseRunner(
        output_dir=Path(eval_output_dir),
        provider=request.config.getoption("--provider"),
        model=request.config.getoption("--model"),
        api_key=request.config.getoption("--api-key"),
        effort=request.config.getoption("--effort"),
        filter_model=request.config.getoption("--filter-model"),
        headless=True,
    )

    if request.config.getoption("--mock"):
        from dataclasses import dataclass, field
        from unittest.mock import patch

        @dataclass
        class _MockResult:
            final_text: str = '<final_outcome>{"status":"passed","summary":"mock"}</final_outcome>'
            steps: list = field(default_factory=list)
            aborted: bool = False
            input_tokens: int = 100
            output_tokens: int = 50
            extensions_failed: list = field(default_factory=list)

        with patch("evals.runner.run_cc_mini", return_value=_MockResult()):
            results = runner.run_case(eval_case, url=url)
    else:
        results = runner.run_case(eval_case, url=url)

    pass_count = sum(1 for r in results if r.oracle_passed)
    pass_rate = pass_count / len(results) if results else 0.0
    assert pass_rate > 0, (
        f"Case {eval_case.id}: 0/{len(results)} trials passed. "
        f"Failures: {[r.verdicts for r in results if not r.oracle_passed]}"
    )
```

- [ ] **Step 3: Write integration test (mock mode only)**

```python
# tests/evals/test_integration.py
"""Integration test: run the eval framework end-to-end with mock LLM."""
from __future__ import annotations

from pathlib import Path

import pytest


class TestEvalIntegration:
    def test_smoke_suite_mock_mode(self):
        """Verify the full eval pipeline works with mock."""
        exit_code = pytest.main([
            str(Path(__file__).resolve().parent.parent.parent / "evals" / "test_eval_smoke.py"),
            "-v", "-m", "eval", "--mock",
            "--suite", "smoke",
            "--eval-trials", "1",
        ])
        # exit_code 0 = all passed, 5 = no tests collected (also ok for smoke check)
        assert exit_code in (0, 5), f"Eval smoke failed with exit code {exit_code}"
```

- [ ] **Step 4: Run integration test**

Run mock eval directly: `uv run pytest evals/test_eval_smoke.py -v -m eval --mock --eval-trials 1`
Expected: all smoke cases PASS with mock

Run integration: `uv run pytest tests/evals/test_integration.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add evals/conftest.py evals/test_eval_smoke.py tests/evals/test_integration.py
git commit -m "feat(evals): add pytest-native eval runner with mock mode and CI markers"
```

______________________________________________________________________

## Task 8: Baseline Workflow and Smoke Baseline

**Files:**

- Create: `evals/baselines/smoke.baseline.json` (generated after first real run)

- Modify: `evals/test_eval_smoke.py` (add baseline comparison post-test)

- [ ] **Step 1: Add baseline comparison to the eval session**

Add a session-scoped finalizer to `evals/conftest.py` that after all cases complete, writes `summary.json` and compares against baseline if one exists.

```python
# Append to evals/conftest.py:

@pytest.fixture(scope="session", autouse=True)
def eval_session_report(request: pytest.FixtureRequest, eval_output_dir: str) -> None:
    yield  # run all tests first
    from pathlib import Path
    from evals.report import write_summary_json, render_eval_report
    from evals.models.baseline import BaselineEntry, compare_to_baseline
    from evals.models.result import EvalCaseResult
    import json

    output = Path(eval_output_dir)
    # Collect all result files
    all_results: dict[str, list[EvalCaseResult]] = {}
    for case_dir in sorted(output.iterdir()):
        if not case_dir.is_dir():
            continue
        results = []
        for rf in sorted(case_dir.glob("trial_*.result.json")):
            results.append(EvalCaseResult.model_validate_json(rf.read_text(encoding="utf-8")))
        if results:
            all_results[case_dir.name] = results

    if not all_results:
        return

    # Write summary
    write_summary_json(all_results, output / "summary.json")

    # Compare to baseline if exists
    evals_root = Path(__file__).resolve().parent
    suite_name = request.config.getoption("--suite", "smoke")
    baseline_path = evals_root / "baselines" / f"{suite_name}.baseline.json"
    diffs = []
    if baseline_path.exists():
        baseline = BaselineEntry.load_baseline(baseline_path)
        diffs = compare_to_baseline(baseline, all_results)
        regressions = [d for d in diffs if d.regressed]
        if regressions:
            names = ", ".join(d.case_id for d in regressions)
            print(f"\n⚠️  REGRESSIONS detected: {names}")

    # Write HTML report
    render_eval_report(all_results, diffs, output / "report.html")
    print(f"\n📊 Eval report: {output / 'report.html'}")
    print(f"📋 Summary: {output / 'summary.json'}")
```

- [ ] **Step 2: Create a script to promote results to baseline**

```python
# evals/promote_baseline.py
"""Promote an eval summary.json into a pinned baseline file.

Usage: python -m evals.promote_baseline <summary.json> [suite_name]
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

from evals.models.baseline import BaselineEntry
from evals.models.result import EvalCaseResult


def main() -> None:
    if len(sys.argv) < 2:
        print("Usage: python -m evals.promote_baseline <summary.json> [suite]")
        sys.exit(1)

    summary_path = Path(sys.argv[1])
    suite = sys.argv[2] if len(sys.argv) > 2 else "smoke"

    data = json.loads(summary_path.read_text(encoding="utf-8"))
    entries: dict[str, BaselineEntry] = {}
    for case_id, case_data in data["cases"].items():
        results = [EvalCaseResult.model_validate(r) for r in case_data["results"]]
        entries[case_id] = BaselineEntry.from_results(case_id, results)

    out = Path(__file__).resolve().parent / "baselines" / f"{suite}.baseline.json"
    BaselineEntry.save_baseline(entries, out)
    print(f"Baseline promoted to {out}")


if __name__ == "__main__":
    main()
```

- [ ] **Step 3: Create empty baselines directory**

```bash
mkdir -p evals/baselines
echo '{}' > evals/baselines/smoke.baseline.json
```

- [ ] **Step 4: Run full mock eval and verify report generation**

Run: `uv run pytest evals/test_eval_smoke.py -v -m eval --mock --eval-trials 1 -s`
Expected: PASS, summary.json and report.html written, "no regressions" output

- [ ] **Step 5: Commit**

```bash
git add evals/conftest.py evals/promote_baseline.py evals/baselines/
git commit -m "feat(evals): add baseline comparison workflow and promote script"
```

______________________________________________________________________

## Verification

After all tasks are complete, verify end-to-end:

1. **Unit tests (no LLM, no browser):**

   ```bash
   uv run pytest tests/evals/ -v
   ```

   Expected: all PASS

2. **Mock eval run (no LLM, no browser):**

   ```bash
   uv run pytest evals/test_eval_smoke.py -v -m eval --mock --eval-trials 1 -s
   ```

   Expected: all smoke cases PASS, summary.json + report.html generated

3. **Real eval run (requires LLM API key + Chrome):**

   ```bash
   uv run pytest evals/test_eval_smoke.py -v -m eval \
     --provider anthropic --model claude-haiku-4-5-20251001 \
     --eval-trials 1 -s
   ```

   Expected: cases execute against fixture server, results and traces saved

4. **Promote baseline:**

   ```bash
   python evals/test_eval_smoke.py promote <path-to-summary.json> smoke
   ```

5. **Regression check (re-run and compare):**

   ```bash
   uv run pytest evals/test_eval_smoke.py -v -m eval --mock --eval-trials 1 -s
   ```

   Expected: "no regressions" in output

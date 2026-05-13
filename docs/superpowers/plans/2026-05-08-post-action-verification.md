# Post-Action Verification Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add engine-level screenshot hash comparison and system prompt verification methodology to detect semantic failures.

**Architecture:** Engine adds `_prev_screenshot_hash` instance var and `_screenshot_content_hash` helper. Both screenshot paths (LLM-initiated and auto-injected) annotate tool_result text with factual state-change observation. System prompt Step 4, error handling, and risk-based verification sections strengthened.

**Tech Stack:** Python (engine.py, context.py), pytest (unit + integration tests)

**Spec:** `docs/superpowers/specs/2026-05-08-post-action-verification-design.md`

______________________________________________________________________

## File Map

| Action | Path                                | Responsibility                         |
| ------ | ----------------------------------- | -------------------------------------- |
| Modify | `webqa-cc-mini/core/engine.py`      | Hash comparison + annotation           |
| Modify | `webqa-cc-mini/core/context.py`     | System prompt verification methodology |
| Create | `tests/test_cc_mini_post_action.py` | Unit tests for hash comparison         |
| Modify | `tests/test_cc_mini_skills.py`      | Integration tests for prompt changes   |

______________________________________________________________________

### Task 1: Write failing tests for engine hash comparison

**Files:**

- Create: `tests/test_cc_mini_post_action.py`

- [ ] **Step 1: Create test file with unit tests**

Create `tests/test_cc_mini_post_action.py`:

```python
"""Tests for post-action screenshot hash comparison in the engine.

Covers:
* _screenshot_content_hash — extracting MD5 from ToolResult image blocks
* Engine._prev_screenshot_hash — state tracking across screenshots
* Annotation text appended to screenshot tool_result content
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

_CC_MINI_ROOT = Path(__file__).resolve().parent.parent / 'webqa-cc-mini'
if str(_CC_MINI_ROOT) not in sys.path:
    sys.path.insert(0, str(_CC_MINI_ROOT))

from core.engine import _screenshot_content_hash  # noqa: E402
from core.tool import ToolResult  # noqa: E402


class TestScreenshotContentHash:
    def test_returns_md5_for_image_block(self):
        result = ToolResult(
            content='Took a screenshot',
            content_blocks=[{
                'type': 'image',
                'data': 'iVBORw0KGgoAAAANSUhEUg==',
                'mimeType': 'image/png',
            }],
        )
        h = _screenshot_content_hash(result)
        assert h is not None
        assert len(h) == 32  # MD5 hex digest length

    def test_returns_none_for_no_image(self):
        result = ToolResult(content='Some text', content_blocks=[])
        assert _screenshot_content_hash(result) is None

    def test_returns_none_for_text_only_blocks(self):
        result = ToolResult(
            content='text',
            content_blocks=[{'type': 'text', 'text': 'hello'}],
        )
        assert _screenshot_content_hash(result) is None

    def test_returns_none_for_empty_data(self):
        result = ToolResult(
            content='screenshot',
            content_blocks=[{'type': 'image', 'data': '', 'mimeType': 'image/png'}],
        )
        assert _screenshot_content_hash(result) is None

    def test_same_data_same_hash(self):
        blocks = [{'type': 'image', 'data': 'AAAA', 'mimeType': 'image/png'}]
        r1 = ToolResult(content='a', content_blocks=list(blocks))
        r2 = ToolResult(content='b', content_blocks=list(blocks))
        assert _screenshot_content_hash(r1) == _screenshot_content_hash(r2)

    def test_different_data_different_hash(self):
        r1 = ToolResult(
            content='a',
            content_blocks=[{'type': 'image', 'data': 'AAAA', 'mimeType': 'image/png'}],
        )
        r2 = ToolResult(
            content='b',
            content_blocks=[{'type': 'image', 'data': 'BBBB', 'mimeType': 'image/png'}],
        )
        assert _screenshot_content_hash(r1) != _screenshot_content_hash(r2)

    def test_uses_first_image_block(self):
        result = ToolResult(
            content='multi',
            content_blocks=[
                {'type': 'image', 'data': 'FIRST', 'mimeType': 'image/png'},
                {'type': 'image', 'data': 'SECOND', 'mimeType': 'image/png'},
            ],
        )
        h = _screenshot_content_hash(result)
        single = ToolResult(
            content='single',
            content_blocks=[{'type': 'image', 'data': 'FIRST', 'mimeType': 'image/png'}],
        )
        assert h == _screenshot_content_hash(single)
```

- [ ] **Step 2: Run to verify tests fail**

Run: `cd /home/tutu/projects/saas/webqa-agent && uv run pytest tests/test_cc_mini_post_action.py -v 2>&1 | tail -15`
Expected: ImportError — `_screenshot_content_hash` does not exist yet.

- [ ] **Step 3: Commit failing tests**

```bash
git add tests/test_cc_mini_post_action.py
git commit -m "test(verification): add failing tests for screenshot hash comparison"
```

______________________________________________________________________

### Task 2: Implement engine hash comparison

**Files:**

- Modify: `webqa-cc-mini/core/engine.py`

- [ ] **Step 1: Add import and helper function**

At the top of `engine.py`, add `hashlib` to the existing imports (line 1-6 area):

```python
import hashlib
```

Add the helper function after `_JITTER_FACTOR = 0.25` (around line 42):

```python
def _screenshot_content_hash(result: ToolResult) -> str | None:
    """MD5 of the first image block's base64 data, or None."""
    for blk in result.content_blocks or []:
        if isinstance(blk, dict) and blk.get('type') == 'image':
            data = blk.get('data', '')
            if data:
                return hashlib.md5(data.encode('ascii')).hexdigest()
    return None
```

- [ ] **Step 2: Add instance variable to Engine.__init__**

In `Engine.__init__` (after `self._data_flow_sequence = 0` on line 119), add:

```python
        self._prev_screenshot_hash: str | None = None
```

- [ ] **Step 3: Add annotation logic to auto-injected screenshot path**

In the auto-screenshot block (after `ss_result = ss_tool.execute(**ss_input)` on line 607, before `ss_end = iso_now()` on line 608), insert:

```python
                        self._annotate_screenshot_state(ss_result, has_mutation=True)
```

- [ ] **Step 4: Add annotation logic to LLM-initiated screenshot path**

In `_execute_tool` (after `return tool.execute(**tool_input)` on line 669), we need to hook into the screenshot result. However, `_execute_tool` returns a generic `ToolResult` — we cannot annotate there because we don't know if mutating actions occurred in this turn.

Instead, add the annotation in the main tool result loop. After the tool result is obtained but before `tool_results.append`, for both sequential and parallel paths.

In the sequential path (around line 548-554), after `result, started_at, ended_at, duration_seconds = (self._execute_tool_with_metrics(...))`:

Check if this is a screenshot result in a mutating turn:

```python
                            if tn == 'mcp__browser__take_screenshot' and has_mutation:
                                self._annotate_screenshot_state(result, has_mutation=True)
```

This `has_mutation` variable doesn't exist at this point in the code. We need to compute it earlier. Currently `has_mutation` is computed at line 580 *after* the tool result loop. We need to lift the computation before the loop.

**Better approach**: Move the `has_mutation` computation before the tool result processing loop. At line 579, before `tool_names = {_block_name(tu) for tu in tool_uses}`, this is already after the tool_uses list is complete. But the tool results loop starts at line 404. We need `has_mutation` available during the loop.

The cleanest approach: compute `has_mutation` right after `tool_uses` is populated (after line 401 `if not tool_uses: break`), before the batching logic:

```python
                tool_names_set = {_block_name(tu) for tu in tool_uses}
                turn_has_mutation = bool(tool_names_set & _MUTATING_TOOLS)
```

Then use `turn_has_mutation` in both the sequential and parallel paths when processing screenshot results, and reuse `tool_names_set` for the existing `has_mutation` / `has_screenshot` check.

- [ ] **Step 5: Add the \_annotate_screenshot_state method**

Add this method to the Engine class (after `_data_flow_event`, around line 191):

```python
    def _annotate_screenshot_state(
        self, result: ToolResult, *, has_mutation: bool,
    ) -> None:
        """Append a factual state-observation note to a screenshot result.

        Compares the screenshot's content hash against the previous one.
        Only annotates when the current turn contained mutating actions.
        """
        if not has_mutation:
            return
        current_hash = _screenshot_content_hash(result)
        if current_hash and self._prev_screenshot_hash:
            if current_hash == self._prev_screenshot_hash:
                result.content += (
                    '\n[post-action observation: page visual state '
                    'unchanged since previous screenshot]'
                )
            else:
                result.content += (
                    '\n[post-action observation: page visual state '
                    'changed since previous screenshot]'
                )
        if current_hash:
            self._prev_screenshot_hash = current_hash
```

- [ ] **Step 6: Run hash tests to verify they pass**

Run: `cd /home/tutu/projects/saas/webqa-agent && uv run pytest tests/test_cc_mini_post_action.py -v`
Expected: ALL PASS (7 tests)

- [ ] **Step 7: Run all existing tests for regression**

Run: `cd /home/tutu/projects/saas/webqa-agent && uv run pytest tests/test_cc_mini_skills.py -q`
Expected: 74 passed

- [ ] **Step 8: Commit**

```bash
git add webqa-cc-mini/core/engine.py tests/test_cc_mini_post_action.py
git commit -m "feat(engine): add post-action screenshot hash comparison with state annotation"
```

______________________________________________________________________

### Task 3: Write failing tests for system prompt changes

**Files:**

- Modify: `tests/test_cc_mini_skills.py`

- [ ] **Step 1: Add prompt verification tests**

Add a new test class `TestSystemPromptVerification` after `TestSystemPromptSkillInjection` in `tests/test_cc_mini_skills.py`:

```python
class TestSystemPromptVerification:
    """Verify post-action verification methodology is present in prompt."""

    def test_step4_contains_outcome_comparison(self):
        prompt = build_web_agent_system_prompt('https://x', 'test')
        assert 'compare the actual outcome against what you expected' in prompt.lower() or \
               'compare the actual' in prompt.lower()

    def test_semantic_failure_coverage(self):
        prompt = build_web_agent_system_prompt('https://x', 'test')
        assert 'does not guarantee the intended effect' in prompt

    def test_anomalous_check_coverage(self):
        prompt = build_web_agent_system_prompt('https://x', 'test')
        assert 'anomalously fast' in prompt
```

- [ ] **Step 2: Run to verify tests fail**

Run: `cd /home/tutu/projects/saas/webqa-agent && uv run pytest tests/test_cc_mini_skills.py::TestSystemPromptVerification -v`
Expected: FAIL — prompt does not yet contain these phrases.

- [ ] **Step 3: Commit failing tests**

```bash
git add tests/test_cc_mini_skills.py
git commit -m "test(verification): add failing tests for prompt verification methodology"
```

______________________________________________________________________

### Task 4: Implement system prompt changes

**Files:**

- Modify: `webqa-cc-mini/core/context.py`

- [ ] **Step 1: Strengthen Step 4 (Verify)**

In `context.py`, find the Step 4 text (around line 75-76):

```python
        '4. **Verify** — confirm the expected effect with evidence before '
        'moving on.'
```

Replace with:

```python
        '4. **Verify** — compare the actual outcome against what you '
        'expected:\n'
        '  - State your expected outcome (what should change on the page).\n'
        '  - Check the post-action screenshot and snapshot against that '
        'expectation.\n'
        '  - If the outcome matches → continue.\n'
        '  - If the outcome diverges (no effect, wrong effect, partial '
        'effect, unexpected side effect) → treat as a failure and recover '
        'before continuing.\n'
```

- [ ] **Step 2: Add semantic failure sentence**

Find the "Errors are not stop signals" paragraph (around line 131-137). After the closing `'\n'` of that paragraph, add a new line:

```python
        '- **Successful tools can still fail.** A successful tool response '
        'does not guarantee the intended effect. If a click, fill, or other '
        'action returns success but the page state does not reflect the '
        'expected change, treat this as a failure — re-observe, diagnose, '
        'and recover just as you would for a tool error.\n'
```

- [ ] **Step 3: Add anomalous check coverage**

Find the "Risk-based final verification" text (around line 108-110). The current text contains:

```python
        'partially unverified requirement, call `verify`'
```

Insert `'anomalously fast check resolution (e.g. wait_for succeeding ' 'in under 1 second for content that should take time to generate), or '` before `'partially unverified requirement'`.

- [ ] **Step 4: Run prompt tests**

Run: `cd /home/tutu/projects/saas/webqa-agent && uv run pytest tests/test_cc_mini_skills.py::TestSystemPromptVerification -v`
Expected: ALL PASS (3 tests)

- [ ] **Step 5: Run all tests for regression**

Run: `cd /home/tutu/projects/saas/webqa-agent && uv run pytest tests/test_cc_mini_skills.py tests/test_cc_mini_post_action.py -q`
Expected: All pass, no regressions.

- [ ] **Step 6: Commit**

```bash
git add webqa-cc-mini/core/context.py tests/test_cc_mini_skills.py
git commit -m "feat(prompt): strengthen verification methodology for semantic failure detection"
```

______________________________________________________________________

### Task 5: Final verification

**Files:** (no changes, verification only)

- [ ] **Step 1: Run full test suite**

Run: `cd /home/tutu/projects/saas/webqa-agent && uv run pytest tests/test_cc_mini_skills.py tests/test_cc_mini_post_action.py -v`
Expected: All pass.

- [ ] **Step 2: Verify the annotation text appears in engine flow**

Run a quick Python check:

```bash
cd /home/tutu/projects/saas/webqa-agent && uv run python -c "
import sys; sys.path.insert(0, 'webqa-cc-mini')
from core.engine import _screenshot_content_hash
from core.tool import ToolResult

# Simulate two identical screenshots
blocks = [{'type': 'image', 'data': 'SAME_DATA', 'mimeType': 'image/jpeg'}]
r = ToolResult(content='Took a screenshot', content_blocks=blocks)
h = _screenshot_content_hash(r)
print(f'Hash: {h}')
print(f'Hash length: {len(h)}')
print('OK: hash function works')
"
```

- [ ] **Step 3: Verify prompt contains all new text**

```bash
cd /home/tutu/projects/saas/webqa-agent && uv run python -c "
import sys; sys.path.insert(0, 'webqa-cc-mini')
from core.context import build_web_agent_system_prompt
prompt = build_web_agent_system_prompt('https://example.com', 'test')
checks = [
    'compare the actual outcome against what you expected',
    'does not guarantee the intended effect',
    'anomalously fast',
]
for c in checks:
    found = c in prompt.lower() if c == checks[0] else c in prompt
    print(f'{'OK' if found else 'MISSING'}: {c}')
"
```

- [ ] **Step 4: Run pre-commit on all changed files**

```bash
pre-commit run --files webqa-cc-mini/core/engine.py webqa-cc-mini/core/context.py tests/test_cc_mini_post_action.py tests/test_cc_mini_skills.py
```

- [ ] **Step 5: Commit any formatting fixes**

```bash
git add -u && git commit -m "style: apply pre-commit formatting" || echo "nothing to commit"
```

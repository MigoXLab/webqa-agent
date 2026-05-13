# Post-Action Verification Enhancement Design Spec

**Date**: 2026-05-08
**Branch**: feature/recovery-skill
**Status**: Draft
**Prerequisite**: Recovery skill (implemented 2026-05-07)

## Problem

The cc-mini browser agent cannot detect *semantic failures* — actions
that execute successfully (tool returns no error) but do not produce
the intended effect. In a real-world test run, the agent issued
`click_at(x=403, y=519)` targeting a "regenerate" button. The tool
returned success, but the coordinates were 240px off — the click landed
on empty space. The agent continued, found pre-existing text that
satisfied its `wait_for` check in 0.03s, and reported the test as
passed. The recovery skill was never loaded.

This is not an isolated case. Research shows ~48% of browser agent
failures are "oblivious failures" where the agent does not realize it
failed (Agent-E self-detection rate: 52%). The root cause is
structural: detection logic that depends on the LLM's voluntary
judgment cannot catch failures the LLM doesn't perceive.

The recovery skill (implemented 2026-05-07) provides a comprehensive
OBSERVE → DIAGNOSE → RECOVER framework, but its trigger depends on the
agent recognizing a problem. This enhancement addresses the gap between
action execution and failure recognition.

## Goals

1. Give the agent objective evidence about action effects at the
   infrastructure level — without relying on LLM judgment for
   detection.
2. Strengthen the system prompt's verification methodology so the agent
   actively compares actual outcomes against intended outcomes after
   every mutating action.
3. Maintain generality — the design must handle all failure types (no
   effect, wrong effect, partial effect, unexpected side effect), not
   just "screenshot unchanged."
4. Avoid over-verification that would slow down successful runs.

## Non-Goals

- Auto-invoking the recovery skill from the engine (keeps engine
  decoupled from skill layer).
- Auto-invoking the verify tool after every action (too expensive: +1
  LLM call per mutating turn).
- Guaranteeing detection of all semantic failures (some require domain
  knowledge the infrastructure cannot have).

## Design Principles

1. **Facts, not directives** — the engine provides objective
   observations; the LLM decides what they mean.
2. **General, not signal-specific** — no if-then rules tied to a
   single failure mode.
3. **Cheap by default** — the per-turn overhead must be negligible
   (hash of an in-memory string, not an extra LLM/MCP call).
4. **Both screenshot paths** — cover LLM-initiated and auto-injected
   screenshots uniformly.

## Architecture

### Layer 1: Engine — Post-Action State Observation

**What**: After every screenshot captured in a turn that contained
mutating actions, compare the screenshot's content hash against the
previous screenshot's hash. Append the comparison result as a
human-readable text annotation on the screenshot's `tool_result`.

**Where**: Two screenshot paths in `engine.py` must be covered:

1. **LLM-initiated screenshots** — the LLM includes
   `take_screenshot` in its tool calls. These go through
   `_execute_tool` (line 653) → `_build_tool_result_block` (line 700).
2. **Auto-injected screenshots** — when mutating actions occur without
   a screenshot, the engine injects one (line 582-643).

**How**:

Add `self._prev_screenshot_hash: str | None = None` to
`Engine.__init__`.

Create a module-level helper:

```python
def _screenshot_content_hash(result: ToolResult) -> str | None:
    for blk in result.content_blocks or []:
        if isinstance(blk, dict) and blk.get('type') == 'image':
            data = blk.get('data', '')
            if data:
                return hashlib.md5(data.encode('ascii')).hexdigest()
    return None
```

At each screenshot capture point (both paths), after obtaining
`ss_result`:

```python
current_hash = _screenshot_content_hash(ss_result)
if current_hash and self._prev_screenshot_hash:
    if current_hash == self._prev_screenshot_hash:
        ss_result.content += (
            '\n[post-action observation: page visual state '
            'unchanged since previous screenshot]'
        )
    else:
        ss_result.content += (
            '\n[post-action observation: page visual state '
            'changed since previous screenshot]'
        )
if current_hash:
    self._prev_screenshot_hash = current_hash
```

**What this produces**: A factual annotation on the screenshot
tool_result text. The LLM sees it as part of the screenshot response —
the same way it sees "Took a screenshot" today, but with an additional
observation. The annotation is informational, not imperative.

**What this costs**: One MD5 hash of a base64 string already in memory.
No extra MCP or LLM calls. No new tool_use/tool_result blocks. No
changes to the message protocol.

**Edge cases**:

- First screenshot of the run: `_prev_screenshot_hash` is None, no
  annotation appended. ✅
- Turn with no mutating actions: no annotation needed (screenshot is
  purely observational). The annotation should only appear when the
  turn contained mutating tools. ✅
- Multiple screenshots in one turn: each updates the hash; only the
  latest comparison is meaningful. ✅
- Dynamic pages (animations, clocks): hash will always differ. The
  annotation says "changed" — which is correct and harmless. The LLM
  still needs to verify the *intended* effect, not just "any change." ✅
- Hidden-field fills: hash may be identical. The annotation says
  "unchanged" — which is factually correct. The LLM's verification
  methodology (Layer 2) teaches it to verify intended effect, not just
  visual change. ✅

### Layer 2: System Prompt — Verification Methodology Enhancement

Three targeted changes to `core/context.py`:

**Change A: Strengthen Step 4 (Verify)**

Current (line 75-76):

```
4. **Verify** — confirm the expected effect with evidence before
moving on.
```

Proposed:

```
4. **Verify** — after every mutating action, compare the actual
outcome against what you expected:
  - State your expected outcome (what should change on the page).
  - Check the post-action screenshot and snapshot against that
    expectation.
  - If the outcome matches expectation → continue.
  - If the outcome diverges (no effect, wrong effect, partial effect,
    unexpected side effect) → treat as a failure and recover before
    continuing.
```

**Change B: Extend "Errors are not stop signals" to cover semantic
failures**

Current (line 131-132):

```
When a tool fails or an element is not found, take a fresh snapshot...
```

Proposed (add after the existing paragraph):

```
A successful tool response does not guarantee the intended effect. If
a click, fill, or other action returns success but the page state does
not reflect the expected change, treat this as a failure — re-observe,
diagnose, and recover just as you would for a tool error.
```

**Change C: Extend "Risk-based final verification" to cover anomalous
verification results**

Current (line 108-110) lists triggers for `verify` / downgrade:

```
...after any timeout, tool error, ambiguous UI state, or partially
unverified requirement...
```

Proposed — add `anomalously fast check resolution` to the list:

```
...after any timeout, tool error, ambiguous UI state, anomalously fast
check resolution (e.g. wait_for succeeding in under 1 second for
content that should take time to generate), or partially unverified
requirement...
```

### Layer 3: Recovery Skill — No Changes

The recovery skill's `when_to_use` already covers semantic failures:
"when an action produces no visible effect, or page state diverges
from expectation." No changes needed.

## Token Budget

| Change                    | Added tokens              | Scope                      |
| ------------------------- | ------------------------- | -------------------------- |
| Engine annotation         | ~12 tokens per screenshot | Only in tool_result text   |
| Step 4 expansion          | ~60 tokens                | System prompt (every call) |
| Semantic failure sentence | ~35 tokens                | System prompt (every call) |
| Anomalous check sentence  | ~20 tokens                | System prompt (every call) |
| **Total system prompt**   | **~115 tokens**           |                            |

## Testing Strategy

### Unit Tests (engine hash comparison)

1. **Hash computed from screenshot content_blocks**: Create a
   `ToolResult` with image content_blocks, verify
   `_screenshot_content_hash` returns a stable MD5.
2. **Hash returns None for non-image results**: Verify empty/text-only
   results produce None.
3. **Annotation appended when hash matches**: Simulate two identical
   screenshots in a turn with mutating actions; verify "unchanged"
   annotation on the second result's content.
4. **Annotation appended when hash differs**: Simulate two different
   screenshots; verify "changed" annotation.
5. **No annotation on first screenshot**: Verify first screenshot of
   the run has no annotation.
6. **No annotation when no mutating action in turn**: Verify
   observation-only turns (pure snapshot + screenshot) get no
   annotation.

### Integration Tests (system prompt)

1. **Step 4 contains verification methodology**: Verify the prompt
   includes "compare the actual outcome against what you expected."
2. **Semantic failure coverage**: Verify the prompt includes "does not
   guarantee the intended effect."
3. **Anomalous check coverage**: Verify the prompt includes
   "anomalously fast check resolution."

### Regression

1. **Existing tests still pass**: All 74 skill tests + any other test
   suites remain green.

## Deliverables

1. Modified `core/engine.py` — screenshot hash comparison +
   annotation (both paths).
2. Modified `core/context.py` — three prompt text changes (A, B, C).
3. New/modified `tests/test_cc_mini_engine_state.py` — unit tests for
   hash comparison.
4. Modified `tests/test_cc_mini_skills.py` — integration tests for
   prompt changes.

## Future Considerations

- **DOM-level change detection**: When the DOM perception skill
  (task #2) is implemented, a DOM diff could complement the screenshot
  hash — catching structural changes invisible to visual comparison
  and avoiding false positives on pages with CSS animations.
- **Conditional verify invocation**: If the screenshot hash is
  unchanged AND the turn contained mutating actions, the engine could
  optionally auto-invoke the `verify` tool. This is more expensive but
  more accurate. Gated behind a configuration flag.
- **MCP tool enhancement**: If `click_at` could report whether it hit
  a real interactive element (vs empty space), the false-success
  problem would be solved at the source.

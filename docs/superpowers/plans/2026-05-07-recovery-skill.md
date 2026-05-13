# Recovery Skill Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Create a recovery skill for the cc-mini browser agent that provides structured error recovery via OBSERVE → DIAGNOSE → RECOVER loop with escalation.

**Architecture:** Pure skill-layer implementation (zero engine changes). Recovery skill lives at `skills/recovery/` with SKILL.md + two references. Plan skill's Error Handling section simplified to cross-reference recovery. Existing `test_cc_mini_skills.py` extended with recovery-specific integration tests.

**Tech Stack:** Markdown (skill documents), Python/pytest (integration tests)

**Spec:** `docs/superpowers/specs/2026-05-07-recovery-skill-design.md`

______________________________________________________________________

## File Map

| Action | Path                                                              | Responsibility                             |
| ------ | ----------------------------------------------------------------- | ------------------------------------------ |
| Create | `webqa-cc-mini/skills/recovery/SKILL.md`                          | Core recovery decision framework           |
| Create | `webqa-cc-mini/skills/recovery/references/error-taxonomy.md`      | Enhanced error classification              |
| Create | `webqa-cc-mini/skills/recovery/references/recovery-strategies.md` | Recovery playbooks with tool examples      |
| Modify | `webqa-cc-mini/skills/plan/SKILL.md:98-109`                       | Simplify Error Handling to cross-reference |
| Delete | `webqa-cc-mini/skills/plan/references/error-taxonomy.md`          | Migrated to recovery skill                 |
| Modify | `tests/test_cc_mini_skills.py`                                    | Add recovery skill integration tests       |

______________________________________________________________________

### Task 1: Write recovery skill integration tests

**Files:**

- Modify: `tests/test_cc_mini_skills.py`

Tests first. These verify the skill infrastructure integrates correctly
with the new recovery skill files (which don't exist yet, so tests will
fail).

- [ ] **Step 1: Write failing test class for recovery skill discovery**

Add this class after `TestPlanSkillIntegration` (around line 477):

```python
class TestRecoverySkillIntegration:
    @pytest.fixture()
    def reg(self):
        if not _REAL_SKILLS_DIR.is_dir():
            pytest.skip('webqa-cc-mini/skills/ not found')
        r = SkillRegistry(_REAL_SKILLS_DIR)
        r.discover()
        return r

    def test_recovery_skill_discovered(self, reg):
        names = [m.name for m in reg.list_metadata()]
        assert 'recovery' in names

    def test_recovery_skill_has_when_to_use(self, reg):
        meta = next(m for m in reg.list_metadata() if m.name == 'recovery')
        assert meta.when_to_use
        assert 'error' in meta.when_to_use.lower()

    def test_recovery_skill_references(self, reg):
        refs = reg.list_references('recovery')
        assert 'error-taxonomy' in refs
        assert 'recovery-strategies' in refs

    def test_recovery_skill_body_contains_key_sections(self, reg):
        body = reg.load_full_content('recovery')
        for section in (
            'When to Use',
            'OBSERVE',
            'DIAGNOSE',
            'RECOVER',
            'Loop Control',
        ):
            assert section in body, f'missing section: {section}'

    def test_recovery_error_taxonomy_loadable(self, reg):
        content = reg.load_reference('recovery', 'error-taxonomy')
        assert 'ELEMENT_NOT_FOUND' in content
        assert 'ACTION_INEFFECTIVE' in content
        assert 'PAGE_CRASHED' in content

    def test_recovery_strategies_loadable(self, reg):
        content = reg.load_reference('recovery', 'recovery-strategies')
        assert 'Re-observe' in content
        assert 'evaluate_script' in content
        assert 'Escalation' in content or 'escalat' in content.lower()
```

- [ ] **Step 2: Write failing test for plan skill modification**

Add these tests to the existing `TestPlanSkillIntegration` class:

```python
    def test_plan_error_handling_references_recovery(self, reg):
        body = reg.load_full_content('plan')
        assert 'load_skill(skill_name="recovery")' in body

    def test_plan_no_longer_has_error_taxonomy_reference(self, reg):
        refs = reg.list_references('plan')
        assert 'error-taxonomy' not in refs
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `cd /home/tutu/projects/saas/webqa-agent && uv run pytest tests/test_cc_mini_skills.py::TestRecoverySkillIntegration -v`
Expected: FAIL — recovery skill directory does not exist yet.

Run: `cd /home/tutu/projects/saas/webqa-agent && uv run pytest tests/test_cc_mini_skills.py::TestPlanSkillIntegration::test_plan_error_handling_references_recovery -v`
Expected: FAIL — plan SKILL.md has not been modified yet.

- [ ] **Step 4: Commit failing tests**

```bash
git add tests/test_cc_mini_skills.py
git commit -m "test(recovery): add failing integration tests for recovery skill"
```

______________________________________________________________________

### Task 2: Create recovery SKILL.md

**Files:**

- Create: `webqa-cc-mini/skills/recovery/SKILL.md`

- [ ] **Step 1: Create the recovery skill directory**

```bash
mkdir -p webqa-cc-mini/skills/recovery/references
```

- [ ] **Step 2: Write SKILL.md**

Create `webqa-cc-mini/skills/recovery/SKILL.md` with this content:

```markdown
---
name: recovery
description: Structured error recovery for failed or ineffective browser actions.
when_to_use: When a tool returns an error, an action produces no visible effect, or page state diverges from expectation.
---

# Recovery Skill

Structured recovery for browser automation failures. Covers execution
errors, semantic failures, state divergence, tool limitations, and
environmental blockers.

## When to Use

Load this skill when any of these occur:

- A tool returns an error (`is_error` in tool result).
- A post-action screenshot shows no change or an unexpected change.
- A verification step (snapshot / verify) contradicts the expected state.
- An action succeeded but the effect is wrong (filled wrong field,
  clicked wrong element, upload didn't trigger, text truncated).
- An unexpected element blocks progress (modal, banner, CAPTCHA,
  cookie consent).

## Recovery Loop

Follow three phases in order. Do not skip OBSERVE.

### Step 1 — OBSERVE

Re-perceive the actual page state before making any recovery decision.

Batch these read-only tools in a single turn (the engine runs them
concurrently):

- `take_snapshot` — current DOM / accessibility tree.
- `take_screenshot` — current visual state.
- `list_console_messages` — JS errors that may explain the failure.
- `list_network_requests` — failed API calls or unexpected redirects.

**Before / after comparison:** Compare the current state against what
the page looked like *before* the failed action. Ask:

1. What changed? (anything at all — URL, DOM, visual layout)
2. What *should* have changed but didn't?
3. Are there new elements that weren't there before (modals, errors)?

### Step 2 — DIAGNOSE

Classify the failure and assess progress.

**Error classification** — load the `error-taxonomy` reference for the
full list:
`load_skill(skill_name="recovery", reference="error-taxonomy")`

Key questions:
- Is this an **execution error** (tool reported failure) or a
  **semantic error** (tool succeeded but wrong effect)?
- Is the root cause a **tool limitation**, a **wrong selector**, a
  **page state change**, or an **environmental blocker**?

**Progress assessment** — did the action make *any* progress toward the
goal?

- **Partial progress** (e.g. 3 of 5 fields filled): preserve what
  worked, recover only the failed part.
- **Zero progress** (nothing changed): the approach itself may be wrong;
  escalate sooner.
- **Negative progress** (broke something): undo if possible (GoBack),
  then re-observe.

### Step 3 — RECOVER

Load the `recovery-strategies` reference for concrete playbooks:
`load_skill(skill_name="recovery", reference="recovery-strategies")`

**Escalation ladder** — try in order, move to the next level when the
current one fails:

1. **Retry with modification** — alternative selector, corrected input,
   adjusted timing.
2. **Alternative approach** — different tool (e.g. `evaluate_script`
   instead of MCP `fill`), different interaction pattern.
3. **Replan** — fundamentally different path to the same goal (e.g.
   direct URL navigation when menu path is broken).
4. **Skip and record** — preserve partial progress, log what failed and
   why, move to the next planned step.

After every recovery action, return to **OBSERVE** to verify the fix
worked before continuing the plan.

## Loop Control

- **Per-step limit:** max 2 recovery attempts on the same step before
  escalating to the next level.
- **Cross-step pattern:** same error pattern 3+ times across different
  steps → treat as systemic; skip and record.
- **Replan depth:** max 1 replan per original step. If the replanned
  approach also fails, skip.
- **Fatal errors:** never attempt recovery. Report and stop. Fatal
  types: PAGE_CRASHED, SESSION_EXPIRED, PERMISSION_DENIED,
  UNSUPPORTED_PAGE.
- **After recovery:** always continue the plan. One failed step does
  not end the entire task.

## Available References

Load on demand: `load_skill(skill_name="recovery", reference="<name>")`

- `error-taxonomy` — 9 error categories with identification traits,
  causes, and recovery guidance
- `recovery-strategies` — concrete recovery playbooks with tool
  examples and escalation patterns
```

- [ ] **Step 3: Run discovery test to verify SKILL.md is parseable**

Run: `cd /home/tutu/projects/saas/webqa-agent && uv run pytest tests/test_cc_mini_skills.py::TestRecoverySkillIntegration::test_recovery_skill_discovered -v`
Expected: PASS

Run: `cd /home/tutu/projects/saas/webqa-agent && uv run pytest tests/test_cc_mini_skills.py::TestRecoverySkillIntegration::test_recovery_skill_has_when_to_use -v`
Expected: PASS

Run: `cd /home/tutu/projects/saas/webqa-agent && uv run pytest tests/test_cc_mini_skills.py::TestRecoverySkillIntegration::test_recovery_skill_body_contains_key_sections -v`
Expected: PASS

- [ ] **Step 4: Commit**

```bash
git add webqa-cc-mini/skills/recovery/SKILL.md
git commit -m "feat(recovery): add recovery skill SKILL.md with OBSERVE/DIAGNOSE/RECOVER framework"
```

______________________________________________________________________

### Task 3: Create error-taxonomy reference

**Files:**

- Create: `webqa-cc-mini/skills/recovery/references/error-taxonomy.md`

- [ ] **Step 1: Write error-taxonomy.md**

Create `webqa-cc-mini/skills/recovery/references/error-taxonomy.md`:

```markdown
# Error Taxonomy

Classify failures to decide what recovery strategy to use. Every
failure falls into one of these categories.

## Recoverable Errors

### ELEMENT_NOT_FOUND

The target element is missing from the current DOM.

- **Cause:** Page hasn't loaded fully, element is inside a collapsed
  section, selector is wrong, dynamic content shifted positions,
  element rendered as a different tag than expected.
- **Identification:** Tool error message mentions missing element,
  selector, or uid. Snapshot confirms the element is absent.
- **Recovery:**
  1. Re-observe: fresh `take_snapshot` + `take_screenshot`.
  2. Try alternative selector: match by visible text, ARIA role,
     nearby landmark, or positional context.
  3. Add `wait_for` if the element may still be loading.
  4. If element truly doesn't exist after 2 attempts, skip the step.

### TIMEOUT

An action or wait exceeded the time limit.

- **Cause:** Slow network, heavy page, async content not yet rendered,
  server processing delay.
- **Identification:** Tool error message mentions timeout or time
  limit exceeded.
- **Recovery:**
  1. Retry once after a brief pause.
  2. Re-observe to see what actually loaded.
  3. If the target content partially loaded, adapt the approach to
     work with what's available.
  4. If it times out again on retry, skip and record.

### NAVIGATION_FAILED

The page didn't load or returned an error.

- **Cause:** Broken link, server error (4xx/5xx), redirect loop,
  network failure, URL changed.
- **Identification:** Blank page, error page, HTTP error status in
  `list_network_requests`, URL doesn't match expected target.
- **Recovery:**
  1. Check `list_network_requests` for the failing request and status.
  2. Try navigating to a parent URL (strip path segments).
  3. Use browser back to return to the last known-good page.
  4. If the page is genuinely down, skip and move to the next step.

### VALIDATION_ERROR

A form rejected the input (client-side or server-side).

- **Cause:** Invalid data format, required field missing, constraint
  violation, unexpected field requirements.
- **Identification:** Error message visible in DOM after form
  submission. Form fields highlighted. Status didn't change to success.
- **Recovery:**
  1. Read the error message from the snapshot or screenshot.
  2. Correct the input based on the error message.
  3. Resubmit the form.
  4. If the validation rule is unclear, try a different valid value.

### ACTION_INEFFECTIVE

The action executed without error but did not produce the expected
effect. This is the most subtle failure type — the tool reports success,
but the outcome is wrong.

- **Cause:** Wrong element targeted (small icon misidentified, dynamic
  ID changed), tool limitation (fill truncated long text, special
  characters dropped, upload didn't trigger file chooser), page
  JavaScript intercepted the event, element was visually overlapped
  by another element, action was applied to a different frame/context.
- **Identification:** Post-action screenshot shows no change or wrong
  change. Before/after state comparison reveals the intended effect
  didn't happen. The tool returned success but the page state
  contradicts the expected outcome.
- **Recovery:**
  1. Re-observe to confirm the actual state.
  2. Assess: was the right element targeted? Compare the element's
     visible text/position against what was intended.
  3. Try alternative approach: use `evaluate_script` for direct DOM
     manipulation (set input values, dispatch events, trigger clicks).
  4. If a custom tool is available for this operation, prefer it over
     evaluate_script.
  5. Try a fundamentally different interaction path (replan) if local
     fixes don't work.

## Fatal Errors

These cannot be recovered within the current run. Report and stop.

### PAGE_CRASHED

The browser tab crashed or became unresponsive.

- **Identification:** Tool calls fail with crash-related errors, no
  response from browser, page load hangs indefinitely.
- **Action:** Report the crash and the last known state. Include the
  URL and the step that triggered it.

### SESSION_EXPIRED

Authentication was lost.

- **Identification:** Redirected to login page, 401/403 HTTP response,
  session cookie cleared, "session expired" message visible.
- **Action:** Report which step lost the session and what the redirect
  target was. Do not attempt to re-authenticate.

### PERMISSION_DENIED

The page or feature is access-restricted.

- **Identification:** 403 response, "access denied" or "forbidden"
  message, feature grayed out with permission tooltip.
- **Action:** Report the permission error and the URL or feature that
  was blocked.

### UNSUPPORTED_PAGE

The page is not standard HTML content.

- **Identification:** PDF viewer, browser extension page, about: URL,
  file download prompt, embedded application (Flash, Java applet).
- **Action:** Report the page type and skip.

## Decision Rule

```

Error occurs
→ Is it fatal? (PAGE_CRASHED / SESSION_EXPIRED / PERMISSION_DENIED / UNSUPPORTED_PAGE)
→ YES: Report and stop.
→ NO: Enter recovery loop.
→ Recovery attempt 1: Try the first applicable strategy.
→ Success: Continue the plan.
→ Fail: Recovery attempt 2 (escalate to next strategy).
→ Success: Continue the plan.
→ Fail: Skip this step, record what failed and why.
→ Same error pattern 3+ times across different steps?
→ YES: Treat as systemic. Note in findings, skip affected steps.

```

If a *different* error occurs during recovery, classify it
independently — do not conflate error types.
```

- [ ] **Step 2: Run reference load test**

Run: `cd /home/tutu/projects/saas/webqa-agent && uv run pytest tests/test_cc_mini_skills.py::TestRecoverySkillIntegration::test_recovery_error_taxonomy_loadable -v`
Expected: PASS

- [ ] **Step 3: Commit**

```bash
git add webqa-cc-mini/skills/recovery/references/error-taxonomy.md
git commit -m "feat(recovery): add error-taxonomy reference with 9 error categories"
```

______________________________________________________________________

### Task 4: Create recovery-strategies reference

**Files:**

- Create: `webqa-cc-mini/skills/recovery/references/recovery-strategies.md`

- [ ] **Step 1: Write recovery-strategies.md**

Create `webqa-cc-mini/skills/recovery/references/recovery-strategies.md`:

```markdown
# Recovery Strategies

Concrete playbooks for each recovery approach. Use the escalation
ladder: try strategies in order, move to the next when the current one
fails.

## Escalation Ladder

```

Level 1: Retry with modification
↓ (failed)
Level 2: Alternative approach
↓ (failed)
Level 3: Replan
↓ (failed)
Level 4: Skip and record

```

Always start with **Re-observe** before attempting any strategy.

---

## Strategy 0: Re-observe (mandatory first step)

**When:** After any failure, before deciding what to do.

**Tools:** Batch in one turn (concurrent read-only):
- `take_snapshot` — DOM / accessibility tree
- `take_screenshot` — visual state

**Optional additions** (include when relevant):
- `list_console_messages` — JS errors that explain the failure
- `list_network_requests` — failed API calls, unexpected redirects

**Before / after comparison checklist:**
1. URL: same or different?
2. Page title / heading: changed?
3. Target element: still present? Same position?
4. New elements: modals, error banners, overlays?
5. Network: any failed requests since the action?
6. Console: any new errors?

---

## Strategy 1: Retry with modification

**When:** ELEMENT_NOT_FOUND, TIMEOUT, VALIDATION_ERROR.

### Alternative selectors (ELEMENT_NOT_FOUND)

If the original selector/uid failed, try identifying the element by:
1. **Visible text** — look for the element's label or text content in
   the snapshot.
2. **ARIA role** — search for role="button", role="link", etc.
3. **Nearby landmark** — find a heading or label near the target, then
   locate the adjacent interactive element.
4. **Positional context** — "the third button in the form" or "the
   input below the 'Email' label."

```

Example:
Failed: click(uid="btn_47")
Observe: take_snapshot → find the "Submit" button text
Retry: click(uid="<new-uid-from-snapshot>")

```

### Adjusted timing (TIMEOUT)

If the element may still be loading:

```

Example:
Failed: click(uid="search-results-item-1") → timeout
Wait: wait_for(selector="\[data-testid='search-results'\]", timeout=10000)
Retry: take_snapshot → find the element → click

```

### Corrected input (VALIDATION_ERROR)

Read the error message, then fix the value:

```

Example:
Failed: fill(uid="email-input", value="not-an-email")
Observe: take_snapshot → error says "Please enter a valid email"
Retry: fill(uid="email-input", value="test@example.com")

```

---

## Strategy 2: Alternative approach

**When:** ACTION_INEFFECTIVE, or retry-with-modification failed.

### DOM direct manipulation via evaluate_script

When MCP interaction tools produce wrong results, bypass them with
direct JavaScript:

**Fill a text input:**
```

evaluate_script({
code: `const el = document.querySelector('textarea#content');     const nativeSetter = Object.getOwnPropertyDescriptor(       window.HTMLTextAreaElement.prototype, 'value'     ).set;     nativeSetter.call(el, 'your long text with special chars: <>&"');     el.dispatchEvent(new Event('input', { bubbles: true }));     el.dispatchEvent(new Event('change', { bubbles: true }));`
})

```

**Click an element:**
```

evaluate_script({
code: "document.querySelector('button.submit-btn').click()"
})

```

**Check/uncheck a checkbox:**
```

evaluate_script({
code: `const cb = document.querySelector('input[type=checkbox]#agree');     cb.checked = true;     cb.dispatchEvent(new Event('change', { bubbles: true }));`
})

```

**Select a dropdown option:**
```

evaluate_script({
code: `const sel = document.querySelector('select#country');     sel.value = 'US';     sel.dispatchEvent(new Event('change', { bubbles: true }));`
})

```

**Always verify after DOM manipulation:**
```

take_screenshot  → confirm the change is visually reflected
take_snapshot    → confirm the DOM state matches expectation

```

### Switch interaction pattern

If clicking doesn't work, try keyboard:
```

Example:
Failed: click(uid="submit-button") → no effect
Alternative: press_key(key="Enter") on focused form element

```

If hover is needed before click (dropdown menus):
```

Example:
Failed: click(uid="dropdown-item") → element not visible
Alternative: hover(uid="dropdown-trigger") → wait → click(uid="dropdown-item")

```

---

## Strategy 3: Replan

**When:** The current approach is fundamentally blocked (not just a
selector issue). Local fixes (retry, alternative tool) have failed.

**Constraint:** Max 1 replan per original step. If the replanned
approach also fails, proceed to skip.

**Common replan patterns:**

**Direct URL navigation** when menu/link path is broken:
```

Example:
Original plan: click "Settings" in sidebar → click "Profile"
Blocked: sidebar menu not rendering
Replan: navigate_page(url="<target-site>/settings/profile")

```

**Alternative entry point** when a form is unreliable:
```

Example:
Original plan: fill search box → submit → click result
Blocked: search box fill produces truncated text
Replan: navigate_page(url="<target-site>/search?q=query")

```

**Different feature path** to verify the same behavior:
```

Example:
Original plan: test delete via UI button
Blocked: delete button not clickable (overlapped by banner)
Replan: dismiss banner first → retry delete button

```

---

## Strategy 4: Handle environmental blockers

**When:** An unexpected overlay, modal, or banner blocks interaction
with the target element.

**Identification:** Screenshot shows an overlay. Clicks land on the
blocker instead of the target. Snapshot shows the blocker element
above the target in the DOM.

**Dismissal patterns:**

**Cookie consent / privacy banner:**
```

take_snapshot → find Accept/OK/Agree button → click it
or: evaluate_script({ code: "document.querySelector('.cookie-banner .accept')?.click()" })
or: press_key(key="Escape")

```

**Modal dialog:**
```

take_snapshot → find close button (X, "Close", "Dismiss") → click it
or: press_key(key="Escape")
or: click outside the modal (click_at coordinates beyond the modal)

```

**Chat widget / floating button:**
```

evaluate_script({
code: "document.querySelector('.chat-widget, .intercom-frame')?.remove()"
})

```

After dismissing, re-observe and retry the original action.

---

## Strategy 5: Skip and record

**When:** All recovery attempts exhausted (2 retries, alternative
approach, and replan all failed).

**What to record** (include in your narration and final report):
- What step was being attempted.
- What errors occurred (with error type from taxonomy).
- What recovery strategies were tried.
- What partial progress was achieved (if any).
- Classification: [warning] if partially done, [failed] if not done.

**Then:** Move to the next planned step without delay. Do not attempt
the skipped step again later.

---

## Strategy 6: Abort with report

**When:** Fatal error only (PAGE_CRASHED, SESSION_EXPIRED,
PERMISSION_DENIED, UNSUPPORTED_PAGE).

**Steps:**
1. Capture final state: `take_screenshot` if possible.
2. Report: error type, last known URL, steps completed so far, steps
   remaining.
3. Mark all uncompleted steps as [failed] with the fatal error as
   cause.
4. Do not attempt further recovery or step execution.
```

- [ ] **Step 2: Run reference load test**

Run: `cd /home/tutu/projects/saas/webqa-agent && uv run pytest tests/test_cc_mini_skills.py::TestRecoverySkillIntegration::test_recovery_strategies_loadable -v`
Expected: PASS

- [ ] **Step 3: Run all recovery skill tests**

Run: `cd /home/tutu/projects/saas/webqa-agent && uv run pytest tests/test_cc_mini_skills.py::TestRecoverySkillIntegration -v`
Expected: ALL PASS (6 tests)

- [ ] **Step 4: Commit**

```bash
git add webqa-cc-mini/skills/recovery/references/recovery-strategies.md
git commit -m "feat(recovery): add recovery-strategies reference with escalation playbooks"
```

______________________________________________________________________

### Task 5: Modify plan skill and remove old error-taxonomy

**Files:**

- Modify: `webqa-cc-mini/skills/plan/SKILL.md:98-109`

- Delete: `webqa-cc-mini/skills/plan/references/error-taxonomy.md`

- [ ] **Step 1: Modify plan SKILL.md Error Handling section**

Replace lines 98-109 in `webqa-cc-mini/skills/plan/SKILL.md`:

Old (current content):

```markdown
## Error Handling

When a tool returns an error, classify it:

- **Recoverable** — element not found (try alternative selector),
  timeout (wait and retry), validation error (correct input).
  Adapt and continue.
- **Fatal** — page crashed, session expired, permission denied,
  unsupported page type. Report the error and stop.

Load `error-taxonomy` reference for the full classification:
`load_skill(skill_name="plan", reference="error-taxonomy")`
```

New:

```markdown
## Error Handling

When a tool returns an error or an action produces unexpected results,
load the `recovery` skill for structured guidance:
`load_skill(skill_name="recovery")`

The recovery skill provides error classification, diagnosis with
progress assessment, and concrete recovery strategies with escalation.
```

- [ ] **Step 2: Delete old error-taxonomy reference**

```bash
rm webqa-cc-mini/skills/plan/references/error-taxonomy.md
```

- [ ] **Step 3: Also update the "Available References" section**

The plan SKILL.md ends with (lines 112-116):

```markdown
## Available References

Load on demand: `load_skill(skill_name="plan", reference="<name>")`

- `error-taxonomy` — 7 error categories, recovery vs abort guidance
- `verification-patterns` — concrete verification examples with MCP tools
```

Replace with:

```markdown
## Available References

Load on demand: `load_skill(skill_name="plan", reference="<name>")`

- `verification-patterns` — concrete verification examples with MCP tools
```

- [ ] **Step 4: Run plan modification tests**

Run: `cd /home/tutu/projects/saas/webqa-agent && uv run pytest tests/test_cc_mini_skills.py::TestPlanSkillIntegration -v`
Expected: ALL PASS (including the two new tests: `test_plan_error_handling_references_recovery` and `test_plan_no_longer_has_error_taxonomy_reference`)

- [ ] **Step 5: Commit**

```bash
git add webqa-cc-mini/skills/plan/SKILL.md
git rm webqa-cc-mini/skills/plan/references/error-taxonomy.md
git commit -m "refactor(plan): simplify error handling to reference recovery skill"
```

______________________________________________________________________

### Task 6: Run full test suite and final verification

**Files:** (no changes, verification only)

- [ ] **Step 1: Run all skill tests**

Run: `cd /home/tutu/projects/saas/webqa-agent && uv run pytest tests/test_cc_mini_skills.py -v`
Expected: ALL PASS

- [ ] **Step 2: Run full project test suite**

Run: `cd /home/tutu/projects/saas/webqa-agent && uv run pytest tests/ -v --tb=short`
Expected: No regressions. All previously passing tests still pass.

- [ ] **Step 3: Verify skill discovery with all skills**

Run this quick Python check to verify the real skills directory:

```bash
cd /home/tutu/projects/saas/webqa-agent && uv run python -c "
import sys; sys.path.insert(0, 'webqa-cc-mini')
from pathlib import Path
from core.skill_registry import SkillRegistry
reg = SkillRegistry(Path('webqa-cc-mini/skills'))
reg.discover()
for m in reg.list_metadata():
    refs = reg.list_references(m.name)
    print(f'{m.name}: {m.description} (refs: {refs})')
"
```

Expected output:

```
plan: Decompose a task into steps with verification checkpoints. (refs: ['verification-patterns'])
recovery: Structured error recovery for failed or ineffective browser actions. (refs: ['error-taxonomy', 'recovery-strategies'])
ui-audit: ... (refs: [...])
```

Verify:

- `plan` has only `verification-patterns` reference (no `error-taxonomy`).

- `recovery` has both `error-taxonomy` and `recovery-strategies` references.

- Both `plan` and `recovery` are discovered.

- [ ] **Step 4: Final commit (if any pre-commit formatting was applied)**

If pre-commit hooks modified any files, stage and commit:

```bash
git add -u
git commit -m "style: apply formatting from pre-commit hooks"
```

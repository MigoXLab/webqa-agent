# Recovery Skill Design Spec

**Date**: 2026-05-07
**Branch**: feature/recovery-skill
**Status**: Draft

## Problem

Browser automation agents routinely encounter failures that go beyond
simple tool errors. These failures fall on a spectrum:

- **Execution failures**: a tool returns an explicit error (element not
  found, timeout, navigation error).
- **Semantic failures**: a tool succeeds but the outcome diverges from
  intent — clicking the wrong element, filling a truncated value,
  triggering an unrelated action.
- **State divergence**: the agent's mental model of the page no longer
  matches reality — an unexpected modal appeared, a redirect changed
  the URL, dynamic content shifted element positions.
- **Tool limitations**: the automation layer itself cannot perform a
  required operation (e.g. MCP fill cannot handle special characters,
  snapshot misidentifies an icon).
- **Environmental surprises**: cookie consent banners, CAPTCHA walls,
  session timeouts, A/B test variations.

Current error handling in cc-mini is a paragraph in the system prompt
("Errors are not stop signals") and a basic error taxonomy reference
in the plan skill. There is no structured recovery decision framework,
no before/after state comparison, and no escalation path beyond "retry
3 times then skip."

Research into modern browser agent architectures (BacktrackAgent,
Agent-E, BrowserGym, WebVoyager) reveals common recovery patterns that
this skill codifies:

- **Observe-then-act loops** (all major agents) — re-perceive before
  re-acting.
- **Progress assessment** (BacktrackAgent Judger) — evaluate whether an
  action moved toward the goal, not just whether it "succeeded."
- **Before/after state diff** (Agent-E) — compare page state before and
  after an action to detect semantic failures.
- **Bounded recovery with escalation** (BrowserGym POMDP) — retry with
  constraints, escalate to replan when local fixes fail.
- **Loop detection** (WebVoyager) — hard limits and pattern matching to
  prevent infinite recovery.

## Goals

1. Provide a general-purpose recovery framework applicable to *any*
   browser automation failure — not tied to specific tools or MCP
   limitations.
2. Cover the full failure spectrum: execution errors, semantic failures,
   state divergence, tool limitations, and environmental surprises.
3. Introduce before/after state comparison and progress assessment as
   first-class concepts in the recovery loop.
4. Define a tool-agnostic recovery escalation path: alternative
   approach → direct DOM manipulation → replan → skip.
5. Integrate cleanly with existing skill architecture (zero engine
   changes, progressive disclosure via `load_skill`).
6. Support incremental enhancement: new perception tools, custom action
   tools, and domain-specific recovery strategies can be plugged in by
   adding references.

## Non-Goals

- Modifying `engine.py` or the core ReAct loop.
- Implementing custom fill/upload tools (scope of task #3).
- Implementing DOM perception skill (scope of task #2).
- Handling LLM API errors (already managed by engine retry logic).

## Design Principles

Drawn from the research above:

1. **Observe before acting** — never retry blindly. Every recovery
   attempt starts with fresh observation.
2. **Assess progress, not just success** — a partial success (3 of 5
   items filled) is different from a total failure. Recovery should
   preserve partial progress.
3. **Escalate, don't loop** — if the same approach fails twice, try a
   fundamentally different approach (alternative selector → JS
   manipulation → replan), not the same thing again.
4. **Bound everything** — hard limits on retry count, recovery depth,
   and time. No infinite loops.
5. **Preserve context** — when skipping a step, record *what* failed,
   *why*, and *what was tried*. This feeds the final report quality.

## Architecture

### Trigger Model

Agent-initiated via `load_skill(skill_name="recovery")`. The agent
loads the skill when it encounters any situation where the current
approach is not working:

- A tool returning `is_error=True`.
- An action that produced no visible change (post-action screenshot
  matches pre-action state).
- Page state that contradicts the plan's expected outcome.
- A verification step (snapshot/verify) that fails.
- An unexpected page element blocking progress (modal, banner, CAPTCHA).

The system prompt's "Available Skills" section injects the skill's
one-line description + `when_to_use` trigger guidance. The plan skill's
Error Handling section cross-references recovery for detailed guidance.

### File Structure

```
skills/
├── plan/
│   ├── SKILL.md                   # Error Handling section simplified
│   └── references/
│       └── verification-patterns.md
└── recovery/
    ├── SKILL.md                   # Core recovery decision framework
    └── references/
        ├── error-taxonomy.md      # Error classification with traits
        └── recovery-strategies.md # Concrete recovery playbooks
```

`plan/references/error-taxonomy.md` is **removed** (migrated to
recovery with enhancements). Plan SKILL.md Error Handling section
becomes a cross-reference to the recovery skill.

### SKILL.md Content Design

**Frontmatter:**

```yaml
---
name: recovery
description: Structured error recovery for failed or ineffective browser actions.
when_to_use: When a tool returns an error, an action produces no visible effect, or page state diverges from expectation.
---
```

**Body** (~1000 tokens target):

1. **When to Use** — concrete trigger conditions covering the full
   failure spectrum (not just tool errors).

2. **Recovery Loop: OBSERVE → DIAGNOSE → RECOVER**

   **OBSERVE** — Re-perceive actual page state:

   - Batch: `take_snapshot` + `take_screenshot` in one turn (concurrent
     read-only tools).
   - Compare current state against pre-action state (before/after diff):
     what changed? What didn't change that should have?
   - Check `list_console_messages` for JS errors that explain the
     failure.
   - Check `list_network_requests` for failed API calls.
   - Goal: build ground truth before deciding next move.

   **DIAGNOSE** — Classify and assess:

   - Classify the failure into one of the error types from
     `error-taxonomy` reference.
   - **Progress assessment**: did the action make *any* progress toward
     the goal? Partial progress (3/5 items done) means preserve what
     worked and recover only the failed part. Zero progress means the
     approach itself may be wrong.
   - **Root cause**: Is this an execution error (tool failed), semantic
     error (wrong effect), state divergence (page changed unexpectedly),
     or tool limitation (tool cannot do this)?

   **RECOVER** — Execute the appropriate strategy from
   `recovery-strategies` reference:

   - **Escalation ladder** (try in order, move to next on failure):
     1. Retry with modification (alt selector, corrected input).
     2. Alternative approach (different tool, JS direct manipulation).
     3. Replan (fundamentally different path to the same goal).
     4. Skip and record (preserve partial progress, log failure).
   - After recovery action: re-observe to verify the fix worked.

3. **Loop Control** — preventing infinite recovery:

   - Same step: max 2 recovery attempts before escalating.
   - Same error pattern 3+ times across steps: treat as systemic,
     skip and record.
   - Recovery depth: max 1 replan per original step.
   - Fatal errors: no recovery (page crash, session expired, permission
     denied, unsupported page).
   - Always: after recovery, continue with the plan. Never stop the
     entire task because of one failed step.

4. **Available References**:

   - `error-taxonomy` — error categories with identification traits and
     recovery guidance.
   - `recovery-strategies` — concrete recovery playbooks with tool
     examples and escalation patterns.

### Reference: error-taxonomy.md

Enhanced from the original plan/references/error-taxonomy.md. Now
covers the full failure spectrum.

**Recoverable Errors** (5 types):

| Error              | Identification                                                                                                                  | Escalation Path                                       |
| ------------------ | ------------------------------------------------------------------------------------------------------------------------------- | ----------------------------------------------------- |
| ELEMENT_NOT_FOUND  | Tool error mentions missing element/selector                                                                                    | Alt selector → snapshot re-check → JS query → skip    |
| TIMEOUT            | Tool error mentions timeout or operation exceeded limit                                                                         | Retry after pause → re-observe → adapt approach       |
| NAVIGATION_FAILED  | 4xx/5xx, blank page, redirect loop                                                                                              | Check network → navigate parent URL → GoBack → skip   |
| VALIDATION_ERROR   | Form shows error message after submission                                                                                       | Read error → correct input → resubmit                 |
| ACTION_INEFFECTIVE | Action succeeded but: no visible change in screenshot, wrong element affected, partial/truncated effect, unexpected side effect | Re-observe → alt approach → JS direct → replan → skip |

Note: `ACTION_INEFFECTIVE` replaces the earlier `MCP_TOOL_LIMITATION`
to be tool-agnostic. It covers any action that technically succeeded but
did not achieve the intended effect, regardless of whether the cause is
a tool limitation, a wrong selector, or a dynamic page change.

Each entry includes:

- **Cause**: common reasons this happens (multiple, not tool-specific).
- **Identification traits**: what the agent observes that indicates this
  error type.
- **Recovery steps**: ordered escalation ladder.

**Fatal Errors** (4 types):

| Error             | Identification                          | Action                          |
| ----------------- | --------------------------------------- | ------------------------------- |
| PAGE_CRASHED      | Browser tab crashed or unresponsive     | Report crash + last known state |
| SESSION_EXPIRED   | Redirected to login, 401/403 response   | Report which step lost session  |
| PERMISSION_DENIED | Access-restricted page or feature       | Report the URL/feature blocked  |
| UNSUPPORTED_PAGE  | PDF viewer, extension, non-HTML content | Report page type and skip       |

**Decision Rule**: If recovery succeeds on 1st or 2nd attempt,
continue. If same error repeats 3+ times on same step, treat as fatal
for that step: log and skip. If a *different* error occurs during
recovery, classify it independently (don't conflate error types).

### Reference: recovery-strategies.md

Organized by strategy type. Each strategy includes: when to use,
applicable error types, tool usage, concrete example, and
success/failure criteria.

1. **Re-observe** — mandatory first step after any failure.

   - Tools: `take_snapshot` + `take_screenshot` (batched).
   - Compare with pre-action state. Note what changed and what didn't.
   - Use `list_console_messages` + `list_network_requests` for hidden
     failures.

2. **Retry with modification** — ELEMENT_NOT_FOUND, TIMEOUT.

   - Alternative selectors: try text content, ARIA role, nearby
     landmark, positional context.
   - Modified timing: add `wait_for` before retry if element may be
     loading.
   - Corrected input: for VALIDATION_ERROR, read the error message and
     fix the value.

3. **Alternative approach** — ACTION_INEFFECTIVE, escalation from retry.

   - Switch tool: if MCP `fill` failed, try `evaluate_script` with
     `element.value = '...'` + input event dispatch.
   - Switch strategy: if clicking a button didn't work, try
     `press_key(key="Enter")` on the focused element.
   - Switch target: if the intended element is misidentified, use
     `evaluate_script` to query by text content or attributes.

4. **Replan** — when the current approach is fundamentally blocked.

   - The goal is still achievable but requires a different path.
   - Example: direct navigation to a page when the menu path is broken.
   - Example: using a URL parameter to pre-fill a form when the UI
     input is unreliable.
   - Constraint: max 1 replan per original step. If replan also fails,
     skip.

5. **Handle environmental blockers** — unexpected modals, banners,
   overlays.

   - Dismiss: click close/dismiss button, press Escape.
   - Accept: click accept/OK for cookie consent, terms.
   - Navigate around: if a CAPTCHA blocks, try a different entry point.

6. **Skip and continue** — after escalation exhausted.

   - Record: what was attempted, what failed, partial progress achieved.
   - Classify: mark as \[warning\] (partially done) or \[failed\] (not
     done at all) in findings.
   - Continue: move to the next planned step without delay.

7. **Abort with report** — fatal errors only.

   - Capture: final screenshot if possible.
   - Report: error type, last known URL, steps completed, steps
     remaining.

### Plan Skill Modification

**Current** `plan/SKILL.md` Error Handling section (lines 98-109):

```markdown
## Error Handling

When a tool returns an error, classify it:

- **Recoverable** — element not found ...
- **Fatal** — page crashed ...

Load `error-taxonomy` reference for the full classification:
`load_skill(skill_name="plan", reference="error-taxonomy")`
```

**New** (simplified cross-reference):

```markdown
## Error Handling

When a tool returns an error or an action produces unexpected results,
load the `recovery` skill for structured guidance:
`load_skill(skill_name="recovery")`

The recovery skill provides error classification, diagnosis with
progress assessment, and concrete recovery strategies with escalation.
```

## Logging and Observability

For end-to-end testing validation, the following log points confirm
skill integration:

1. **Skill discovery**: `SkillRegistry.discover()` logs
   `Skills discovered (N): plan, recovery, ...` at INFO level.
2. **Skill load**: `LoadSkillTool.execute()` emits
   `Loading skill: recovery` activity description.
3. **Reference load**: `LoadSkillTool.execute()` emits
   `Loading skill reference: recovery/error-taxonomy` activity.

These are already provided by the existing skill infrastructure — no
new logging code needed. End-to-end tests can verify skill activation
by checking for these log messages.

## Future Extensions

When tasks #2 and #3 are implemented:

1. **Custom action tools**: Add a reference
   `recovery/references/custom-action-tools.md` describing tool names,
   parameters, and when to prefer them over MCP equivalents. Update
   recovery-strategies.md "Alternative approach" section to reference
   custom tools as first choice in the escalation ladder.

2. **DOM perception skill**: Add a reference
   `recovery/references/perception-tools.md` describing how to use
   enhanced DOM perception during the OBSERVE phase. The SKILL.md
   OBSERVE section can note "load perception-tools reference for
   enhanced observation" when available.

3. **Visual grounding**: If visual element identification becomes
   available, the DIAGNOSE phase can incorporate visual evidence for
   more accurate failure classification (e.g. identifying a small icon
   that snapshot misses).

4. **Domain-specific recovery**: For specific application types (e-commerce
   checkout, form wizards, SPA navigation), add domain references with
   specialized recovery patterns.

## Deliverables

1. `skills/recovery/SKILL.md` — core recovery skill.
2. `skills/recovery/references/error-taxonomy.md` — enhanced error
   classification.
3. `skills/recovery/references/recovery-strategies.md` — recovery
   playbooks.
4. Modified `skills/plan/SKILL.md` — simplified error handling section.
5. Removed `skills/plan/references/error-taxonomy.md`.

## Testing Strategy

Since skills are prompt-text documents (not executable code), testing
focuses on integration validation:

1. **Skill discovery test**: Verify `SkillRegistry` discovers the
   recovery skill and parses its frontmatter correctly.
2. **Load test**: Verify `load_skill(skill_name="recovery")` returns
   the full SKILL.md body.
3. **Reference load test**: Verify both references load without error.
4. **Plan modification test**: Verify plan skill still loads correctly
   after Error Handling section change.
5. **End-to-end smoke test** (manual): Run against a site known to
   trigger failures; verify logs show recovery skill load and reference
   load events.

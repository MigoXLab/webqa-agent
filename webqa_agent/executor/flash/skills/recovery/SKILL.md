---
name: recovery
description: Structured error recovery for failed or ineffective browser
actions.
when_to_use: When a tool returns an error, an action produces no visible effect,
or page state diverges from expectation.
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
- **Negative progress** (broke something): undo if possible
  (`evaluate_script({ code: "history.back()" })` or navigate to the
  previous URL), then re-observe.

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
- `verification-patterns` — concrete verification examples with MCP
  tools (useful during OBSERVE phase for comprehensive state checks)

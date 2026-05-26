---
name: plan
description: Decompose a task into steps with completion checkpoints.
when_to_use: For multi-step workflows or broad testing objectives.
---

# Plan Skill

Structure your approach before acting. Decompose broad objectives into
sequenced steps with completion criteria at key milestones.

## When to Use

- The task describes a multi-step workflow (login, search, checkout, etc.)
- The objective is broad ("test fundamental functionalities")
- You are unfamiliar with the page structure
- The task involves state that carries across steps (form data, cart items)

Skip this skill for single-action tasks ("click the login button").

## Planning Phases

### Phase 1: Understand the Objective

- What is the end goal? What does success look like?
- Which pages/features are involved? Ignore unrelated ones.
- What data flows through the workflow? (e.g., search query -> results -> detail page)

### Phase 2: Sequence the Steps

Order steps as a continuous workflow, each following from the previous
outcome.

- Aim for **4-8 steps** for substantial tasks, fewer for simple ones.
  Each step is one *reasoning unit* — typically 1-3 tool calls that
  achieve a single sub-goal.
- Use semantic intent, not element selectors:
  - Good: `"Click the 'Submit' button below the form"`
  - Bad: `"Click element #btn_47"` or `"Click at coordinates (400, 300)"`
- For each step, state **what** and **why**:
  - Good: `"Enter a search query to test the search flow"`
  - Bad: `"Type 'hello world' in the search box"`
- Mark dependencies between steps: if step 4 depends on data from
  step 2's outcome, say so explicitly.
  - Example: `"Step 4 uses the product name found in step 2's results"`

### Phase 3: Place Completion Checkpoints

Insert a checkpoint every 3-5 steps at key milestones.

For each checkpoint, define **what to verify** (the completion
condition), not how to verify it:

- Good: `"Verify: search results page loaded with matching items"`
- Bad: `"take_snapshot and check for a results container"`

The completion condition answers: **what state proves this milestone
was reached?** The execution cycle (system prompt Step 4) handles
the how.

Merge multiple conditions into one checkpoint to reduce round-trips:

- Good: one checkpoint verifying title + items + no error state
- Bad: separate checkpoints for each

## Observation Batching

The engine runs read-only tools concurrently. Batch independent
observations in a single turn for efficiency:

```
Turn N (one LLM response, all run in parallel):
  - take_snapshot    -> DOM structure
  - take_screenshot  -> visual state
  - list_console_messages -> JS errors
  - list_network_requests -> failed API calls
```

Use this pattern at completion checkpoints for a comprehensive view
without extra round-trips.

## Multi-Tab Workflows

You have full tab management. Use it when beneficial:

- **Preserve state:** Open a link in a new tab (`new_page`) to inspect
  it without losing the current page's form state.
- **Compare pages:** Keep the original open, navigate the new tab,
  then `select_page` back to compare.
- **Clean up:** `close_page` when a tab is no longer needed.

## Re-planning

The plan is a living document, not a fixed script. When execution
reveals new information that invalidates the plan:

- The original page structure differs from expectations.
- A step's outcome opens a different path than planned.
- A step is blocked and must be skipped.

Revise the remaining steps based on what you now know. Do not force
the original plan when reality has diverged.

## Completion

When the objective is fully achieved, **stop executing** even if you
planned more steps. Remaining steps that add no new information are
waste. State clearly what was accomplished and why remaining steps
are unnecessary.

Do not loop after completion. Do not retry successful actions.

## Error Handling

When a tool returns an error or an action produces unexpected results,
load the `recovery` skill for structured guidance:
`load_skill(skill_name="recovery")`

The recovery skill provides error classification, diagnosis with
progress assessment, and concrete recovery strategies with escalation.

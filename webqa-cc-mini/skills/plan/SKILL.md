---
name: plan
description: Decompose a task into steps with verification checkpoints.
when_to_use: For multi-step workflows or broad testing objectives.
---

# Plan Skill

Structure your approach before acting. Decompose broad objectives into
sequenced steps with verification checkpoints at key milestones.

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

- Order steps as a continuous workflow, each following from the previous outcome.
- Aim for **8-15 steps** for substantial tasks, fewer for simple ones.
- One atomic action per step — no compound instructions.
  - `"Search for 'hello world' and click the first result"` -> two steps.
- Use descriptive element references: semantic role + visual label + context.
  - Good: `"Click the blue 'Submit' button below the form"`
  - Bad: `"Click button"` or `"Click element 36"`

### Phase 3: Place Verification Checkpoints

- Insert a verification step every 3-5 actions at key milestones.
- Verify **state persistence** across steps: data entered early should appear later.
- Merge consecutive checks into one observation turn to reduce tool calls.
  - Bad: snapshot to check title, then snapshot to check button, then snapshot to check input.
  - Good: one snapshot, verify title + button + input together.

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

Use this pattern at verification checkpoints for a comprehensive view
without extra round-trips.

## Verification Strategy

Choose the right verification tool for the assertion:

| What to verify                | How                                                        |
| ----------------------------- | ---------------------------------------------------------- |
| Element exists / text content | `take_snapshot` — check accessibility tree                 |
| Page looks correct visually   | `take_screenshot` — inspect rendered output                |
| No JavaScript errors          | `list_console_messages` — check for errors                 |
| API calls succeeded           | `list_network_requests` — check status codes               |
| Complex DOM state             | `evaluate_script` — run JS assertions directly             |
| Cross-tab state               | `list_pages` + `select_page` — verify state in another tab |

Load `verification-patterns` reference for concrete examples:
`load_skill(skill_name="plan", reference="verification-patterns")`

## Multi-Tab Workflows

You have full tab management. Use it when beneficial:

- **Preserve state:** Open a link in a new tab (`new_page`) to inspect
  it without losing the current page's form state.
- **Compare pages:** Keep the original open, navigate the new tab,
  then `select_page` back to compare.
- **Clean up:** `close_page` when a tab is no longer needed.

## Completion

When the objective is fully achieved, **stop executing** even if you
planned more steps. Remaining steps that add no new information are
waste. State clearly what was accomplished and why remaining steps
are unnecessary.

Do not loop after completion. Do not retry successful actions.

## Error Handling

When a tool returns an error, classify it:

- **Recoverable** — element not found (try alternative selector),
  timeout (wait and retry), validation error (correct input).
  Adapt and continue.
- **Fatal** — page crashed, session expired, permission denied,
  unsupported page type. Report the error and stop.

Load `error-taxonomy` reference for the full classification:
`load_skill(skill_name="plan", reference="error-taxonomy")`

## Available References

Load on demand: `load_skill(skill_name="plan", reference="<name>")`

- `error-taxonomy` — 7 error categories, recovery vs abort guidance
- `verification-patterns` — concrete verification examples with MCP tools

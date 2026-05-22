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

______________________________________________________________________

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

______________________________________________________________________

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
  Wait: wait_for(selector="[data-testid='search-results']", timeout=10000)
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

______________________________________________________________________

## Strategy 2: Alternative approach

**When:** ACTION_INEFFECTIVE, or retry-with-modification failed.

Try a different tool or interaction pattern for the same operation.
The general principle: if the primary tool fails, switch to the next
tool in the priority chain before falling back to raw JS.

### Alternative tool for text input

If `fill` fails (truncated text, special characters lost, newlines
stripped), switch to `type_text`:

```
Example:
  Failed: fill(uid="chat-input", value="long multi-line text...")
  Alternative:
    1. click(uid="chat-input")   → focus the target
    2. type_text(text="long multi-line text...\nwith newlines")
```

If `type_text` also fails, fall back to `evaluate_script`:

```
evaluate_script({
  code: `
    const el = document.querySelector('textarea#content');
    const nativeSetter = Object.getOwnPropertyDescriptor(
      window.HTMLTextAreaElement.prototype, 'value'
    ).set;
    nativeSetter.call(el, 'your long text with special chars: <>&"');
    el.dispatchEvent(new Event('input', { bubbles: true }));
    el.dispatchEvent(new Event('change', { bubbles: true }));
  `
})
```

### Alternative tool for file upload

If `cdp_upload_file` fails (selector mismatch, iframe input, element
not found), try adjusting the selector first:

```
Example:
  Failed: cdp_upload_file(file_path="...", selector="input[type='file']")
  Diagnose: evaluate_script to list all file inputs:
    evaluate_script({ code: "JSON.stringify([...document.querySelectorAll('input[type=file]')].map(e => ({id: e.id, name: e.name, parent: e.parentElement?.className})))" })
  Retry with specific selector:
    cdp_upload_file(file_path="...", selector="form.upload input[type='file']")
```

If no file input is found (custom upload via drag-and-drop or API),
fall back to `evaluate_script` with `DataTransfer`:

```
evaluate_script({
  code: `
    const dt = new DataTransfer();
    dt.items.add(new File(['content'], 'test.txt', {type: 'text/plain'}));
    const dropZone = document.querySelector('.drop-area');
    dropZone.dispatchEvent(new DragEvent('drop', {dataTransfer: dt, bubbles: true}));
  `
})
```

### Other DOM operations via evaluate_script

**Click an element:**

```
evaluate_script({
  code: "document.querySelector('button.submit-btn').click()"
})
```

**Check/uncheck a checkbox:**

```
evaluate_script({
  code: `
    const cb = document.querySelector('input[type=checkbox]#agree');
    cb.checked = true;
    cb.dispatchEvent(new Event('change', { bubbles: true }));
  `
})
```

**Select a dropdown option:**

```
evaluate_script({
  code: `
    const sel = document.querySelector('select#country');
    sel.value = 'US';
    sel.dispatchEvent(new Event('change', { bubbles: true }));
  `
})
```

**Always verify after any alternative approach:**

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

______________________________________________________________________

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

______________________________________________________________________

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

______________________________________________________________________

## Strategy 5: Skip and record

**When:** All recovery attempts exhausted (2 retries, alternative
approach, and replan all failed).

**What to record** (include in your narration and final report):

- What step was being attempted.
- What errors occurred (with error type from taxonomy).
- What recovery strategies were tried.
- What partial progress was achieved (if any).
- Classification: \[warning\] if partially done, \[failed\] if not done.

**Then:** Move to the next planned step without delay. Do not attempt
the skipped step again later.

______________________________________________________________________

## Strategy 6: Abort with report

**When:** Fatal error only (PAGE_CRASHED, SESSION_EXPIRED,
PERMISSION_DENIED, UNSUPPORTED_PAGE).

**Steps:**

1. Capture final state: `take_screenshot` if possible.
2. Report: error type, last known URL, steps completed so far, steps
   remaining.
3. Mark all uncompleted steps as \[failed\] with the fatal error as
   cause.
4. Do not attempt further recovery or step execution.

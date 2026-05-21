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
  characters dropped, upload selector missed the file input), page
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
  3. Try an alternative tool for the same operation (e.g., `type_text`
     instead of `fill` for text input; adjust `cdp_upload_file`
     selector for file upload). See recovery-strategies reference.
  4. If no alternative tool works, use `evaluate_script` for direct
     DOM manipulation (set input values, dispatch events).
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

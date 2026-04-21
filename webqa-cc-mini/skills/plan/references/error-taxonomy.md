# Error Taxonomy

Classify tool errors to decide whether to adapt or stop.

## Recoverable Errors (adapt and continue)

### ELEMENT_NOT_FOUND

The target element is missing from the current DOM.

- **Cause:** Page hasn't loaded fully, element is inside a collapsed
  section, or selector is wrong.
- **Recovery:** Take a fresh snapshot. Try an alternative selector
  (text content, ARIA role, nearby landmark). If the element truly
  doesn't exist, skip the step and note it.

### TIMEOUT

A `wait_for` or action exceeded the time limit.

- **Cause:** Slow network, heavy page, async content not yet rendered.
- **Recovery:** Retry once after a brief pause. If it times out again,
  take a snapshot to see what actually loaded and adapt.

### NAVIGATION_FAILED

The page didn't load or returned an error (4xx/5xx).

- **Cause:** Broken link, server error, redirect loop.
- **Recovery:** Check `list_network_requests` for the failing request.
  Try navigating to a parent URL. If the page is genuinely down, report
  and move to the next planned step.

### VALIDATION_ERROR

A form rejected the input (client-side or server-side).

- **Cause:** Invalid data format, required field missing, constraint
  violation.
- **Recovery:** Read the error message from the DOM. Correct the input
  and resubmit. If the validation rule is unclear, take a snapshot to
  inspect the form state.

## Fatal Errors (report and stop)

### PAGE_CRASHED

The browser tab crashed or became unresponsive.

- **Recovery:** None. Report the crash and the last known state.

### SESSION_EXPIRED

Authentication was lost (redirected to login, 401/403 response).

- **Recovery:** None within the current run. Report which step lost
  the session and what the redirect target was.

### PERMISSION_DENIED

The page or feature is access-restricted.

- **Recovery:** None. Report the permission error and the URL/feature
  that was blocked.

### UNSUPPORTED_PAGE

The page is a PDF viewer, browser extension, or other non-HTML content.

- **Recovery:** None. Report the page type and skip.

## Decision Rule

If recovery succeeds on the first or second attempt, continue the plan.
If the same error repeats 3+ times on the same step, treat it as fatal
for that step: log the error, skip it, and proceed with the next step.
